# Phase 1: Observability Foundation

> **Status:** DESIGN  
> **Priority:** P0  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** None  

---

## 1. Executive Summary

Phase 1 establishes the observability and reliability foundation that all subsequent phases depend on. Without structured logging, health checks, and error tracking, we cannot safely implement or debug any of the later phases.

### Deliverables

| Component | Module | Lines (est.) |
|-----------|--------|-------------|
| Structured logging | `logging_config.py` | ~120 |
| Correlation ID middleware | `middleware.py` | ~80 |
| Health check endpoint | `health.py` | ~90 |
| Request validation | `validation.py` | ~100 |
| Centralized error handler | `errors.py` | ~80 |
| Timeout enforcement | `timeouts.py` | ~60 |
| Tests | `tests/test_phase1_*.py` | ~400 |
| **Total** | | **~930** |

---

## 2. Current State Analysis

### 2.1 Logging (or lack thereof)

```bash
$ grep -rn "import logging" ollamadev_mcp_server/
# → 0 results
```

**Evidence:** No module in the codebase imports Python's `logging` module. The only logs come from uvicorn's access logger, which records HTTP method/path/status but no tool names, arguments, latencies, or error details.

**Impact:** When an agent workflow fails, there is no way to reconstruct what happened. The `server_run.log` shows only `POST /mcp 200 OK` lines — no indication of which tools were called, how long they took, or whether any errors occurred internally.

### 2.2 Health Checks

The only health mechanism is the `ping` tool (`meta.py:~250`):

```python
@mcp.tool()
def ping() -> str:
    return json.dumps({"pong": True, "uptime_seconds": round(time.time() - _START, 1)})
```

**Problems:**
- Requires a full MCP handshake to invoke (not a simple HTTP GET)
- Does not check dependency health (Ollama, workspace filesystem)
- No liveness/readiness distinction for container orchestration
- No way for monitoring systems to poll without MCP client

### 2.3 Error Handling

Errors are raised directly as exceptions:

```python
# filesystem.py:17
raise PermissionError(f"Path escapes workspace: {relative}")

# code.py:121
raise ValueError(f"symbol_type must be one of: any, class, function, property")

# meta.py:483
raise RuntimeError("Neither ANTHROPIC_API_KEY nor ANTHROPIC_AUTH_TOKEN is set...")
```

**Problems:**
- No centralized error handler — each tool raises different exception types
- No error context (which tool, which arguments, what correlation ID)
- No error aggregation or alerting
- Sensitive data (API keys, paths) may leak into error messages
- No distinction between user errors and system errors

### 2.4 Timeouts

Timeouts are inconsistent:

| Location | Timeout | Notes |
|----------|---------|-------|
| `code.py:38` | 30s | grep subprocess |
| `meta.py:470` | 120s | LLM HTTP call |
| `sandbox.py:23` | 300s | Default for _run() |
| `build.py:490` | 900s | Instrumented tests |
| `sprint.py` | None | Autonomous loop has no overall timeout |

**Problems:**
- No global request timeout
- Autonomous sprint can run indefinitely
- No timeout propagation through nested calls

---

## 3. Proposed Architecture

### 3.1 Structured Logging

**Design:** Use Python's `logging` module with a JSON formatter. Add `structlog` as an optional enhancement for context binding.

```python
# ollamadev_mcp_server/logging_config.py
"""Structured logging configuration for the OllamaDev MCP server."""

import json
import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

# Context variables for request-scoped data
_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_tool_name: ContextVar[str] = ContextVar("tool_name", default="-")
_agent_id: ContextVar[str] = ContextVar("agent_id", default="-")


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "request_id": _request_id.get("-"),
            "tool_name": _tool_name.get("-"),
            "agent_id": _agent_id.get("-"),
        }
        # Add extra fields if present
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }
        return json.dumps(log_entry, ensure_ascii=False)


def configure_logging(level: str | None = None) -> None:
    """Configure structured JSON logging for the entire application."""
    log_level = level or os.environ.get("LOG_LEVEL", "INFO").upper()
    log_format = os.environ.get("LOG_FORMAT", "json").lower()

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level, logging.INFO))

    # Clear existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
    root.addHandler(handler)

    # Quiet noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.INFO)


def new_request_id() -> str:
    """Generate a new unique request ID."""
    return uuid.uuid4().hex[:16]


def bind_request(request_id: str, tool_name: str = "-", agent_id: str = "-") -> None:
    """Bind request-scoped context for the current coroutine."""
    _request_id.set(request_id)
    _tool_name.set(tool_name)
    _agent_id.set(agent_id)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name."""
    return logging.getLogger(name)
```

### 3.2 Correlation ID Middleware

**Design:** Wrap tool calls with request context binding.

```python
# ollamadev_mcp_server/middleware.py
"""Request middleware for correlation IDs and tool call tracking."""

import time
from typing import Any, Callable

from ollamadev_mcp_server.logging_config import (
    bind_request,
    get_logger,
    new_request_id,
)

logger = get_logger(__name__)


class ToolCallTracker:
    """Track tool call metrics for the current request."""

    def __init__(self, request_id: str):
        self.request_id = request_id
        self.start_time = time.monotonic()
        self.calls: list[dict[str, Any]] = []

    def record_call(self, tool_name: str, duration_ms: float, success: bool, error: str | None = None) -> None:
        self.calls.append({
            "tool_name": tool_name,
            "duration_ms": round(duration_ms, 2),
            "success": success,
            "error": error,
        })

    def summary(self) -> dict[str, Any]:
        total_duration = (time.monotonic() - self.start_time) * 1000
        return {
            "request_id": self.request_id,
            "total_duration_ms": round(total_duration, 2),
            "tool_calls": len(self.calls),
            "success_count": sum(1 for c in self.calls if c["success"]),
            "error_count": sum(1 for c in self.calls if not c["success"]),
        }
```

### 3.3 Health Check Endpoint

**Design:** A module that checks dependency health and exposes it via a tool.

```python
# ollamadev_mcp_server/health.py
"""Health check tools for the OllamaDev MCP server."""

import json
import os
import time

import requests

from ollamadev_mcp_server.constants import OLLAMA_URL, WORKSPACE_ROOT
from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)
_START = time.time()


def _check_workspace() -> dict:
    """Check workspace filesystem health."""
    try:
        if not WORKSPACE_ROOT.exists():
            return {"status": "DOWN", "detail": f"Workspace root does not exist: {WORKSPACE_ROOT}"}
        if not os.access(str(WORKSPACE_ROOT), os.R_OK | os.W_OK):
            return {"status": "DEGRADED", "detail": "Workspace root is not readable/writable"}
        return {"status": "UP", "path": str(WORKSPACE_ROOT)}
    except Exception as exc:
        return {"status": "DOWN", "detail": str(exc)}


def _check_ollama() -> dict:
    """Check Ollama API health."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            return {"status": "UP", "url": OLLAMA_URL, "model_count": len(models)}
        return {"status": "DEGRADED", "detail": f"HTTP {resp.status_code}"}
    except requests.ConnectionError:
        return {"status": "DOWN", "detail": f"Cannot connect to {OLLAMA_URL}"}
    except Exception as exc:
        return {"status": "DOWN", "detail": str(exc)}


def _check_settings_file() -> dict:
    """Check settings file accessibility."""
    from ollamadev_mcp_server.persistence import settings_file_path
    path = settings_file_path()
    parent = path.parent
    if not parent.exists():
        return {"status": "DEGRADED", "detail": f"Settings directory does not exist: {parent}"}
    return {"status": "UP", "path": str(path)}


def get_health_status(detailed: bool = False) -> dict:
    """Compute overall health status."""
    checks = {
        "workspace": _check_workspace(),
        "ollama": _check_ollama(),
        "settings": _check_settings_file(),
    }

    statuses = [c["status"] for c in checks.values()]
    if all(s == "UP" for s in statuses):
        overall = "UP"
    elif any(s == "DOWN" for s in statuses):
        overall = "DOWN"
    else:
        overall = "DEGRADED"

    result = {
        "status": overall,
        "uptime_seconds": round(time.time() - _START, 1),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if detailed:
        result["checks"] = checks
    return result
```

### 3.4 Request Validation

**Design:** Input validation decorators for tool functions.

```python
# ollamadev_mcp_server/validation.py
"""Input validation utilities for MCP tool arguments."""

import re
from typing import Any, Callable

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

# Limits
MAX_PATH_LENGTH = 1024
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB
MAX_PATTERN_LENGTH = 4096
MAX_TOOL_ARGUMENT_SIZE = 1 * 1024 * 1024  # 1 MB

# Path traversal patterns
_DANGEROUS_PATH_PATTERNS = [
    re.compile(r"\.\.[\\/]"),       # ../ or ..\
    re.compile(r"^[\\/]"),          # absolute paths
    re.compile(r"[\x00-\x1f]"),     # control characters
]


def validate_path(path: str, *, allow_absolute: bool = False) -> str:
    """Validate a relative path argument."""
    if not path:
        raise ValueError("Path cannot be empty")
    if len(path) > MAX_PATH_LENGTH:
        raise ValueError(f"Path too long: {len(path)} > {MAX_PATH_LENGTH}")
    if not allow_absolute:
        for pattern in _DANGEROUS_PATH_PATTERNS:
            if pattern.search(path):
                raise ValueError(f"Invalid path characters in: {path!r}")
    return path


def validate_content(content: str, *, max_length: int = MAX_CONTENT_LENGTH) -> str:
    """Validate file content argument."""
    if len(content.encode("utf-8")) > max_length:
        raise ValueError(f"Content too large: {len(content)} chars > {max_length} bytes")
    return content


def validate_pattern(pattern: str) -> str:
    """Validate a regex pattern argument."""
    if not pattern:
        raise ValueError("Pattern cannot be empty")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError(f"Pattern too long: {len(pattern)} > {MAX_PATTERN_LENGTH}")
    # Validate regex syntax
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"Invalid regex pattern: {exc}")
    return pattern


def validate_positive_int(value: int, *, name: str, max_value: int = 100000) -> int:
    """Validate a positive integer argument."""
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    if value > max_value:
        raise ValueError(f"{name} too large: {value} > {max_value}")
    return value
```

### 3.5 Centralized Error Handler

```python
# ollamadev_mcp_server/errors.py
"""Centralized error handling for the OllamaDev MCP server."""

import json
from typing import Any

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)


class OllamaDevError(Exception):
    """Base exception for all OllamaDev errors."""

    def __init__(self, message: str, *, code: str = "UNKNOWN", status_code: int = 500, context: dict | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.context = context or {}


class ValidationError(OllamaDevError):
    """Raised when tool input validation fails."""
    def __init__(self, message: str, **context: Any):
        super().__init__(message, code="VALIDATION_ERROR", status_code=400, context=context)


class SecurityError(OllamaDevError):
    """Raised when a security check fails."""
    def __init__(self, message: str, **context: Any):
        super().__init__(message, code="SECURITY_ERROR", status_code=403, context=context)


class DependencyError(OllamaDevError):
    """Raised when an external dependency is unavailable."""
    def __init__(self, message: str, **context: Any):
        super().__init__(message, code="DEPENDENCY_ERROR", status_code=503, context=context)


class TimeoutError_(OllamaDevError):
    """Raised when an operation times out."""
    def __init__(self, message: str, **context: Any):
        super().__init__(message, code="TIMEOUT", status_code=504, context=context)


def format_error_response(error: OllamaDevError) -> str:
    """Format an error as a JSON response string."""
    return json.dumps({
        "error": {
            "code": error.code,
            "message": error.message,
            "context": error.context,
        }
    }, indent=2)


def handle_tool_error(exc: Exception, tool_name: str) -> str:
    """Central error handler for tool exceptions. Returns a JSON error string."""
    if isinstance(exc, OllamaDevError):
        logger.warning(
            "Tool error: %s — %s",
            tool_name, exc.message,
            extra={"extra_data": {"code": exc.code, "context": exc.context}},
        )
        return format_error_response(exc)

    # Unexpected errors — log with full traceback
    logger.exception("Unexpected error in tool %s", tool_name)
    return json.dumps({
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "An internal error occurred. Check server logs for details.",
        }
    }, indent=2)
```

### 3.6 Timeout Enforcement

```python
# ollamadev_mcp_server/timeouts.py
"""Timeout configuration and enforcement."""

import asyncio
import os
from typing import Any, Callable

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

# Default timeouts (seconds)
DEFAULT_TOOL_TIMEOUT = int(os.environ.get("DEFAULT_TOOL_TIMEOUT", "60"))
DEFAULT_LLM_TIMEOUT = int(os.environ.get("DEFAULT_LLM_TIMEOUT", "120"))
DEFAULT_SHELL_TIMEOUT = int(os.environ.get("DEFAULT_SHELL_TIMEOUT", "300"))
DEFAULT_GRADLE_TIMEOUT = int(os.environ.get("DEFAULT_GRADLE_TIMEOUT", "600"))
DEFAULT_AUTONOMOUS_TIMEOUT = int(os.environ.get("DEFAULT_AUTONOMOUS_TIMEOUT", "3600"))

# Per-tool timeout overrides
TOOL_TIMEOUTS: dict[str, int] = {
    "search_workspace": 30,
    "get_file_outline": 30,
    "find_symbol": 30,
    "get_todos": 30,
    "run_pytest": DEFAULT_SHELL_TIMEOUT,
    "run_gradle_test_command": DEFAULT_GRADLE_TIMEOUT,
    "run_gradle_tests": DEFAULT_GRADLE_TIMEOUT,
    "run_gradle_build": DEFAULT_GRADLE_TIMEOUT,
    "run_lint": 120,
    "run_detekt": 120,
    "run_instrumented_tests": 900,
    "run_screenshot_tests": 900,
    "run_shell_command": DEFAULT_SHELL_TIMEOUT,
    "suggest_next_action": DEFAULT_LLM_TIMEOUT,
    "run_autonomous_sprint": DEFAULT_AUTONOMOUS_TIMEOUT,
}


def get_timeout(tool_name: str) -> int:
    """Get the timeout for a specific tool."""
    return TOOL_TIMEOUTS.get(tool_name, DEFAULT_TOOL_TIMEOUT)
```

---

## 4. Implementation Plan

### Step 1: Create logging module (Day 1, morning)

1. Create `ollamadev_mcp_server/logging_config.py`
2. Add `configure_logging()` call to `server.py:main()`
3. Add `get_logger()` calls to all existing modules
4. Write `tests/test_logging.py`

### Step 2: Create error handling module (Day 1, afternoon)

1. Create `ollamadev_mcp_server/errors.py`
2. Migrate existing exceptions to `OllamaDevError` subclasses
3. Add `handle_tool_error()` wrapper
4. Write `tests/test_errors.py`

### Step 3: Create validation module (Day 2, morning)

1. Create `ollamadev_mcp_server/validation.py`
2. Add validation calls to filesystem tools
3. Add validation calls to code tools
4. Write `tests/test_validation.py`

### Step 4: Create health check module (Day 2, afternoon)

1. Create `ollamadev_mcp_server/health.py`
2. Register health tools in `server.py`
3. Write `tests/test_health.py`

### Step 5: Create timeout module (Day 3, morning)

1. Create `ollamadev_mcp_server/timeouts.py`
2. Apply timeouts to subprocess calls
3. Write `tests/test_timeouts.py`

### Step 6: Integration and verification (Day 3, afternoon)

1. Run full test suite
2. Start server and verify structured logs
3. Verify health endpoint
4. Update README with new configuration options

---

## 5. Impact Assessment

### 5.1 Backward Compatibility

| Change | Breaking? | Migration |
|--------|-----------|-----------|
| New logging module | No | Additive |
| New error types | No | Existing exceptions still work |
| New validation | Partial | Invalid inputs that previously succeeded silently will now raise |
| New health tools | No | Additive |
| New timeouts | Partial | Operations that previously ran indefinitely will now timeout |

### 5.2 New Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `LOG_FORMAT` | `json` | Log format (json, text) |
| `DEFAULT_TOOL_TIMEOUT` | `60` | Default tool timeout in seconds |
| `DEFAULT_LLM_TIMEOUT` | `120` | LLM call timeout in seconds |
| `DEFAULT_SHELL_TIMEOUT` | `300` | Shell command timeout in seconds |
| `DEFAULT_GRADLE_TIMEOUT` | `600` | Gradle command timeout in seconds |
| `DEFAULT_AUTONOMOUS_TIMEOUT` | `3600` | Autonomous sprint timeout in seconds |

### 5.3 New Dependencies

None. All modules use Python standard library only.

---

## 6. Verification Plan

### 6.1 Unit Tests

```bash
# All new modules must have >90% coverage
pytest tests/test_logging.py tests/test_errors.py tests/test_validation.py \
       tests/test_health.py tests/test_timeouts.py -v --cov=ollamadev_mcp_server
```

### 6.2 Integration Tests

```bash
# Start server and verify structured logs
uv run serve &
SERVER_PID=$!

# Call a tool and check log output
curl -s -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ping","arguments":{}}}'

# Verify JSON log output
# Expected: {"timestamp":"...","level":"INFO","message":"Tool call: ping",...}

kill $SERVER_PID
```

### 6.3 Regression Tests

```bash
# All existing tests must still pass
pytest -q
# Expected: 105 passed (or more if new tests added)
```

---

## 7. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Logging overhead slows tools | JSON formatting is fast; use lazy evaluation for expensive fields |
| Validation breaks existing agents | Start with warnings, escalate to errors after 1 release |
| Timeout kills legitimate long operations | Make timeouts configurable per-tool via env vars |
| Health check leaks internal info | Only expose status, not paths or error details in summary mode |

---

## 8. Success Criteria

- [ ] All server logs are structured JSON
- [ ] Every tool call has a correlation ID
- [ ] Health check returns dependency status
- [ ] All tool inputs are validated
- [ ] All errors are caught and logged with context
- [ ] All tools have configurable timeouts
- [ ] All existing tests pass
- [ ] New test coverage > 90% for new modules
- [ ] Zero new pytest warnings

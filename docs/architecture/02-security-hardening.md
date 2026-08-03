# Phase 2: Security Hardening

> **Status:** DESIGN  
> **Priority:** P0  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** Phase 1 (logging for audit trail)  

---

## 1. Executive Summary

Phase 2 addresses critical security gaps in the MCP server. Currently, the server exposes 46 tools over HTTP with **no authentication, no rate limiting, and no CORS restrictions**. Any network-accessible client can invoke destructive tools like `delete_workspace_file`, `run_shell_command`, and `reset_server_settings`.

### Threat Model

```
                    ┌─────────────────────────────┐
                    │      ATTACK SURFACE          │
                    │                              │
  Internet ────────►│  HTTP :5000/mcp (no auth)   │
                    │                              │
                    │  ┌────────────────────────┐  │
                    │  │ 46 tools               │  │
                    │  │  ├─ 5 filesystem (rw)  │  │
                    │  │  ├─ 4 code (read)      │  │
                    │  │  ├─ 12 build (exec)    │  │
                    │  │  ├─ 4 sandbox (exec)   │  │
                    │  │  ├─ 3 git (rw)         │  │
                    │  │  ├─ 1 shell (ARBITRARY)│  │
                    │  │  └─ 3 settings (rw)    │  │
                    │  └────────────────────────┘  │
                    │                              │
                    │  ┌────────────────────────┐  │
                    │  │ WORKSPACE_ROOT (rw)    │  │
                    │  │ /home/userland/OllamaDev│ │
                    │  └────────────────────────┘  │
                    └─────────────────────────────┘
```

### Deliverables

| Component | Module | Lines (est.) |
|-----------|--------|-------------|
| Authentication | `auth.py` | ~120 |
| Rate limiting | `rate_limit.py` | ~100 |
| Input sanitization | `sanitization.py` | ~80 |
| Audit logging | `audit.py` | ~100 |
| CORS configuration | `cors.py` | ~60 |
| Security middleware | `security_middleware.py` | ~80 |
| Tests | `tests/test_phase2_*.py` | ~350 |
| **Total** | | **~890** |

---

## 2. Current State Analysis

### 2.1 Authentication: NONE

**Evidence:** `server.py:31` — `mcp.run(transport="streamable-http", host="0.0.0.0", port=5000)` with no authentication middleware.

**Risk:** Any client that can reach port 5000 can invoke any tool, including:
- `run_shell_command` — arbitrary code execution
- `delete_workspace_file` — data destruction
- `update_server_settings` — configuration manipulation
- `reset_server_settings` — configuration wipe

### 2.2 Rate Limiting: NONE

**Evidence:** No rate limiting code exists anywhere in the codebase.

**Risk:** A malicious or buggy client can:
- Flood the server with requests (DoS)
- Exhaust LLM API quotas via `suggest_next_action`
- Fill disk via repeated `write_workspace_file` calls
- Trigger expensive Gradle builds repeatedly

### 2.3 Input Sanitization: PARTIAL

**Evidence:** `filesystem.py:12-18` — `_safe_path()` uses string prefix matching:

```python
def _safe_path(relative: str) -> Path:
    target = (WORKSPACE_ROOT / relative).resolve()
    workspace = WORKSPACE_ROOT.resolve()
    if not str(target).startswith(str(workspace)):
        raise PermissionError(f"Path escapes workspace: {relative}")
    return target
```

**Risk:** String-based path traversal check is vulnerable to:
- Null bytes in paths
- Unicode normalization attacks
- Symlink following (resolved path may differ from checked path)
- Case sensitivity issues on some filesystems

### 2.4 Audit Logging: NONE

**Evidence:** No audit trail for destructive operations. The `delete_workspace_file` tool logs nothing.

**Risk:** Cannot reconstruct what happened after a destructive operation. No accountability.

### 2.5 CORS: NONE

**Evidence:** No CORS headers configured. The MCP SDK may handle this, but it's not explicit.

**Risk:** Browser-based attacks (CSRF) if the server is accessed from a web interface.

---

## 3. Proposed Architecture

### 3.1 Authentication Layer

**Design:** Bearer token authentication with configurable API key.

```python
# ollamadev_mcp_server/auth.py
"""Authentication middleware for the OllamaDev MCP server."""

import hashlib
import hmac
import os
import time
from typing import Any

from ollamadev_mcp_server.errors import SecurityError
from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

# Configuration
AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "false").lower() == "true"
API_KEY = os.environ.get("API_KEY", "")
API_KEY_HASH = os.environ.get("API_KEY_HASH", "")  # SHA-256 hash of API key
AUTH_TOKEN_MAX_AGE = int(os.environ.get("AUTH_TOKEN_MAX_AGE", "86400"))  # 24 hours

# Paths that don't require authentication
PUBLIC_PATHS = frozenset({"/health", "/ping"})


def verify_api_key(provided_key: str) -> bool:
    """Verify an API key against the configured key or hash."""
    if not provided_key:
        return False
    
    # Check against plain key (development only)
    if API_KEY and hmac.compare_digest(provided_key, API_KEY):
        return True
    
    # Check against hashed key (production)
    if API_KEY_HASH:
        provided_hash = hashlib.sha256(provided_key.encode()).hexdigest()
        if hmac.compare_digest(provided_hash, API_KEY_HASH):
            return True
    
    return False


def extract_bearer_token(auth_header: str | None) -> str | None:
    """Extract bearer token from Authorization header."""
    if not auth_header:
        return None
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


def require_auth(path: str, auth_header: str | None) -> dict[str, Any]:
    """Check authentication for a request. Returns client context or raises SecurityError."""
    if not AUTH_ENABLED:
        return {"authenticated": False, "client_id": "anonymous"}
    
    if path in PUBLIC_PATHS:
        return {"authenticated": False, "client_id": "public"}
    
    token = extract_bearer_token(auth_header)
    if not token:
        logger.warning("Missing authentication token for path: %s", path)
        raise SecurityError("Missing or invalid authentication token")
    
    if not verify_api_key(token):
        logger.warning("Invalid authentication token for path: %s", path)
        raise SecurityError("Invalid authentication token")
    
    # Generate a client ID from the token (for audit logging)
    client_id = hashlib.sha256(token.encode()).hexdigest()[:16]
    logger.info("Authenticated client: %s", client_id)
    return {"authenticated": True, "client_id": client_id}
```

### 3.2 Rate Limiting

**Design:** Token bucket rate limiter with per-IP and per-tool limits.

```python
# ollamadev_mcp_server/rate_limit.py
"""Rate limiting for the OllamaDev MCP server."""

import os
import time
from collections import defaultdict
from typing import Any

from ollamadev_mcp_server.errors import OllamaDevError
from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

# Configuration
RATE_LIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "true").lower() == "true"
DEFAULT_RATE_LIMIT = int(os.environ.get("DEFAULT_RATE_LIMIT", "100"))  # requests per minute
DEFAULT_BURST_LIMIT = int(os.environ.get("DEFAULT_BURST_LIMIT", "20"))  # burst size

# Per-tool rate limits (requests per minute)
TOOL_RATE_LIMITS: dict[str, int] = {
    "suggest_next_action": 10,  # LLM calls are expensive
    "run_shell_command": 5,     # Destructive
    "run_gradle_tests": 3,      # Expensive
    "run_gradle_build": 3,      # Expensive
    "run_autonomous_sprint": 1, # Very expensive
}


class TokenBucket:
    """Token bucket rate limiter."""

    def __init__(self, rate: int, burst: int):
        self.rate = rate  # tokens per second
        self.burst = burst  # max tokens
        self.tokens = float(burst)
        self.last_update = time.monotonic()

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns True if successful."""
        now = time.monotonic()
        elapsed = now - self.last_update
        self.last_update = now
        
        # Add tokens based on elapsed time
        self.tokens = min(self.burst, self.tokens + elapsed * (self.rate / 60.0))
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False


class RateLimiter:
    """Per-client rate limiter."""

    def __init__(self):
        self._buckets: dict[str, TokenBucket] = {}
        self._tool_buckets: dict[str, dict[str, TokenBucket]] = defaultdict(dict)

    def check_rate_limit(self, client_id: str, tool_name: str | None = None) -> None:
        """Check rate limit for a client. Raises OllamaDevError if exceeded."""
        if not RATE_LIMIT_ENABLED:
            return

        # Check global rate limit
        if client_id not in self._buckets:
            self._buckets[client_id] = TokenBucket(DEFAULT_RATE_LIMIT, DEFAULT_BURST_LIMIT)
        
        if not self._buckets[client_id].consume():
            logger.warning("Rate limit exceeded for client: %s", client_id)
            raise OllamaDevError(
                "Rate limit exceeded. Please wait before making more requests.",
                code="RATE_LIMIT_EXCEEDED",
                status_code=429,
            )

        # Check per-tool rate limit
        if tool_name and tool_name in TOOL_RATE_LIMITS:
            limit = TOOL_RATE_LIMITS[tool_name]
            if client_id not in self._tool_buckets[tool_name]:
                self._tool_buckets[tool_name][client_id] = TokenBucket(limit, max(1, limit // 5))
            
            if not self._tool_buckets[tool_name][client_id].consume():
                logger.warning(
                    "Tool rate limit exceeded for client: %s, tool: %s",
                    client_id, tool_name,
                )
                raise OllamaDevError(
                    f"Rate limit exceeded for tool '{tool_name}'. Limit: {limit}/min",
                    code="TOOL_RATE_LIMIT_EXCEEDED",
                    status_code=429,
                )


# Global rate limiter instance
_rate_limiter = RateLimiter()


def check_rate_limit(client_id: str, tool_name: str | None = None) -> None:
    """Check rate limit for a client."""
    _rate_limiter.check_rate_limit(client_id, tool_name)
```

### 3.3 Input Sanitization

**Design:** Enhanced path validation and input sanitization.

```python
# ollamadev_mcp_server/sanitization.py
"""Input sanitization for the OllamaDev MCP server."""

import os
import re
from pathlib import Path

from ollamadev_mcp_server.errors import SecurityError, ValidationError
from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

# Dangerous patterns
_NULL_BYTE = re.compile(r"\x00")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_PATH_TRAVERSAL = re.compile(r"(?:^|[\\/])\\.\\.(?:[\\/]|$)")

# Shell metacharacters that could be used for injection
_SHELL_METACHARACTERS = re.compile(r"[;&|`$(){}\\[\\]<>!?*~\\\\'\"]")


def sanitize_path(path: str, *, workspace_root: Path) -> Path:
    """Sanitize and validate a relative path."""
    # Check for null bytes
    if _NULL_BYTE.search(path):
        raise SecurityError("Path contains null bytes")
    
    # Check for control characters
    if _CONTROL_CHARS.search(path):
        raise SecurityError("Path contains control characters")
    
    # Check for path traversal
    if _PATH_TRAVERSAL.search(path):
        raise SecurityError(f"Path traversal detected: {path!r}")
    
    # Resolve the path
    target = (workspace_root / path).resolve()
    workspace = workspace_root.resolve()
    
    # Verify the resolved path is within workspace
    # Use os.path.commonpath for robust comparison
    try:
        common = os.path.commonpath([str(target), str(workspace)])
        if common != str(workspace):
            raise SecurityError(f"Path escapes workspace: {path!r}")
    except ValueError:
        # On Windows, paths on different drives raise ValueError
        raise SecurityError(f"Path on different drive: {path!r}")
    
    return target


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename to prevent directory traversal or special file creation."""
    # Remove path separators
    filename = filename.replace("/", "_").replace("\\", "_")
    # Remove null bytes
    filename = _NULL_BYTE.sub("", filename)
    # Remove control characters
    filename = _CONTROL_CHARS.sub("", filename)
    # Remove leading dots (hidden files)
    filename = filename.lstrip(".")
    # Limit length
    if len(filename) > 255:
        filename = filename[:255]
    # Reject empty filenames
    if not filename:
        raise ValidationError("Invalid filename")
    return filename


def sanitize_shell_command(command: str) -> str:
    """Sanitize a shell command for logging (not for execution)."""
    # For logging purposes, mask potentially sensitive data
    # Mask API keys, tokens, etc.
    sanitized = re.sub(r"(api[_-]?key|token|password|secret)\\s*[=:]\\s*\\S+", r"\\1=***", command, flags=re.IGNORECASE)
    return sanitized


def validate_file_content(content: str, *, max_size: int = 10 * 1024 * 1024) -> None:
    """Validate file content before writing."""
    # Check size
    content_bytes = content.encode("utf-8")
    if len(content_bytes) > max_size:
        raise ValidationError(f"Content too large: {len(content_bytes)} bytes > {max_size} bytes")
    
    # Check for null bytes (binary content)
    if "\x00" in content:
        raise ValidationError("Content contains null bytes (binary content not allowed)")
```

### 3.4 Audit Logging

**Design:** Structured audit log for all destructive operations.

```python
# ollamadev_mcp_server/audit.py
"""Audit logging for destructive operations."""

import json
import time
from pathlib import Path
from typing import Any

from ollamadev_mcp_server.constants import STORE_DIR
from ollamadev_mcp_server.logging_config import get_logger, _request_id

logger = get_logger(__name__)

# Audit log file
AUDIT_LOG_FILE = STORE_DIR / "audit.log"

# Operations that require audit logging
AUDITABLE_OPERATIONS = frozenset({
    "write_workspace_file",
    "delete_workspace_file",
    "move_workspace_file",
    "apply_file_patch",
    "add_gradle_dependency",
    "git_commit_checkpoint",
    "run_shell_command",
    "update_server_settings",
    "reset_server_settings",
    "store_memory",
    "clear_memory",
})


def audit_log(
    operation: str,
    client_id: str,
    arguments: dict[str, Any],
    result: str | None = None,
    error: str | None = None,
) -> None:
    """Log an auditable operation."""
    if operation not in AUDITABLE_OPERATIONS:
        return

    # Mask sensitive arguments
    masked_args = _mask_sensitive_args(arguments)

    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "request_id": _request_id.get("-"),
        "operation": operation,
        "client_id": client_id,
        "arguments": masked_args,
        "result_preview": result[:500] if result else None,
        "error": error,
    }

    # Write to audit log file
    try:
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.error("Failed to write audit log: %s", exc)

    # Also log via structured logging
    logger.info(
        "AUDIT: %s by %s",
        operation, client_id,
        extra={"extra_data": entry},
    )


def _mask_sensitive_args(args: dict[str, Any]) -> dict[str, Any]:
    """Mask sensitive values in arguments."""
    sensitive_keys = {"api_key", "token", "password", "secret", "content"}
    masked = {}
    for key, value in args.items():
        if any(s in key.lower() for s in sensitive_keys):
            if isinstance(value, str) and len(value) > 10:
                masked[key] = value[:5] + "***" + value[-5:]
            else:
                masked[key] = "***"
        else:
            masked[key] = value
    return masked


def get_audit_log_entries(limit: int = 100) -> list[dict]:
    """Read recent audit log entries."""
    if not AUDIT_LOG_FILE.exists():
        return []
    
    entries = []
    try:
        with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines[-limit:]:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    
    return list(reversed(entries))  # Most recent first
```

### 3.5 CORS Configuration

**Design:** Explicit CORS headers for browser-based clients.

```python
# ollamadev_mcp_server/cors.py
"""CORS configuration for the OllamaDev MCP server."""

import os

# Configuration
CORS_ENABLED = os.environ.get("CORS_ENABLED", "true").lower() == "true"
CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "*").split(",")
CORS_ALLOWED_METHODS = os.environ.get("CORS_ALLOWED_METHODS", "POST,OPTIONS").split(",")
CORS_ALLOWED_HEADERS = os.environ.get("CORS_ALLOWED_HEADERS", "Content-Type,Authorization,MCP-Protocol-Version,Mcp-Session-Id").split(",")


def get_cors_headers(origin: str | None = None) -> dict[str, str]:
    """Get CORS headers for a response."""
    if not CORS_ENABLED:
        return {}

    # Check if origin is allowed
    allowed = False
    if "*" in CORS_ALLOWED_ORIGINS:
        allowed = True
    elif origin and origin in CORS_ALLOWED_ORIGINS:
        allowed = True

    if not allowed:
        return {}

    return {
        "Access-Control-Allow-Origin": origin or "*",
        "Access-Control-Allow-Methods": ", ".join(CORS_ALLOWED_METHODS),
        "Access-Control-Allow-Headers": ", ".join(CORS_ALLOWED_HEADERS),
        "Access-Control-Max-Age": "86400",  # 24 hours
    }
```

---

## 4. Implementation Plan

### Step 1: Authentication (Day 1, morning)
1. Create `auth.py` with bearer token validation
2. Add `AUTH_ENABLED` and `API_KEY` environment variables
3. Integrate into request handling
4. Write `tests/test_auth.py`

### Step 2: Rate Limiting (Day 1, afternoon)
1. Create `rate_limit.py` with token bucket algorithm
2. Add per-tool rate limits
3. Integrate into tool dispatch
4. Write `tests/test_rate_limit.py`

### Step 3: Input Sanitization (Day 2, morning)
1. Create `sanitization.py` with enhanced path validation
2. Replace `_safe_path()` in `filesystem.py`
3. Add content validation to `write_workspace_file`
4. Write `tests/test_sanitization.py`

### Step 4: Audit Logging (Day 2, afternoon)
1. Create `audit.py` with structured audit log
2. Integrate into destructive tools
3. Add `get_audit_log` tool for inspection
4. Write `tests/test_audit.py`

### Step 5: CORS Configuration (Day 3, morning)
1. Create `cors.py` with configurable origins
2. Add CORS headers to responses
3. Write `tests/test_cors.py`

### Step 6: Security Middleware Integration (Day 3, afternoon)
1. Create `security_middleware.py` to tie everything together
2. Update `server.py` to use security middleware
3. Run full test suite
4. Update README with security configuration

---

## 5. Impact Assessment

### 5.1 Backward Compatibility

| Change | Breaking? | Migration |
|--------|-----------|-----------|
| Authentication | Optional | Set `AUTH_ENABLED=false` (default) to disable |
| Rate limiting | Optional | Set `RATE_LIMIT_ENABLED=false` to disable |
| Path sanitization | Partial | Stricter validation may reject previously accepted paths |
| Audit logging | No | Additive, writes to `store/audit.log` |
| CORS | Optional | Set `CORS_ENABLED=false` to disable |

### 5.2 New Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_ENABLED` | `false` | Enable bearer token authentication |
| `API_KEY` | `""` | Plain API key (development only) |
| `API_KEY_HASH` | `""` | SHA-256 hash of API key (production) |
| `RATE_LIMIT_ENABLED` | `true` | Enable rate limiting |
| `DEFAULT_RATE_LIMIT` | `100` | Global rate limit (requests/minute) |
| `DEFAULT_BURST_LIMIT` | `20` | Burst size |
| `CORS_ENABLED` | `true` | Enable CORS headers |
| `CORS_ALLOWED_ORIGINS` | `*` | Comma-separated allowed origins |

### 5.3 New Dependencies

None. All modules use Python standard library only.

---

## 6. Verification Plan

### 6.1 Security Tests

```bash
# Test authentication
curl -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ping","arguments":{}}}'
# Expected: 401 Unauthorized (when AUTH_ENABLED=true)

curl -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <valid-token>' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ping","arguments":{}}}'
# Expected: 200 OK
```

### 6.2 Rate Limit Tests

```bash
# Send 150 requests in 1 minute
for i in {1..150}; do
  curl -s -X POST http://localhost:5000/mcp \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ping","arguments":{}}}'
  sleep 0.4
done
# Expected: 429 Too Many Requests after 100 requests
```

### 6.3 Audit Log Tests

```bash
# Perform a destructive operation
curl -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"delete_workspace_file","arguments":{"path":"test.txt"}}}'

# Check audit log
cat store/audit.log
# Expected: JSON entry with operation, client_id, arguments
```

---

## 7. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Authentication locks out legitimate users | Default is disabled; document setup clearly |
| Rate limiting blocks legitimate bulk operations | Make limits configurable; add bypass for trusted clients |
| Stricter path validation breaks existing workflows | Test with existing paths before enabling |
| Audit log grows unbounded | Add log rotation (future phase) |
| CORS misconfiguration exposes server | Default is permissive; document secure configuration |

---

## 8. Success Criteria

- [ ] Authentication prevents unauthorized access when enabled
- [ ] Rate limiting prevents DoS attacks
- [ ] Path traversal attacks are blocked
- [ ] All destructive operations are audited
- [ ] CORS headers prevent CSRF attacks
- [ ] All existing tests pass
- [ ] New test coverage > 90% for security modules
- [ ] Security documentation is complete

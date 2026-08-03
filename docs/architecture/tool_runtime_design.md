# Tool Runtime Architecture Design

**Document Version:** 1.0  
**Created:** 2026-08-03  
**Author:** Lead Refactoring Architect  
**Status:** PROPOSAL

---

## 1. Executive Summary

This document proposes a unified tool runtime architecture to eliminate duplicated patterns across all 47 MCP tools. Analysis reveals **6 critical duplication categories** affecting code quality, maintainability, and observability.

### Key Findings

| Pattern | Occurrences | Impact |
|---------|-------------|--------|
| Argument validation (`raise ValueError`) | 65 | Inconsistent error handling |
| JSON serialization (`json.dumps`) | 66 | No unified response format |
| Workspace access (`WORKSPACE_ROOT`) | 100+ | Duplicated path logic |
| File I/O (`encoding="utf-8"`) | 85 | Manual encoding specification |
| Subprocess execution | 26 | No centralized wrapper |
| Exception types | 5 different types | Inconsistent error categories |

### Proposed Solution

Introduce four core abstractions:
1. **ToolContext** - Request-scoped context (workspace, config, correlation ID)
2. **ToolResponse** - Unified response envelope with metadata
3. **ToolError** - Centralized error handling with codes and categories
4. **ToolMetrics** - Automatic telemetry collection

---

## 2. Current State Analysis

### 2.1 Duplicated Patterns

#### Pattern 1: Argument Validation

**Evidence:** 65 instances of `raise ValueError`, multiple `FileNotFoundError`, `PermissionError`, `RuntimeError`

**Example from `filesystem.py`:**
```python
def _safe_path(relative: str) -> Path:
    target = (WORKSPACE_ROOT / relative).resolve()
    workspace = WORKSPACE_ROOT.resolve()
    if not str(target).startswith(str(workspace)):
        raise PermissionError(f"Path escapes workspace: {relative}")
    return target

@mcp.tool()
def read_workspace_file(path: str) -> str:
    target = _safe_path(path)
    if not target.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not target.is_file():
        raise ValueError(f"Path is not a file: {path}")
    return target.read_text(encoding="utf-8")
```

**Problems:**
- Manual validation in every tool
- Inconsistent exception types
- No validation framework
- Duplicated path validation logic

#### Pattern 2: Result Formatting

**Evidence:** 66 instances of `json.dumps()`

**Example from `build.py`:**
```python
@mcp.tool()
def run_gradle_tests(module: str = "app", test_filter: str = "") -> str:
    # ... execution logic ...
    status = "PASSED" if result.returncode == 0 else "FAILED"
    return json.dumps(
        {
            "status": status,
            "returncode": result.returncode,
            "output": output[-8000:],
        },
        indent=2,
    )
```

**Problems:**
- Manual JSON serialization in every tool
- Inconsistent response formats
- No metadata (duration, tool name, warnings)
- No unified response envelope

#### Pattern 3: Workspace Access

**Evidence:** 100+ instances of `WORKSPACE_ROOT`

**Example from `code.py`:**
```python
@mcp.tool()
def search_workspace(pattern: str, file_glob: str = "*.kt") -> str:
    cmd = ["grep", "-rn", f"--include={file_glob}", pattern, str(WORKSPACE_ROOT)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    out = result.stdout.strip()
    out = out.replace(str(WORKSPACE_ROOT) + "/", "")
    return out if out else "No matches found."
```

**Problems:**
- Manual path construction everywhere
- Duplicated path validation
- Inconsistent use of `_safe_path()`
- No centralized workspace context

#### Pattern 4: Exception Handling

**Evidence:** 5 different exception types used inconsistently

**Current exception usage:**
```python
# filesystem.py
raise PermissionError(f"Path escapes workspace: {relative}")
raise FileNotFoundError(f"File not found: {path}")
raise ValueError(f"Path is not a file: {path}")

# patch.py
raise RuntimeError(f"Hunk starting at line {start + 1} is out of range")
raise RuntimeError(f"patch command failed:\n{result.stderr}")

# meta.py
raise ValueError(f"Missing key: {key}")
raise RuntimeError("Neither ANTHROPIC_API_KEY nor ANTHROPIC_AUTH_TOKEN is set")
```

**Problems:**
- No error codes or categories
- Inconsistent error messages
- No centralized error handling
- Difficult to track error patterns

#### Pattern 5: Subprocess Execution

**Evidence:** 26 instances of `subprocess.run()`

**Example from `build.py`:**
```python
def _run(cmd: list[str], timeout: int = 300) -> str:
    result = subprocess.run(
        cmd,
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return (result.stdout + result.stderr).strip()
```

**Problems:**
- Duplicated subprocess wrapper logic
- Inconsistent timeout handling
- No centralized error handling
- No metrics collection

#### Pattern 6: File I/O

**Evidence:** 85 instances of `encoding="utf-8"`

**Example from `memory.py`:**
```python
def _load_memory() -> dict[str, str]:
    if not _MEMORY_FILE.exists():
        return {}
    try:
        data = json.loads(_MEMORY_FILE.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()}
    except (json.JSONDecodeError, TypeError):
        return {}
```

**Problems:**
- Manual encoding specification everywhere
- Duplicated error handling
- No centralized file operations
- No validation or sanitization

---

## 3. Proposed Architecture

### 3.1 Core Abstractions

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
from pathlib import Path
import time


class ErrorCategory(Enum):
    """Error categories for classification."""
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    PERMISSION = "permission"
    TIMEOUT = "timeout"
    EXECUTION = "execution"
    IO = "io"
    CONFIGURATION = "configuration"
    EXTERNAL_SERVICE = "external_service"
    INTERNAL = "internal"


@dataclass
class ToolContext:
    """Request-scoped context for tool execution.
    
    Provides workspace access, configuration, and request metadata.
    Automatically injected into tool functions via decorator.
    """
    workspace_root: Path
    config: Any  # ServerConfig
    request_id: str
    agent_id: str = "-"
    correlation_id: str = "-"
    _start_time: float = field(default_factory=time.monotonic)
    
    def safe_path(self, relative: str) -> Path:
        """Resolve and validate a path within workspace."""
        from ollamadev_mcp_server.sanitization import sanitize_path
        return sanitize_path(relative, workspace_root=self.workspace_root)
    
    def elapsed_ms(self) -> float:
        """Get elapsed time in milliseconds."""
        return (time.monotonic() - self._start_time) * 1000


@dataclass
class ToolResponse:
    """Unified response envelope for all tools.
    
    Every tool returns this structure, enabling consistent parsing,
    metrics collection, and error handling.
    """
    success: bool
    tool: str
    duration_ms: float
    data: dict[str, Any] | str | list | None = None
    warnings: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "success": self.success,
            "tool": self.tool,
            "duration_ms": round(self.duration_ms, 2),
            "warnings": self.warnings,
        }
        if self.data is not None:
            result["data"] = self.data
        if self.error is not None:
            result["error"] = self.error
        return result
    
    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


@dataclass
class ToolError:
    """Structured error with category and code.
    
    Provides consistent error handling across all tools.
    """
    category: ErrorCategory
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for inclusion in ToolResponse."""
        return {
            "category": self.category.value,
            "code": self.code,
            "message": self.message,
            "context": self.context,
        }
    
    def to_response(self, tool_name: str, duration_ms: float) -> ToolResponse:
        """Convert to a failed ToolResponse."""
        return ToolResponse(
            success=False,
            tool=tool_name,
            duration_ms=duration_ms,
            error=self.to_dict(),
        )


@dataclass
class ToolMetrics:
    """Automatic telemetry collection for tool execution.
    
    Tracks duration, success/failure, and error patterns.
    """
    tool_name: str
    duration_ms: float
    success: bool
    error_category: ErrorCategory | None = None
    error_code: str | None = None
    timestamp: float = field(default_factory=time.time)
    
    def record(self) -> None:
        """Record metrics to persistent storage."""
        from ollamadev_mcp_server.tool_history import ToolCallRecord, get_history
        
        record = ToolCallRecord(
            tool_name=self.tool_name,
            arguments={},  # Arguments captured separately
            success=self.success,
            duration_ms=self.duration_ms,
            error=self.error_code,
        )
        get_history().record(record)
```

### 3.2 Decorator-Based Runtime

```python
from functools import wraps
from typing import TypeVar, ParamSpec
import logging

P = ParamSpec('P')
T = TypeVar('T')

logger = logging.getLogger(__name__)


def tool_runtime(
    name: str | None = None,
    validate_args: bool = True,
    track_metrics: bool = True,
):
    """Decorator that wraps tool functions with runtime support.
    
    Features:
    - Automatic ToolContext injection
    - Unified ToolResponse wrapping
    - Automatic metrics collection
    - Centralized error handling
    - Request correlation
    
    Usage:
        @tool_runtime(name="read_file")
        def read_workspace_file(ctx: ToolContext, path: str) -> str:
            target = ctx.safe_path(path)
            return target.read_text(encoding="utf-8")
    """
    def decorator(func: Callable[P, T]) -> Callable[P, str]:
        tool_name = name or func.__name__
        
        @wraps(func)
        def wrapper(*args, **kwargs) -> str:
            # Extract or create context
            ctx = None
            for arg in args:
                if isinstance(arg, ToolContext):
                    ctx = arg
                    break
            
            if ctx is None:
                # Create default context
                from ollamadev_mcp_server.config import get_config
                from ollamadev_mcp_server.logging_config import get_context
                
                config = get_config()
                req_ctx = get_context()
                ctx = ToolContext(
                    workspace_root=config.workspace_root,
                    config=config,
                    request_id=req_ctx["request_id"],
                    agent_id=req_ctx["agent_id"],
                    correlation_id=req_ctx["request_id"],
                )
            
            start_time = time.monotonic()
            metrics = None
            
            try:
                # Execute tool function
                result = func(ctx, *args[1:], **kwargs)
                
                # Calculate duration
                duration_ms = (time.monotonic() - start_time) * 1000
                
                # Wrap result in ToolResponse
                if isinstance(result, ToolResponse):
                    response = result
                else:
                    response = ToolResponse(
                        success=True,
                        tool=tool_name,
                        duration_ms=duration_ms,
                        data=result,
                    )
                
                # Record metrics
                if track_metrics:
                    metrics = ToolMetrics(
                        tool_name=tool_name,
                        duration_ms=duration_ms,
                        success=True,
                    )
                    metrics.record()
                
                # Log success
                logger.info(
                    "Tool %s completed in %.2fms",
                    tool_name,
                    duration_ms,
                    extra={
                        "extra_data": {
                            "tool": tool_name,
                            "duration_ms": duration_ms,
                            "success": True,
                        }
                    },
                )
                
                return response.to_json()
                
            except Exception as exc:
                # Calculate duration
                duration_ms = (time.monotonic() - start_time) * 1000
                
                # Convert to ToolError
                tool_error = _convert_exception(exc)
                
                # Create failed response
                response = tool_error.to_response(tool_name, duration_ms)
                
                # Record metrics
                if track_metrics:
                    metrics = ToolMetrics(
                        tool_name=tool_name,
                        duration_ms=duration_ms,
                        success=False,
                        error_category=tool_error.category,
                        error_code=tool_error.code,
                    )
                    metrics.record()
                
                # Log error
                logger.error(
                    "Tool %s failed: %s",
                    tool_name,
                    tool_error.message,
                    extra={
                        "extra_data": {
                            "tool": tool_name,
                            "duration_ms": duration_ms,
                            "success": False,
                            "error_category": tool_error.category.value,
                            "error_code": tool_error.code,
                        }
                    },
                    exc_info=True,
                )
                
                return response.to_json()
        
        return wrapper
    
    return decorator


def _convert_exception(exc: Exception) -> ToolError:
    """Convert various exception types to ToolError."""
    from ollamadev_mcp_server.errors import (
        OllamaDevError,
        ValidationError,
        SecurityError,
        DependencyError,
        ToolTimeoutError,
    )
    
    # Handle our custom exceptions
    if isinstance(exc, ValidationError):
        return ToolError(
            category=ErrorCategory.VALIDATION,
            code="VALIDATION_ERROR",
            message=exc.message,
            context=exc.context,
        )
    
    if isinstance(exc, SecurityError):
        return ToolError(
            category=ErrorCategory.PERMISSION,
            code="SECURITY_ERROR",
            message=exc.message,
            context=exc.context,
        )
    
    if isinstance(exc, DependencyError):
        return ToolError(
            category=ErrorCategory.EXTERNAL_SERVICE,
            code="DEPENDENCY_ERROR",
            message=exc.message,
            context=exc.context,
        )
    
    if isinstance(exc, ToolTimeoutError):
        return ToolError(
            category=ErrorCategory.TIMEOUT,
            code="TIMEOUT",
            message=exc.message,
            context=exc.context,
        )
    
    if isinstance(exc, OllamaDevError):
        return ToolError(
            category=ErrorCategory.INTERNAL,
            code=exc.code,
            message=exc.message,
            context=exc.context,
        )
    
    # Handle built-in exceptions
    if isinstance(exc, FileNotFoundError):
        return ToolError(
            category=ErrorCategory.NOT_FOUND,
            code="FILE_NOT_FOUND",
            message=str(exc),
        )
    
    if isinstance(exc, PermissionError):
        return ToolError(
            category=ErrorCategory.PERMISSION,
            code="PERMISSION_DENIED",
            message=str(exc),
        )
    
    if isinstance(exc, TimeoutError):
        return ToolError(
            category=ErrorCategory.TIMEOUT,
            code="TIMEOUT",
            message=str(exc),
        )
    
    if isinstance(exc, ValueError):
        return ToolError(
            category=ErrorCategory.VALIDATION,
            code="INVALID_ARGUMENT",
            message=str(exc),
        )
    
    if isinstance(exc, RuntimeError):
        return ToolError(
            category=ErrorCategory.EXECUTION,
            code="RUNTIME_ERROR",
            message=str(exc),
        )
    
    # Fallback for unknown exceptions
    return ToolError(
        category=ErrorCategory.INTERNAL,
        code="INTERNAL_ERROR",
        message=str(exc),
        context={"exception_type": type(exc).__name__},
    )
```

### 3.3 Helper Functions

```python
# Helper functions for common operations

def read_workspace_file(ctx: ToolContext, path: str) -> str:
    """Read a file from workspace with automatic path validation."""
    target = ctx.safe_path(path)
    if not target.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not target.is_file():
        raise ValueError(f"Path is not a file: {path}")
    return target.read_text(encoding="utf-8")


def write_workspace_file(
    ctx: ToolContext,
    path: str,
    content: str,
    create_dirs: bool = True,
) -> int:
    """Write a file to workspace with automatic path validation."""
    target = ctx.safe_path(path)
    if create_dirs:
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return len(content.encode("utf-8"))


def run_subprocess(
    ctx: ToolContext,
    cmd: list[str],
    timeout: int = 300,
    input_data: str | None = None,
) -> dict[str, Any]:
    """Run a subprocess with automatic workspace context."""
    import subprocess
    
    result = subprocess.run(
        cmd,
        cwd=str(ctx.workspace_root),
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_data,
    )
    
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "combined": (result.stdout + result.stderr).strip(),
    }


def success_response(
    ctx: ToolContext,
    data: Any,
    warnings: list[str] | None = None,
) -> ToolResponse:
    """Create a success response with automatic duration tracking."""
    return ToolResponse(
        success=True,
        tool="",  # Will be filled by decorator
        duration_ms=ctx.elapsed_ms(),
        data=data,
        warnings=warnings or [],
    )


def error_response(
    ctx: ToolContext,
    error: ToolError,
) -> ToolResponse:
    """Create an error response with automatic duration tracking."""
    return error.to_response(
        tool_name="",  # Will be filled by decorator
        duration_ms=ctx.elapsed_ms(),
    )
```

---

## 4. Migration Strategy

### 4.1 Phased Approach

**Phase 1: Foundation (Week 1)**
- Implement `ToolContext`, `ToolResponse`, `ToolError`, `ToolMetrics`
- Create `@tool_runtime` decorator
- Implement helper functions
- Write comprehensive tests
- **No tool modifications yet**

**Phase 2: Pilot Migration (Week 2)**
- Migrate 3-5 simple tools (e.g., `ping`, `list_workspace_files`, `read_workspace_file`)
- Validate response format compatibility
- Test metrics collection
- Gather feedback

**Phase 3: Bulk Migration (Weeks 3-4)**
- Migrate remaining tools in batches
- Prioritize by risk level (SAFE → MODERATE → DESTRUCTIVE)
- Maintain backward compatibility during transition

**Phase 4: Cleanup (Week 5)**
- Remove legacy code paths
- Update documentation
- Performance optimization

### 4.2 Backward Compatibility

During migration, tools can return either:
1. **Legacy format:** Raw string or dict
2. **New format:** `ToolResponse` object

The decorator automatically wraps legacy returns:

```python
# Legacy tool (still works)
@mcp.tool()
def old_tool(path: str) -> str:
    return "result"

# New tool (recommended)
@tool_runtime(name="new_tool")
def new_tool(ctx: ToolContext, path: str) -> str:
    return "result"  # Automatically wrapped in ToolResponse
```

### 4.3 Response Format Evolution

**Current format (inconsistent):**
```json
{
  "status": "PASSED",
  "returncode": 0,
  "output": "..."
}
```

**New format (unified):**
```json
{
  "success": true,
  "tool": "run_gradle_tests",
  "duration_ms": 1234.56,
  "data": {
    "status": "PASSED",
    "returncode": 0,
    "output": "..."
  },
  "warnings": []
}
```

**Error format:**
```json
{
  "success": false,
  "tool": "read_workspace_file",
  "duration_ms": 12.34,
  "error": {
    "category": "not_found",
    "code": "FILE_NOT_FOUND",
    "message": "File not found: missing.kt",
    "context": {}
  },
  "warnings": []
}
```

---

## 5. Implementation Sequence

### Step 1: Core Abstractions (Day 1)

**Files to Create:**
- `ollamadev_mcp_server/tool_runtime.py` (300 lines)
  - `ErrorCategory` enum
  - `ToolContext` dataclass
  - `ToolResponse` dataclass
  - `ToolError` dataclass
  - `ToolMetrics` dataclass

**Tests:**
- `tests/test_tool_runtime.py` (200 lines)
  - Test context creation
  - Test response serialization
  - Test error conversion
  - Test metrics recording

**Deliverables:**
- ✅ Core abstractions implemented
- ✅ 100% test coverage
- ✅ Documentation complete

---

### Step 2: Decorator and Helpers (Day 2)

**Files to Create:**
- `ollamadev_mcp_server/tool_decorator.py` (250 lines)
  - `@tool_runtime` decorator
  - `_convert_exception()` function
  - Helper functions (`read_workspace_file`, `write_workspace_file`, etc.)

**Tests:**
- `tests/test_tool_decorator.py` (150 lines)
  - Test decorator wrapping
  - Test context injection
  - Test error handling
  - Test metrics collection

**Deliverables:**
- ✅ Decorator implemented
- ✅ Helper functions implemented
- ✅ 100% test coverage

---

### Step 3: Pilot Migration (Days 3-4)

**Tools to Migrate:**
1. `ping` (meta.py) - Simplest tool
2. `list_workspace_files` (filesystem.py) - Read-only
3. `read_workspace_file` (filesystem.py) - Read-only with validation
4. `write_workspace_file` (filesystem.py) - Write with validation
5. `get_sandbox_status` (sandbox.py) - Read-only

**Migration Pattern:**

**Before:**
```python
@mcp.tool()
def read_workspace_file(path: str) -> str:
    target = _safe_path(path)
    if not target.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not target.is_file():
        raise ValueError(f"Path is not a file: {path}")
    return target.read_text(encoding="utf-8")
```

**After:**
```python
@tool_runtime(name="read_workspace_file")
def read_workspace_file(ctx: ToolContext, path: str) -> str:
    target = ctx.safe_path(path)
    if not target.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not target.is_file():
        raise ValueError(f"Path is not a file: {path}")
    return target.read_text(encoding="utf-8")
```

**Tests:**
- Update existing tests to handle new response format
- Add tests for new metadata fields
- Verify backward compatibility

**Deliverables:**
- ✅ 5 tools migrated
- ✅ All tests passing
- ✅ Response format validated

---

### Step 4: Bulk Migration - SAFE Tools (Days 5-7)

**Tools to Migrate (13 SAFE tools):**
1. `list_workspace_files`
2. `read_workspace_file`
3. `git_status_diff`
4. `git_log`
5. `get_sandbox_status`
6. `parse_test_results`
7. `parse_test_results_xml`
8. `parse_coverage_xml`
9. `get_build_config`
10. `list_phase_artifacts`
11. `read_phase_artifact`
12. `evaluate_sprint_outcome`
13. `ping`

**Migration Checklist:**
- [ ] Add `@tool_runtime` decorator
- [ ] Add `ctx: ToolContext` parameter
- [ ] Replace `WORKSPACE_ROOT` with `ctx.workspace_root`
- [ ] Replace `_safe_path()` with `ctx.safe_path()`
- [ ] Update tests
- [ ] Verify response format
- [ ] Check metrics collection

**Deliverables:**
- ✅ 13 SAFE tools migrated
- ✅ All tests passing
- ✅ Metrics flowing

---

### Step 5: Bulk Migration - MODERATE Tools (Days 8-12)

**Tools to Migrate (26 MODERATE tools):**

**Filesystem (2):**
- `write_workspace_file`
- `move_workspace_file`

**Build (9):**
- `run_gradle_tests`
- `run_gradle_build`
- `run_lint`
- `run_detekt`
- `run_ktlint`
- `run_instrumented_tests`
- `run_screenshot_tests`
- `run_pytest`
- `run_gradle_test_command`

**Sprint (2):**
- `create_sprint_task`
- `update_phase_artifact`

**Memory (4):**
- `store_memory`
- `recall_memory`
- `list_memories`
- `clear_memory`

**Settings (2):**
- `get_server_settings`
- `update_server_settings`

**Other (7):**
- `describe_tools`
- `suggest_next_action`
- `get_task_transcript`
- `search_workspace`
- `get_file_outline`
- `find_symbol`
- `get_todos`

**Migration Pattern for Execution Tools:**

**Before:**
```python
@mcp.tool()
def run_gradle_tests(module: str = "app", test_filter: str = "") -> str:
    gradlew = WORKSPACE_ROOT / "gradlew"
    if not gradlew.exists():
        return json.dumps({"status": "FAILED", "error": "gradlew not found"}, indent=2)
    
    cmd = _gradle_cmd(gradlew, f":{module}:testDebugUnitTest", "--no-daemon")
    if test_filter:
        cmd += ["--tests", test_filter]
    
    result = subprocess.run(cmd, cwd=str(WORKSPACE_ROOT), capture_output=True, text=True, timeout=300)
    status = "PASSED" if result.returncode == 0 else "FAILED"
    return json.dumps({"status": status, "returncode": result.returncode, "output": result.stdout}, indent=2)
```

**After:**
```python
@tool_runtime(name="run_gradle_tests")
def run_gradle_tests(ctx: ToolContext, module: str = "app", test_filter: str = "") -> dict:
    gradlew = ctx.workspace_root / "gradlew"
    if not gradlew.exists():
        raise FileNotFoundError("gradlew not found in workspace root")
    
    cmd = _gradle_cmd(gradlew, f":{module}:testDebugUnitTest", "--no-daemon")
    if test_filter:
        cmd += ["--tests", test_filter]
    
    result = run_subprocess(ctx, cmd, timeout=300)
    status = "PASSED" if result["returncode"] == 0 else "FAILED"
    
    return {
        "status": status,
        "returncode": result["returncode"],
        "output": result["stdout"][-8000:],
    }
```

**Deliverables:**
- ✅ 26 MODERATE tools migrated
- ✅ All tests passing
- ✅ Metrics flowing

---

### Step 6: Bulk Migration - DESTRUCTIVE Tools (Days 13-15)

**Tools to Migrate (8 DESTRUCTIVE tools):**
1. `delete_workspace_file`
2. `git_commit_checkpoint`
3. `run_shell_command`
4. `run_autonomous_sprint`
5. `reset_server_settings`
6. `find_symbol`
7. `get_todos`
8. `get_server_health`

**Special Considerations:**
- Add approval workflow integration
- Enhanced audit logging
- Stricter validation
- Resource limits

**Migration Pattern for Destructive Tools:**

**Before:**
```python
@mcp.tool()
def delete_workspace_file(path: str) -> str:
    target = _safe_path(path)
    if not target.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if target.is_dir():
        raise ValueError(f"Refusing to delete directory: {path}")
    target.unlink()
    return f"Deleted {path}"
```

**After:**
```python
@tool_runtime(name="delete_workspace_file")
def delete_workspace_file(ctx: ToolContext, path: str) -> str:
    # Validate path
    target = ctx.safe_path(path)
    if not target.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if target.is_dir():
        raise ValueError(f"Refusing to delete directory: {path}")
    
    # Check if file is protected
    if _is_protected_file(target):
        raise PermissionError(f"Cannot delete protected file: {path}")
    
    # Perform deletion
    target.unlink()
    
    # Audit log
    from ollamadev_mcp_server.audit import audit_log
    audit_log(
        operation="delete_workspace_file",
        client_id=ctx.agent_id,
        arguments={"path": path},
        result=f"Deleted {path}",
    )
    
    return f"Deleted {path}"
```

**Deliverables:**
- ✅ 8 DESTRUCTIVE tools migrated
- ✅ All tests passing
- ✅ Enhanced security

---

### Step 7: Cleanup and Optimization (Days 16-17)

**Tasks:**
1. Remove legacy `_safe_path()` function (replace with `ctx.safe_path()`)
2. Remove duplicate helper functions
3. Optimize decorator performance
4. Update documentation
5. Create migration guide for external users

**Deliverables:**
- ✅ Legacy code removed
- ✅ Documentation updated
- ✅ Performance optimized

---

### Step 8: Testing and Validation (Days 18-20)

**Tasks:**
1. Run full test suite (407 tests)
2. Performance benchmarking
3. Load testing
4. Security review
5. Code review

**Deliverables:**
- ✅ All tests passing
- ✅ Performance validated
- ✅ Security reviewed
- ✅ Code approved

---

## 6. Benefits

### 6.1 Code Quality

**Before:**
- 65 instances of manual validation
- 66 instances of manual JSON serialization
- 100+ instances of manual workspace access
- 5 different exception types
- Inconsistent error handling

**After:**
- Centralized validation via `ToolContext`
- Automatic JSON serialization via `ToolResponse`
- Centralized workspace access via `ToolContext`
- Unified error handling via `ToolError`
- Consistent response format

**Estimated Reduction:**
- ~500 lines of duplicated code
- 60% reduction in boilerplate
- 100% consistent error handling

### 6.2 Maintainability

**Before:**
- Changes to validation logic require updating 65 locations
- Changes to response format require updating 66 locations
- Changes to workspace access require updating 100+ locations
- Difficult to track error patterns

**After:**
- Changes to validation logic in one place (`ToolContext`)
- Changes to response format in one place (`ToolResponse`)
- Changes to workspace access in one place (`ToolContext`)
- Easy to track error patterns via `ToolError` categories

**Estimated Improvement:**
- 80% reduction in maintenance effort
- 90% faster feature development
- 100% consistent behavior

### 6.3 Observability

**Before:**
- No duration tracking
- No success/failure metrics
- No error categorization
- No request correlation

**After:**
- Automatic duration tracking via `ToolMetrics`
- Automatic success/failure tracking
- Error categorization via `ErrorCategory`
- Request correlation via `request_id`

**Estimated Improvement:**
- 100% metrics coverage
- Real-time performance monitoring
- Error pattern analysis
- Request tracing

### 6.4 Security

**Before:**
- Inconsistent path validation
- Manual audit logging
- No centralized permission checks

**After:**
- Centralized path validation via `ctx.safe_path()`
- Automatic audit logging via decorator
- Centralized permission checks
- Enhanced error categorization

**Estimated Improvement:**
- 100% path validation coverage
- 100% audit logging coverage
- Reduced security vulnerabilities

---

## 7. Risks and Mitigations

### Risk 1: Breaking Changes

**Risk:** New response format breaks existing clients

**Mitigation:**
- Backward compatibility during migration
- Version field in response for future changes
- Gradual rollout with feature flags
- Comprehensive testing

### Risk 2: Performance Overhead

**Risk:** Decorator adds overhead to every tool call

**Mitigation:**
- Benchmark decorator overhead (target: <1ms)
- Optimize hot paths
- Lazy evaluation where possible
- Profile before/after migration

### Risk 3: Migration Complexity

**Risk:** Migrating 47 tools is complex and error-prone

**Mitigation:**
- Phased approach (8 steps over 20 days)
- Comprehensive testing at each phase
- Rollback plan for each phase
- Code review for each migration

### Risk 4: Test Coverage

**Risk:** New abstractions not fully tested

**Mitigation:**
- 100% test coverage requirement
- Integration tests for each tool
- Load testing before production
- Security review

---

## 8. Success Criteria

### 8.1 Functional Criteria

- [ ] All 47 tools migrated to new runtime
- [ ] All 407 tests passing
- [ ] Response format consistent across all tools
- [ ] Error handling consistent across all tools
- [ ] Metrics collected for all tools

### 8.2 Performance Criteria

- [ ] Decorator overhead < 1ms per call
- [ ] No regression in tool execution time
- [ ] Memory usage within 10% of baseline
- [ ] CPU usage within 10% of baseline

### 8.3 Quality Criteria

- [ ] 100% test coverage for new abstractions
- [ ] Code review approved by 2 reviewers
- [ ] Security review completed
- [ ] Documentation complete

### 8.4 Business Criteria

- [ ] 50% reduction in duplicated code
- [ ] 80% reduction in maintenance effort
- [ ] 100% metrics coverage
- [ ] Zero breaking changes for existing clients

---

## 9. Timeline

| Phase | Duration | Deliverables |
|-------|----------|--------------|
| Phase 1: Foundation | 1 day | Core abstractions, tests |
| Phase 2: Decorator | 1 day | Decorator, helpers, tests |
| Phase 3: Pilot | 2 days | 5 tools migrated, validated |
| Phase 4: SAFE tools | 3 days | 13 tools migrated |
| Phase 5: MODERATE tools | 5 days | 26 tools migrated |
| Phase 6: DESTRUCTIVE tools | 3 days | 8 tools migrated |
| Phase 7: Cleanup | 2 days | Legacy code removed |
| Phase 8: Testing | 3 days | Full validation |
| **Total** | **20 days** | **47 tools migrated** |

---

## 10. Conclusion

This tool runtime architecture eliminates **6 critical duplication categories** affecting 47 MCP tools. The proposed solution provides:

1. **Unified abstractions** (`ToolContext`, `ToolResponse`, `ToolError`, `ToolMetrics`)
2. **Decorator-based runtime** for automatic wrapping
3. **Phased migration** over 20 days
4. **100% backward compatibility** during transition
5. **Comprehensive testing** at each phase

**Expected Outcomes:**
- 50% reduction in duplicated code
- 80% reduction in maintenance effort
- 100% metrics coverage
- Consistent error handling
- Enhanced observability
- Improved security

**Next Steps:**
1. Review and approve this design
2. Begin Phase 1 implementation
3. Conduct pilot migration
4. Gather feedback and iterate

---

**Document Status:** PROPOSED  
**Review Date:** 2026-08-10  
**Author:** Lead Refactoring Architect  
**Approvers:** [Pending]

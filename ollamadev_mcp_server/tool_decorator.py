"""Tool runtime decorator and helper functions.

Provides the @tool_runtime decorator that automatically wraps tool functions
with runtime support including context injection, response wrapping, metrics
collection, and error handling.

Usage:
    from ollamadev_mcp_server.tool_decorator import tool_runtime
    
    @tool_runtime(name="read_file")
    def read_workspace_file(ctx: ToolContext, path: str) -> str:
        target = ctx.safe_path(path)
        return target.read_text(encoding="utf-8")
"""

import subprocess
import asyncio
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar

from ollamadev_mcp_server.logging_config import get_logger
from ollamadev_mcp_server.tool_runtime import (
    ErrorCategory,
    ToolContext,
    ToolError,
    ToolMetrics,
    ToolResponse,
)

logger = get_logger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


# ---------------------------------------------------------------------------
# Exception Conversion
# ---------------------------------------------------------------------------


def _convert_exception(exc: Exception) -> ToolError:
    """Convert various exception types to ToolError.

    Maps built-in and custom exceptions to standardized ToolError
    with appropriate category and code.

    Args:
        exc: Exception to convert

    Returns:
        ToolError with category and code
    """
    from ollamadev_mcp_server.errors import (
        DependencyError,
        OllamaDevError,
        SecurityError,
        ToolTimeoutError,
        ValidationError,
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


# ---------------------------------------------------------------------------
# Tool Runtime Decorator
# ---------------------------------------------------------------------------


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

    Args:
        name: Tool name (defaults to function name)
        validate_args: Whether to validate arguments (reserved for future)
        track_metrics: Whether to collect metrics

    Returns:
        Decorated function that returns JSON string

    Usage:
        @tool_runtime(name="read_file")
        def read_workspace_file(ctx: ToolContext, path: str) -> str:
            target = ctx.safe_path(path)
            return target.read_text(encoding="utf-8")
    """

    def decorator(func: Callable[P, T]) -> Callable[P, str]:
        tool_name = name or func.__name__

        # Check if function is async
        is_async = asyncio.iscoroutinefunction(func)

        if is_async:
            @wraps(func)
            async def async_wrapper(*args, **kwargs) -> str:
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
                    # Inject ctx if not already provided in args or kwargs
                    has_ctx_in_args = any(isinstance(arg, ToolContext) for arg in args)
                    if not has_ctx_in_args and "ctx" not in kwargs:
                        kwargs["ctx"] = ctx
                    result = await func(*args, **kwargs)

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

            return async_wrapper
        else:
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
                    # Inject ctx if not already provided in args or kwargs
                    has_ctx_in_args = any(isinstance(arg, ToolContext) for arg in args)
                    if not has_ctx_in_args and "ctx" not in kwargs:
                        kwargs["ctx"] = ctx
                    result = func(*args, **kwargs)

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

def read_workspace_file(ctx: ToolContext, path: str) -> str:
    """Read a file from workspace with automatic path validation.

    Args:
        ctx: Tool context with workspace root
        path: Relative path to file

    Returns:
        File content as string

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If path is not a file
    """
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
    """Write a file to workspace with automatic path validation.

    Args:
        ctx: Tool context with workspace root
        path: Relative path to file
        content: Content to write
        create_dirs: Whether to create parent directories

    Returns:
        Number of bytes written
    """
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
    """Run a subprocess with automatic workspace context.

    Args:
        ctx: Tool context with workspace root
        cmd: Command and arguments
        timeout: Timeout in seconds
        input_data: Optional input to pass to subprocess

    Returns:
        Dictionary with returncode, stdout, stderr, and combined output
    """
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
    """Create a success response with automatic duration tracking.

    Args:
        ctx: Tool context for duration tracking
        data: Response data
        warnings: Optional warning messages

    Returns:
        ToolResponse with success=True
    """
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
    """Create an error response with automatic duration tracking.

    Args:
        ctx: Tool context for duration tracking
        error: ToolError to include

    Returns:
        ToolResponse with success=False
    """
    return error.to_response(
        tool_name="",  # Will be filled by decorator
        duration_ms=ctx.elapsed_ms(),
    )

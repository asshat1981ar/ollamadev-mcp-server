"""Centralized error handling for the OllamaDev MCP server.

Defines a hierarchy of typed exceptions and a central error handler
that formats errors as JSON responses.  All tool modules should raise
``OllamaDevError`` subclasses so the server can return consistent,
machine-readable error messages.

Usage::

    from ollamadev_mcp_server.errors import ValidationError

    raise ValidationError("Path cannot be empty", field="path")
"""

import json
from typing import Any

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class OllamaDevError(Exception):
    """Base exception for all OllamaDev errors.

    Attributes:
        message: Human-readable error description.
        code: Machine-readable error code (e.g. ``VALIDATION_ERROR``).
        status_code: Suggested HTTP status code.
        context: Arbitrary extra data for debugging.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "UNKNOWN",
        status_code: int = 500,
        context: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.context = context or {}


class ValidationError(OllamaDevError):
    """Raised when tool input validation fails."""

    def __init__(self, message: str, **context: Any):
        super().__init__(
            message,
            code="VALIDATION_ERROR",
            status_code=400,
            context=context,
        )


class SecurityError(OllamaDevError):
    """Raised when a security check fails (path traversal, auth, etc.)."""

    def __init__(self, message: str, **context: Any):
        super().__init__(
            message,
            code="SECURITY_ERROR",
            status_code=403,
            context=context,
        )


class DependencyError(OllamaDevError):
    """Raised when an external dependency is unavailable."""

    def __init__(self, message: str, **context: Any):
        super().__init__(
            message,
            code="DEPENDENCY_ERROR",
            status_code=503,
            context=context,
        )


class ToolTimeoutError(OllamaDevError):
    """Raised when a tool operation exceeds its timeout."""

    def __init__(self, message: str, **context: Any):
        super().__init__(
            message,
            code="TIMEOUT",
            status_code=504,
            context=context,
        )


# ---------------------------------------------------------------------------
# Error formatting
# ---------------------------------------------------------------------------


def format_error_response(error: OllamaDevError) -> str:
    """Format an ``OllamaDevError`` as a JSON string."""
    return json.dumps(
        {
            "error": {
                "code": error.code,
                "message": error.message,
                "context": error.context,
            }
        },
        indent=2,
    )


def handle_tool_error(exc: Exception, tool_name: str) -> str:
    """Central error handler for tool exceptions.

    Logs the error with context and returns a JSON error string suitable
    for returning to the MCP client.
    """
    if isinstance(exc, OllamaDevError):
        logger.warning(
            "Tool error [%s]: %s — %s",
            exc.code,
            tool_name,
            exc.message,
            extra={"extra_data": {"code": exc.code, "context": exc.context}},
        )
        return format_error_response(exc)

    # Unexpected errors — log with full traceback
    logger.exception("Unexpected error in tool %s", tool_name)
    return json.dumps(
        {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An internal error occurred. Check server logs for details.",
            }
        },
        indent=2,
    )

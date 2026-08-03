"""Unified tool runtime for OllamaDev MCP server.

Provides core abstractions to eliminate duplicated patterns across all tools:
- ToolContext: Request-scoped context with workspace access and validation
- ToolResponse: Unified response envelope with metadata
- ToolError: Centralized error handling with categories and codes
- ToolMetrics: Automatic telemetry collection

Usage:
    from ollamadev_mcp_server.tool_runtime import tool_runtime, ToolContext
    
    @tool_runtime(name="read_file")
    def read_workspace_file(ctx: ToolContext, path: str) -> str:
        target = ctx.safe_path(path)
        return target.read_text(encoding="utf-8")
"""

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Error Categories
# ---------------------------------------------------------------------------


class ErrorCategory(Enum):
    """Error categories for classification and programmatic handling."""

    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    PERMISSION = "permission"
    TIMEOUT = "timeout"
    EXECUTION = "execution"
    IO = "io"
    CONFIGURATION = "configuration"
    EXTERNAL_SERVICE = "external_service"
    INTERNAL = "internal"


# ---------------------------------------------------------------------------
# Tool Context
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    """Request-scoped context for tool execution.

    Provides workspace access, configuration, and request metadata.
    Automatically injected into tool functions via @tool_runtime decorator.

    Attributes:
        workspace_root: Root directory for workspace operations
        config: Server configuration
        request_id: Unique request identifier for correlation
        agent_id: Identifier for the calling agent
        correlation_id: Correlation ID for request tracing
    """

    workspace_root: Path
    config: Any  # ServerConfig
    request_id: str
    agent_id: str = "-"
    correlation_id: str = "-"
    _start_time: float = field(default_factory=time.monotonic)

    def safe_path(self, relative: str) -> Path:
        """Resolve and validate a path within workspace.

        Args:
            relative: Relative path to resolve

        Returns:
            Resolved Path object

        Raises:
            SecurityError: If path escapes workspace
        """
        from ollamadev_mcp_server.sanitization import sanitize_path

        return sanitize_path(relative, workspace_root=self.workspace_root)

    def elapsed_ms(self) -> float:
        """Get elapsed time in milliseconds since context creation.

        Returns:
            Elapsed time in milliseconds
        """
        return (time.monotonic() - self._start_time) * 1000


# ---------------------------------------------------------------------------
# Tool Response
# ---------------------------------------------------------------------------


@dataclass
class ToolResponse:
    """Unified response envelope for all tools.

    Every tool returns this structure, enabling consistent parsing,
    metrics collection, and error handling.

    Attributes:
        success: Whether the operation succeeded
        tool: Name of the tool that was executed
        duration_ms: Execution duration in milliseconds
        data: Operation result data (on success)
        warnings: List of warning messages
        error: Error details (on failure)
    """

    success: bool
    tool: str
    duration_ms: float
    data: dict[str, Any] | str | list | None = None
    warnings: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary representation of the response
        """
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
        """Serialize to JSON string.

        Args:
            indent: JSON indentation level

        Returns:
            JSON string representation
        """
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool Error
# ---------------------------------------------------------------------------


@dataclass
class ToolError:
    """Structured error with category and code.

    Provides consistent error handling across all tools with
    programmatic error classification.

    Attributes:
        category: Error category for classification
        code: Machine-readable error code
        message: Human-readable error message
        context: Additional error context for debugging
    """

    category: ErrorCategory
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for inclusion in ToolResponse.

        Returns:
            Dictionary representation of the error
        """
        return {
            "category": self.category.value,
            "code": self.code,
            "message": self.message,
            "context": self.context,
        }

    def to_response(self, tool_name: str, duration_ms: float) -> ToolResponse:
        """Convert to a failed ToolResponse.

        Args:
            tool_name: Name of the tool that failed
            duration_ms: Execution duration in milliseconds

        Returns:
            ToolResponse with error details
        """
        return ToolResponse(
            success=False,
            tool=tool_name,
            duration_ms=duration_ms,
            error=self.to_dict(),
        )


# ---------------------------------------------------------------------------
# Tool Metrics
# ---------------------------------------------------------------------------


@dataclass
class ToolMetrics:
    """Automatic telemetry collection for tool execution.

    Tracks duration, success/failure, and error patterns for
    observability and performance monitoring.

    Attributes:
        tool_name: Name of the tool
        duration_ms: Execution duration in milliseconds
        success: Whether the operation succeeded
        error_category: Error category (on failure)
        error_code: Error code (on failure)
        timestamp: Unix timestamp of execution
    """

    tool_name: str
    duration_ms: float
    success: bool
    error_category: ErrorCategory | None = None
    error_code: str | None = None
    timestamp: float = field(default_factory=time.time)

    def record(self) -> None:
        """Record metrics to persistent storage.

        Stores metrics in tool call history for analysis and monitoring.
        """
        from ollamadev_mcp_server.tool_history import ToolCallRecord, get_history

        record = ToolCallRecord(
            tool_name=self.tool_name,
            arguments={},  # Arguments captured separately
            success=self.success,
            duration_ms=self.duration_ms,
            error=self.error_code,
        )
        get_history().record(record)

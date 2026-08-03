"""Request middleware for correlation IDs and tool call tracking.

Provides a lightweight ``ToolCallTracker`` that records per-request
metrics (tool calls, durations, success/failure).  The tracker is
bound to the current request via ``bind_request`` from the logging
module.

Usage::

    from ollamadev_mcp_server.middleware import ToolCallTracker

    tracker = ToolCallTracker(request_id="abc123")
    tracker.record_call("search_workspace", duration_ms=42.5, success=True)
    print(tracker.summary())
"""

import time
from typing import Any

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)


class ToolCallTracker:
    """Track tool call metrics for a single request.

    Attributes:
        request_id: The correlation ID for this request.
        start_time: Monotonic timestamp when the tracker was created.
        calls: List of recorded tool call dicts.
    """

    def __init__(self, request_id: str):
        self.request_id = request_id
        self.start_time = time.monotonic()
        self.calls: list[dict[str, Any]] = []

    def record_call(
        self,
        tool_name: str,
        duration_ms: float,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Record a single tool call."""
        self.calls.append({
            "tool_name": tool_name,
            "duration_ms": round(duration_ms, 2),
            "success": success,
            "error": error,
        })

    def summary(self) -> dict[str, Any]:
        """Return a summary of all recorded calls."""
        total_duration = (time.monotonic() - self.start_time) * 1000
        return {
            "request_id": self.request_id,
            "total_duration_ms": round(total_duration, 2),
            "tool_calls": len(self.calls),
            "success_count": sum(1 for c in self.calls if c["success"]),
            "error_count": sum(1 for c in self.calls if not c["success"]),
        }

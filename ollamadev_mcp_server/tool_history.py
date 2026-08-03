"""Persistent tool call history for agent learning and debugging.

Records tool calls with arguments, results, and timing to a JSON file.
Enables analysis of tool usage patterns and debugging of agent behavior.

Usage::

    from ollamadev_mcp_server.tool_history import ToolHistory

    history = ToolHistory()
    history.record("search_workspace", {"pattern": "class.*Test"}, "Found 5 matches", 0.5)
    recent = history.get_recent(10)
"""

import json
import time
from collections import deque
from pathlib import Path
from typing import Any

from ollamadev_mcp_server.constants import STORE_DIR
from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

HISTORY_FILE = STORE_DIR / "tool_call_history.json"
MAX_HISTORY_SIZE = 1000


# ---------------------------------------------------------------------------
# Tool call record
# ---------------------------------------------------------------------------


class ToolCallRecord:
    """A single tool call record.

    Attributes:
        tool_name: Name of the tool that was called.
        arguments: Tool arguments dict.
        success: Whether the call succeeded.
        duration_ms: Call duration in milliseconds.
        error: Error message if call failed, else None.
        cycle_id: Sprint cycle ID if part of a sprint, else None.
        phase: Sprint phase if part of a sprint, else None.
        timestamp: Unix timestamp of the call.
    """

    def __init__(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        success: bool,
        duration_ms: float,
        error: str | None = None,
        cycle_id: int | None = None,
        phase: str | None = None,
    ):
        self.tool_name = tool_name
        self.arguments = arguments
        self.success = success
        self.duration_ms = duration_ms
        self.error = error
        self.cycle_id = cycle_id
        self.phase = phase
        self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "success": self.success,
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error,
            "cycle_id": self.cycle_id,
            "phase": self.phase,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCallRecord":
        """Create from dictionary."""
        record = cls(
            tool_name=data["tool_name"],
            arguments=data.get("arguments", {}),
            success=data["success"],
            duration_ms=data.get("duration_ms", 0),
            error=data.get("error"),
            cycle_id=data.get("cycle_id"),
            phase=data.get("phase"),
        )
        record.timestamp = data.get("timestamp", time.time())
        return record


# ---------------------------------------------------------------------------
# Tool history
# ---------------------------------------------------------------------------


class ToolHistory:
    """Manages tool call history with persistence.

    Stores up to MAX_HISTORY_SIZE records in a deque and persists to disk.
    """

    def __init__(self, max_size: int = MAX_HISTORY_SIZE):
        self._max_size = max_size
        self._records: deque[ToolCallRecord] = deque(maxlen=max_size)
        self._load()

    def record(self, call: ToolCallRecord) -> None:
        """Record a tool call.

        Args:
            call: ToolCallRecord to record.
        """
        self._records.append(call)
        self._save()

    def get_recent(self, n: int = 10) -> list[ToolCallRecord]:
        """Get the N most recent tool calls.

        Args:
            n: Number of records to return.

        Returns:
            List of ToolCallRecord, most recent last.
        """
        return list(self._records)[-n:]

    def get_for_phase(self, cycle_id: int, phase: str) -> list[ToolCallRecord]:
        """Get tool calls for a specific sprint phase.

        Args:
            cycle_id: Sprint cycle ID.
            phase: Sprint phase name.

        Returns:
            List of ToolCallRecord for that phase.
        """
        return [
            r
            for r in self._records
            if r.cycle_id == cycle_id and r.phase == phase
        ]

    def get_failures(self, tool_name: str | None = None, limit: int = 10) -> list[ToolCallRecord]:
        """Get recent failed tool calls.

        Args:
            tool_name: Optional filter by tool name.
            limit: Maximum number of records to return.

        Returns:
            List of failed ToolCallRecord, most recent last.
        """
        failures = [r for r in self._records if not r.success]
        if tool_name:
            failures = [r for r in failures if r.tool_name == tool_name]
        return failures[-limit:]

    def get_tool_stats(self, tool_name: str) -> dict[str, Any]:
        """Get statistics for a specific tool.

        Args:
            tool_name: Name of the tool.

        Returns:
            Dict with call count, success rate, and duration stats.
        """
        calls = [r for r in self._records if r.tool_name == tool_name]
        if not calls:
            return {"tool_name": tool_name, "total_calls": 0}

        successes = [r for r in calls if r.success]
        durations = [r.duration_ms for r in calls]

        return {
            "tool_name": tool_name,
            "total_calls": len(calls),
            "success_count": len(successes),
            "failure_count": len(calls) - len(successes),
            "success_rate": len(successes) / len(calls),
            "avg_duration_ms": sum(durations) / len(durations),
            "min_duration_ms": min(durations),
            "max_duration_ms": max(durations),
        }

    def clear(self) -> None:
        """Clear all history."""
        self._records.clear()
        self._save()

    def _load(self) -> None:
        """Load history from disk."""
        if not HISTORY_FILE.exists():
            return
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            for item in data:
                self._records.append(ToolCallRecord.from_dict(item))
        except (json.JSONDecodeError, OSError, KeyError) as exc:
            logger.warning("Failed to load tool history: %s", exc)

    def _save(self) -> None:
        """Save history to disk."""
        try:
            STORE_DIR.mkdir(parents=True, exist_ok=True)
            data = [r.to_dict() for r in self._records]
            HISTORY_FILE.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to save tool history: %s", exc)


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

_history: ToolHistory | None = None


def get_history() -> ToolHistory:
    """Get the global tool call history instance."""
    global _history
    if _history is None:
        _history = ToolHistory()
    return _history

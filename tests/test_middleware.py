"""Tests for request middleware and tool call tracking."""

import time

from ollamadev_mcp_server.middleware import ToolCallTracker


class TestToolCallTracker:
    def test_initial_state(self):
        tracker = ToolCallTracker(request_id="abc123")
        assert tracker.request_id == "abc123"
        assert tracker.calls == []

    def test_record_success(self):
        tracker = ToolCallTracker(request_id="abc123")
        tracker.record_call("search_workspace", duration_ms=42.5, success=True)
        assert len(tracker.calls) == 1
        assert tracker.calls[0]["tool_name"] == "search_workspace"
        assert tracker.calls[0]["duration_ms"] == 42.5
        assert tracker.calls[0]["success"] is True
        assert tracker.calls[0]["error"] is None

    def test_record_failure(self):
        tracker = ToolCallTracker(request_id="abc123")
        tracker.record_call("bad_tool", duration_ms=100.0, success=False, error="boom")
        assert len(tracker.calls) == 1
        assert tracker.calls[0]["success"] is False
        assert tracker.calls[0]["error"] == "boom"

    def test_summary(self):
        tracker = ToolCallTracker(request_id="abc123")
        tracker.record_call("tool_a", duration_ms=10.0, success=True)
        tracker.record_call("tool_b", duration_ms=20.0, success=True)
        tracker.record_call("tool_c", duration_ms=30.0, success=False, error="fail")
        summary = tracker.summary()
        assert summary["request_id"] == "abc123"
        assert summary["tool_calls"] == 3
        assert summary["success_count"] == 2
        assert summary["error_count"] == 1
        assert summary["total_duration_ms"] > 0

    def test_summary_empty(self):
        tracker = ToolCallTracker(request_id="empty")
        summary = tracker.summary()
        assert summary["tool_calls"] == 0
        assert summary["success_count"] == 0
        assert summary["error_count"] == 0

    def test_duration_rounding(self):
        tracker = ToolCallTracker(request_id="abc")
        tracker.record_call("tool", duration_ms=42.5678, success=True)
        assert tracker.calls[0]["duration_ms"] == 42.57

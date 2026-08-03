"""Tests for persistent tool call history."""

import json
import time
from pathlib import Path

import pytest

from ollamadev_mcp_server.tool_history import (
    HISTORY_FILE,
    MAX_HISTORY_SIZE,
    ToolCallRecord,
    ToolHistory,
    get_history,
)


class TestToolCallRecord:
    def test_creation(self):
        record = ToolCallRecord(
            tool_name="search_workspace",
            arguments={"pattern": "class.*Test"},
            success=True,
            duration_ms=123.45,
        )
        assert record.tool_name == "search_workspace"
        assert record.arguments == {"pattern": "class.*Test"}
        assert record.success is True
        assert record.duration_ms == 123.45
        assert record.error is None
        assert record.cycle_id is None
        assert record.phase is None
        assert record.timestamp > 0

    def test_creation_with_all_fields(self):
        record = ToolCallRecord(
            tool_name="run_tests",
            arguments={"filter": "unit"},
            success=False,
            duration_ms=5000.0,
            error="Connection timeout",
            cycle_id=1,
            phase="VERIFICATION",
        )
        assert record.tool_name == "run_tests"
        assert record.success is False
        assert record.error == "Connection timeout"
        assert record.cycle_id == 1
        assert record.phase == "VERIFICATION"

    def test_to_dict(self):
        record = ToolCallRecord(
            tool_name="ping",
            arguments={},
            success=True,
            duration_ms=10.5,
        )
        data = record.to_dict()
        assert data["tool_name"] == "ping"
        assert data["arguments"] == {}
        assert data["success"] is True
        assert data["duration_ms"] == 10.5
        assert "timestamp" in data

    def test_to_dict_rounds_duration(self):
        record = ToolCallRecord(
            tool_name="test",
            arguments={},
            success=True,
            duration_ms=123.456789,
        )
        data = record.to_dict()
        assert data["duration_ms"] == 123.46

    def test_from_dict(self):
        data = {
            "tool_name": "search_workspace",
            "arguments": {"pattern": "test"},
            "success": True,
            "duration_ms": 100.0,
            "error": None,
            "cycle_id": 1,
            "phase": "DISCOVERY",
            "timestamp": 1234567890.0,
        }
        record = ToolCallRecord.from_dict(data)
        assert record.tool_name == "search_workspace"
        assert record.arguments == {"pattern": "test"}
        assert record.success is True
        assert record.duration_ms == 100.0
        assert record.cycle_id == 1
        assert record.phase == "DISCOVERY"
        assert record.timestamp == 1234567890.0

    def test_from_dict_with_missing_fields(self):
        data = {
            "tool_name": "ping",
            "success": True,
        }
        record = ToolCallRecord.from_dict(data)
        assert record.tool_name == "ping"
        assert record.arguments == {}
        assert record.duration_ms == 0
        assert record.error is None


class TestToolHistory:
    def test_empty_history(self, tmp_path, monkeypatch):
        history_file = tmp_path / "history.json"
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.HISTORY_FILE", history_file)
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.STORE_DIR", tmp_path)
        
        history = ToolHistory()
        assert len(history.get_recent()) == 0

    def test_record_single_call(self, tmp_path, monkeypatch):
        history_file = tmp_path / "history.json"
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.HISTORY_FILE", history_file)
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.STORE_DIR", tmp_path)
        
        history = ToolHistory()
        record = ToolCallRecord(
            tool_name="ping",
            arguments={},
            success=True,
            duration_ms=10.0,
        )
        history.record(record)
        
        recent = history.get_recent()
        assert len(recent) == 1
        assert recent[0].tool_name == "ping"

    def test_record_multiple_calls(self, tmp_path, monkeypatch):
        history_file = tmp_path / "history.json"
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.HISTORY_FILE", history_file)
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.STORE_DIR", tmp_path)
        
        history = ToolHistory()
        for i in range(5):
            record = ToolCallRecord(
                tool_name=f"tool_{i}",
                arguments={},
                success=True,
                duration_ms=10.0,
            )
            history.record(record)
        
        recent = history.get_recent()
        assert len(recent) == 5

    def test_get_recent_limit(self, tmp_path, monkeypatch):
        history_file = tmp_path / "history.json"
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.HISTORY_FILE", history_file)
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.STORE_DIR", tmp_path)
        
        history = ToolHistory()
        for i in range(10):
            record = ToolCallRecord(
                tool_name=f"tool_{i}",
                arguments={},
                success=True,
                duration_ms=10.0,
            )
            history.record(record)
        
        recent = history.get_recent(3)
        assert len(recent) == 3

    def test_get_for_phase(self, tmp_path, monkeypatch):
        history_file = tmp_path / "history.json"
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.HISTORY_FILE", history_file)
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.STORE_DIR", tmp_path)
        
        history = ToolHistory()
        history.record(ToolCallRecord("tool1", {}, True, 10.0, cycle_id=1, phase="DISCOVERY"))
        history.record(ToolCallRecord("tool2", {}, True, 10.0, cycle_id=1, phase="IMPLEMENTATION"))
        history.record(ToolCallRecord("tool3", {}, True, 10.0, cycle_id=2, phase="DISCOVERY"))
        
        phase_records = history.get_for_phase(1, "DISCOVERY")
        assert len(phase_records) == 1
        assert phase_records[0].tool_name == "tool1"

    def test_get_failures(self, tmp_path, monkeypatch):
        history_file = tmp_path / "history.json"
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.HISTORY_FILE", history_file)
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.STORE_DIR", tmp_path)
        
        history = ToolHistory()
        history.record(ToolCallRecord("tool1", {}, True, 10.0))
        history.record(ToolCallRecord("tool2", {}, False, 10.0, error="fail1"))
        history.record(ToolCallRecord("tool3", {}, True, 10.0))
        history.record(ToolCallRecord("tool4", {}, False, 10.0, error="fail2"))
        
        failures = history.get_failures()
        assert len(failures) == 2
        assert failures[0].tool_name == "tool2"
        assert failures[1].tool_name == "tool4"

    def test_get_failures_with_tool_filter(self, tmp_path, monkeypatch):
        history_file = tmp_path / "history.json"
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.HISTORY_FILE", history_file)
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.STORE_DIR", tmp_path)
        
        history = ToolHistory()
        history.record(ToolCallRecord("tool1", {}, False, 10.0, error="fail1"))
        history.record(ToolCallRecord("tool2", {}, False, 10.0, error="fail2"))
        history.record(ToolCallRecord("tool1", {}, False, 10.0, error="fail3"))
        
        failures = history.get_failures(tool_name="tool1")
        assert len(failures) == 2
        assert all(f.tool_name == "tool1" for f in failures)

    def test_get_tool_stats(self, tmp_path, monkeypatch):
        history_file = tmp_path / "history.json"
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.HISTORY_FILE", history_file)
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.STORE_DIR", tmp_path)
        
        history = ToolHistory()
        history.record(ToolCallRecord("tool1", {}, True, 10.0))
        history.record(ToolCallRecord("tool1", {}, True, 20.0))
        history.record(ToolCallRecord("tool1", {}, False, 30.0, error="fail"))
        
        stats = history.get_tool_stats("tool1")
        assert stats["tool_name"] == "tool1"
        assert stats["total_calls"] == 3
        assert stats["success_count"] == 2
        assert stats["failure_count"] == 1
        assert stats["success_rate"] == 2 / 3
        assert stats["avg_duration_ms"] == 20.0
        assert stats["min_duration_ms"] == 10.0
        assert stats["max_duration_ms"] == 30.0

    def test_get_tool_stats_no_calls(self, tmp_path, monkeypatch):
        history_file = tmp_path / "history.json"
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.HISTORY_FILE", history_file)
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.STORE_DIR", tmp_path)
        
        history = ToolHistory()
        stats = history.get_tool_stats("nonexistent")
        assert stats["total_calls"] == 0

    def test_clear(self, tmp_path, monkeypatch):
        history_file = tmp_path / "history.json"
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.HISTORY_FILE", history_file)
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.STORE_DIR", tmp_path)
        
        history = ToolHistory()
        history.record(ToolCallRecord("tool1", {}, True, 10.0))
        history.record(ToolCallRecord("tool2", {}, True, 10.0))
        
        history.clear()
        assert len(history.get_recent()) == 0

    def test_persistence(self, tmp_path, monkeypatch):
        history_file = tmp_path / "history.json"
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.HISTORY_FILE", history_file)
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.STORE_DIR", tmp_path)
        
        # Create and populate history
        history1 = ToolHistory()
        history1.record(ToolCallRecord("tool1", {"arg": "value"}, True, 10.0))
        
        # Create new history instance (should load from disk)
        history2 = ToolHistory()
        recent = history2.get_recent()
        assert len(recent) == 1
        assert recent[0].tool_name == "tool1"
        assert recent[0].arguments == {"arg": "value"}

    def test_max_size_limit(self, tmp_path, monkeypatch):
        history_file = tmp_path / "history.json"
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.HISTORY_FILE", history_file)
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.STORE_DIR", tmp_path)
        
        history = ToolHistory(max_size=5)
        for i in range(10):
            history.record(ToolCallRecord(f"tool_{i}", {}, True, 10.0))
        
        # Should only keep last 5
        recent = history.get_recent()
        assert len(recent) == 5
        # Should be the last 5 tools
        assert recent[0].tool_name == "tool_5"
        assert recent[4].tool_name == "tool_9"

    def test_corrupt_file_handled_gracefully(self, tmp_path, monkeypatch):
        history_file = tmp_path / "history.json"
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.HISTORY_FILE", history_file)
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.STORE_DIR", tmp_path)
        
        # Write corrupt data
        history_file.write_text("{invalid json", encoding="utf-8")
        
        # Should not raise, just log warning
        history = ToolHistory()
        assert len(history.get_recent()) == 0


class TestGetHistory:
    def test_get_history_returns_same_instance(self, tmp_path, monkeypatch):
        history_file = tmp_path / "history.json"
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.HISTORY_FILE", history_file)
        monkeypatch.setattr("ollamadev_mcp_server.tool_history.STORE_DIR", tmp_path)
        
        # Reset global instance
        import ollamadev_mcp_server.tool_history as th_module
        th_module._history = None
        
        history1 = get_history()
        history2 = get_history()
        assert history1 is history2

"""Tests for tool runtime core abstractions."""

import json
import time
from pathlib import Path

import pytest

from ollamadev_mcp_server.tool_runtime import (
    ErrorCategory,
    ToolContext,
    ToolError,
    ToolMetrics,
    ToolResponse,
)


class TestErrorCategory:
    """Test ErrorCategory enum."""

    def test_all_categories_exist(self):
        """Verify all expected categories are defined."""
        assert ErrorCategory.VALIDATION.value == "validation"
        assert ErrorCategory.NOT_FOUND.value == "not_found"
        assert ErrorCategory.PERMISSION.value == "permission"
        assert ErrorCategory.TIMEOUT.value == "timeout"
        assert ErrorCategory.EXECUTION.value == "execution"
        assert ErrorCategory.IO.value == "io"
        assert ErrorCategory.CONFIGURATION.value == "configuration"
        assert ErrorCategory.EXTERNAL_SERVICE.value == "external_service"
        assert ErrorCategory.INTERNAL.value == "internal"

    def test_category_count(self):
        """Verify we have the expected number of categories."""
        assert len(ErrorCategory) == 9


class TestToolContext:
    """Test ToolContext dataclass."""

    def test_context_creation(self, tmp_path):
        """Test basic context creation."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()
        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        assert ctx.workspace_root == tmp_path
        assert ctx.request_id == "test-123"
        assert ctx.agent_id == "-"
        assert ctx.correlation_id == "-"

    def test_context_with_all_fields(self, tmp_path):
        """Test context creation with all fields."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()
        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
            agent_id="agent-456",
            correlation_id="corr-789",
        )

        assert ctx.agent_id == "agent-456"
        assert ctx.correlation_id == "corr-789"

    def test_elapsed_ms(self, tmp_path):
        """Test elapsed time tracking."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()
        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        time.sleep(0.1)
        elapsed = ctx.elapsed_ms()

        assert elapsed >= 100  # At least 100ms
        assert elapsed < 200  # Less than 200ms

    def test_safe_path_valid(self, tmp_path):
        """Test safe_path with valid path."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()
        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        resolved = ctx.safe_path("test.txt")
        assert resolved == test_file.resolve()

    def test_safe_path_traversal_blocked(self, tmp_path):
        """Test safe_path blocks path traversal."""
        from ollamadev_mcp_server.config import get_config
        from ollamadev_mcp_server.errors import SecurityError

        config = get_config()
        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        with pytest.raises(SecurityError):
            ctx.safe_path("../etc/passwd")


class TestToolResponse:
    """Test ToolResponse dataclass."""

    def test_success_response(self):
        """Test success response creation."""
        response = ToolResponse(
            success=True,
            tool="test_tool",
            duration_ms=123.45,
            data={"result": "success"},
        )

        assert response.success is True
        assert response.tool == "test_tool"
        assert response.duration_ms == 123.45
        assert response.data == {"result": "success"}
        assert response.error is None

    def test_error_response(self):
        """Test error response creation."""
        response = ToolResponse(
            success=False,
            tool="test_tool",
            duration_ms=50.0,
            error={"code": "TEST_ERROR", "message": "Test failed"},
        )

        assert response.success is False
        assert response.error is not None
        assert response.error["code"] == "TEST_ERROR"

    def test_to_dict(self):
        """Test conversion to dictionary."""
        response = ToolResponse(
            success=True,
            tool="test_tool",
            duration_ms=100.0,
            data={"key": "value"},
            warnings=["Warning 1"],
        )

        result = response.to_dict()

        assert result["success"] is True
        assert result["tool"] == "test_tool"
        assert result["duration_ms"] == 100.0
        assert result["data"] == {"key": "value"}
        assert result["warnings"] == ["Warning 1"]

    def test_to_dict_rounds_duration(self):
        """Test that duration is rounded to 2 decimals."""
        response = ToolResponse(
            success=True,
            tool="test_tool",
            duration_ms=123.456789,
        )

        result = response.to_dict()
        assert result["duration_ms"] == 123.46

    def test_to_json(self):
        """Test JSON serialization."""
        response = ToolResponse(
            success=True,
            tool="test_tool",
            duration_ms=100.0,
            data={"key": "value"},
        )

        json_str = response.to_json()
        parsed = json.loads(json_str)

        assert parsed["success"] is True
        assert parsed["tool"] == "test_tool"
        assert parsed["duration_ms"] == 100.0

    def test_to_json_indent(self):
        """Test JSON indentation."""
        response = ToolResponse(
            success=True,
            tool="test_tool",
            duration_ms=100.0,
        )

        json_str = response.to_json(indent=4)
        assert "    " in json_str  # 4-space indent

    def test_response_with_warnings(self):
        """Test response with warnings."""
        response = ToolResponse(
            success=True,
            tool="test_tool",
            duration_ms=100.0,
            data={"result": "ok"},
            warnings=["Deprecation warning", "Performance warning"],
        )

        assert len(response.warnings) == 2
        assert "Deprecation warning" in response.warnings


class TestToolError:
    """Test ToolError dataclass."""

    def test_error_creation(self):
        """Test basic error creation."""
        error = ToolError(
            category=ErrorCategory.VALIDATION,
            code="INVALID_INPUT",
            message="Input is invalid",
        )

        assert error.category == ErrorCategory.VALIDATION
        assert error.code == "INVALID_INPUT"
        assert error.message == "Input is invalid"
        assert error.context == {}

    def test_error_with_context(self):
        """Test error with context."""
        error = ToolError(
            category=ErrorCategory.NOT_FOUND,
            code="FILE_NOT_FOUND",
            message="File not found",
            context={"path": "/test/file.txt", "workspace": "/workspace"},
        )

        assert error.context["path"] == "/test/file.txt"
        assert error.context["workspace"] == "/workspace"

    def test_to_dict(self):
        """Test conversion to dictionary."""
        error = ToolError(
            category=ErrorCategory.PERMISSION,
            code="ACCESS_DENIED",
            message="Access denied",
            context={"resource": "file.txt"},
        )

        result = error.to_dict()

        assert result["category"] == "permission"
        assert result["code"] == "ACCESS_DENIED"
        assert result["message"] == "Access denied"
        assert result["context"]["resource"] == "file.txt"

    def test_to_response(self):
        """Test conversion to ToolResponse."""
        error = ToolError(
            category=ErrorCategory.TIMEOUT,
            code="OPERATION_TIMEOUT",
            message="Operation timed out",
        )

        response = error.to_response("test_tool", 5000.0)

        assert response.success is False
        assert response.tool == "test_tool"
        assert response.duration_ms == 5000.0
        assert response.error is not None
        assert response.error["code"] == "OPERATION_TIMEOUT"


class TestToolMetrics:
    """Test ToolMetrics dataclass."""

    def test_metrics_creation(self):
        """Test basic metrics creation."""
        metrics = ToolMetrics(
            tool_name="test_tool",
            duration_ms=100.0,
            success=True,
        )

        assert metrics.tool_name == "test_tool"
        assert metrics.duration_ms == 100.0
        assert metrics.success is True
        assert metrics.error_category is None
        assert metrics.error_code is None
        assert metrics.timestamp > 0

    def test_metrics_with_error(self):
        """Test metrics with error information."""
        metrics = ToolMetrics(
            tool_name="test_tool",
            duration_ms=50.0,
            success=False,
            error_category=ErrorCategory.VALIDATION,
            error_code="INVALID_INPUT",
        )

        assert metrics.success is False
        assert metrics.error_category == ErrorCategory.VALIDATION
        assert metrics.error_code == "INVALID_INPUT"

    def test_metrics_record(self, tmp_path, monkeypatch):
        """Test metrics recording to history."""
        from ollamadev_mcp_server import tool_history
        from ollamadev_mcp_server.tool_history import ToolHistory

        # Use temporary history file
        history_file = tmp_path / "history.json"
        monkeypatch.setattr(tool_history, "HISTORY_FILE", history_file)
        monkeypatch.setattr(tool_history, "STORE_DIR", tmp_path)

        # Reset global history
        tool_history._history = None

        metrics = ToolMetrics(
            tool_name="test_tool",
            duration_ms=100.0,
            success=True,
        )

        metrics.record()

        # Verify history was recorded
        history = ToolHistory()
        records = history.get_recent(1)

        assert len(records) == 1
        assert records[0].tool_name == "test_tool"
        assert records[0].success is True
        assert records[0].duration_ms == 100.0

"""Tests for tool runtime decorator and helper functions."""

import json
from pathlib import Path

import pytest

from ollamadev_mcp_server.tool_decorator import (
    _convert_exception,
    error_response,
    read_workspace_file,
    run_subprocess,
    success_response,
    tool_runtime,
    write_workspace_file,
)
from ollamadev_mcp_server.tool_runtime import (
    ErrorCategory,
    ToolContext,
    ToolError,
    ToolResponse,
)


class TestConvertException:
    """Test exception conversion to ToolError."""

    def test_validation_error(self):
        """Test ValidationError conversion."""
        from ollamadev_mcp_server.errors import ValidationError

        exc = ValidationError("Invalid input", field="name")
        error = _convert_exception(exc)

        assert error.category == ErrorCategory.VALIDATION
        assert error.code == "VALIDATION_ERROR"
        assert error.message == "Invalid input"
        assert error.context["field"] == "name"

    def test_security_error(self):
        """Test SecurityError conversion."""
        from ollamadev_mcp_server.errors import SecurityError

        exc = SecurityError("Access denied")
        error = _convert_exception(exc)

        assert error.category == ErrorCategory.PERMISSION
        assert error.code == "SECURITY_ERROR"

    def test_dependency_error(self):
        """Test DependencyError conversion."""
        from ollamadev_mcp_server.errors import DependencyError

        exc = DependencyError("Service unavailable")
        error = _convert_exception(exc)

        assert error.category == ErrorCategory.EXTERNAL_SERVICE
        assert error.code == "DEPENDENCY_ERROR"

    def test_timeout_error(self):
        """Test ToolTimeoutError conversion."""
        from ollamadev_mcp_server.errors import ToolTimeoutError

        exc = ToolTimeoutError("Operation timed out")
        error = _convert_exception(exc)

        assert error.category == ErrorCategory.TIMEOUT
        assert error.code == "TIMEOUT"

    def test_file_not_found_error(self):
        """Test FileNotFoundError conversion."""
        exc = FileNotFoundError("File not found: test.txt")
        error = _convert_exception(exc)

        assert error.category == ErrorCategory.NOT_FOUND
        assert error.code == "FILE_NOT_FOUND"
        assert "test.txt" in error.message

    def test_permission_error(self):
        """Test PermissionError conversion."""
        exc = PermissionError("Access denied")
        error = _convert_exception(exc)

        assert error.category == ErrorCategory.PERMISSION
        assert error.code == "PERMISSION_DENIED"

    def test_timeout_error_builtin(self):
        """Test built-in TimeoutError conversion."""
        exc = TimeoutError("Operation timed out")
        error = _convert_exception(exc)

        assert error.category == ErrorCategory.TIMEOUT
        assert error.code == "TIMEOUT"

    def test_value_error(self):
        """Test ValueError conversion."""
        exc = ValueError("Invalid value")
        error = _convert_exception(exc)

        assert error.category == ErrorCategory.VALIDATION
        assert error.code == "INVALID_ARGUMENT"

    def test_runtime_error(self):
        """Test RuntimeError conversion."""
        exc = RuntimeError("Runtime failure")
        error = _convert_exception(exc)

        assert error.category == ErrorCategory.EXECUTION
        assert error.code == "RUNTIME_ERROR"

    def test_unknown_error(self):
        """Test unknown exception conversion."""
        exc = Exception("Unknown error")
        error = _convert_exception(exc)

        assert error.category == ErrorCategory.INTERNAL
        assert error.code == "INTERNAL_ERROR"
        assert error.context["exception_type"] == "Exception"


class TestToolRuntimeDecorator:
    """Test @tool_runtime decorator."""

    def test_decorator_success(self, tmp_path):
        """Test decorator with successful execution."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()

        @tool_runtime(name="test_tool")
        def test_func(ctx: ToolContext, value: str) -> str:
            return f"Result: {value}"

        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        result = test_func(ctx, "test")
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["tool"] == "test_tool"
        assert parsed["data"] == "Result: test"
        assert "duration_ms" in parsed

    def test_decorator_error(self, tmp_path):
        """Test decorator with error."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()

        @tool_runtime(name="test_tool")
        def test_func(ctx: ToolContext) -> str:
            raise ValueError("Test error")

        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        result = test_func(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["tool"] == "test_tool"
        assert parsed["error"]["code"] == "INVALID_ARGUMENT"
        assert "duration_ms" in parsed

    def test_decorator_auto_context(self, tmp_path, monkeypatch):
        """Test decorator auto-creates context if not provided."""
        from ollamadev_mcp_server import config as config_module

        # Mock config
        monkeypatch.setattr(config_module, "_config", None)

        @tool_runtime(name="test_tool")
        def test_func(ctx: ToolContext) -> str:
            return "success"

        # Call without context
        result = test_func()
        parsed = json.loads(result)

        assert parsed["success"] is True

    def test_decorator_with_tool_response(self, tmp_path):
        """Test decorator with ToolResponse return."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()

        @tool_runtime(name="test_tool")
        def test_func(ctx: ToolContext) -> ToolResponse:
            return ToolResponse(
                success=True,
                tool="custom_tool",
                duration_ms=50.0,
                data={"custom": "data"},
            )

        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        result = test_func(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["tool"] == "custom_tool"
        assert parsed["data"] == {"custom": "data"}

    def test_decorator_metrics_tracking(self, tmp_path, monkeypatch):
        """Test decorator tracks metrics."""
        from ollamadev_mcp_server import tool_history
        from ollamadev_mcp_server.config import get_config
        from ollamadev_mcp_server.tool_history import ToolHistory

        # Use temporary history file
        history_file = tmp_path / "history.json"
        monkeypatch.setattr(tool_history, "HISTORY_FILE", history_file)
        monkeypatch.setattr(tool_history, "STORE_DIR", tmp_path)

        # Reset global history
        tool_history._history = None

        config = get_config()

        @tool_runtime(name="test_tool", track_metrics=True)
        def test_func(ctx: ToolContext) -> str:
            return "success"

        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        test_func(ctx)

        # Verify metrics were recorded
        history = ToolHistory()
        records = history.get_recent(1)

        assert len(records) == 1
        assert records[0].tool_name == "test_tool"
        assert records[0].success is True

    def test_decorator_no_metrics_tracking(self, tmp_path, monkeypatch):
        """Test decorator with metrics disabled."""
        from ollamadev_mcp_server import tool_history
        from ollamadev_mcp_server.config import get_config
        from ollamadev_mcp_server.tool_history import ToolHistory

        # Use temporary history file
        history_file = tmp_path / "history.json"
        monkeypatch.setattr(tool_history, "HISTORY_FILE", history_file)
        monkeypatch.setattr(tool_history, "STORE_DIR", tmp_path)

        # Reset global history
        tool_history._history = None

        config = get_config()

        @tool_runtime(name="test_tool", track_metrics=False)
        def test_func(ctx: ToolContext) -> str:
            return "success"

        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        test_func(ctx)

        # Verify no metrics were recorded
        history = ToolHistory()
        records = history.get_recent(1)

        assert len(records) == 0


class TestHelperFunctions:
    """Test helper functions."""

    def test_read_workspace_file(self, tmp_path):
        """Test read_workspace_file helper."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()
        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!")

        content = read_workspace_file(ctx, "test.txt")
        assert content == "Hello, World!"

    def test_read_workspace_file_not_found(self, tmp_path):
        """Test read_workspace_file with missing file."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()
        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        with pytest.raises(FileNotFoundError):
            read_workspace_file(ctx, "missing.txt")

    def test_read_workspace_file_not_file(self, tmp_path):
        """Test read_workspace_file with directory."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()
        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        # Create directory
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        with pytest.raises(ValueError, match="not a file"):
            read_workspace_file(ctx, "test_dir")

    def test_write_workspace_file(self, tmp_path):
        """Test write_workspace_file helper."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()
        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        bytes_written = write_workspace_file(ctx, "test.txt", "Hello, World!")

        assert bytes_written == 13
        assert (tmp_path / "test.txt").read_text() == "Hello, World!"

    def test_write_workspace_file_creates_dirs(self, tmp_path):
        """Test write_workspace_file creates parent directories."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()
        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        write_workspace_file(ctx, "subdir/test.txt", "content")

        assert (tmp_path / "subdir" / "test.txt").exists()

    def test_run_subprocess(self, tmp_path):
        """Test run_subprocess helper."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()
        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        result = run_subprocess(ctx, ["echo", "test"])

        assert result["returncode"] == 0
        assert "test" in result["stdout"]

    def test_run_subprocess_with_input(self, tmp_path):
        """Test run_subprocess with input."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()
        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        result = run_subprocess(ctx, ["cat"], input_data="test input")

        assert result["returncode"] == 0
        assert "test input" in result["stdout"]

    def test_success_response(self, tmp_path):
        """Test success_response helper."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()
        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        response = success_response(ctx, {"result": "success"})

        assert response.success is True
        assert response.data == {"result": "success"}
        assert response.duration_ms >= 0

    def test_success_response_with_warnings(self, tmp_path):
        """Test success_response with warnings."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()
        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        response = success_response(
            ctx,
            {"result": "success"},
            warnings=["Warning 1", "Warning 2"],
        )

        assert len(response.warnings) == 2

    def test_error_response(self, tmp_path):
        """Test error_response helper."""
        from ollamadev_mcp_server.config import get_config

        config = get_config()
        ctx = ToolContext(
            workspace_root=tmp_path,
            config=config,
            request_id="test-123",
        )

        error = ToolError(
            category=ErrorCategory.VALIDATION,
            code="TEST_ERROR",
            message="Test error",
        )

        response = error_response(ctx, error)

        assert response.success is False
        assert response.error["code"] == "TEST_ERROR"
        assert response.duration_ms >= 0

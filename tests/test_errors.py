"""Tests for centralized error handling."""

import json

from ollamadev_mcp_server.errors import (
    DependencyError,
    OllamaDevError,
    SecurityError,
    ToolTimeoutError,
    ValidationError,
    format_error_response,
    handle_tool_error,
)


class TestOllamaDevError:
    def test_basic(self):
        err = OllamaDevError("something broke", code="TEST", status_code=500)
        assert str(err) == "something broke"
        assert err.message == "something broke"
        assert err.code == "TEST"
        assert err.status_code == 500
        assert err.context == {}

    def test_with_context(self):
        err = OllamaDevError("fail", context={"key": "value"})
        assert err.context == {"key": "value"}


class TestValidationError:
    def test_defaults(self):
        err = ValidationError("bad input")
        assert err.code == "VALIDATION_ERROR"
        assert err.status_code == 400

    def test_kwargs_become_context(self):
        err = ValidationError("bad path", field="path", value="../etc")
        assert err.context == {"field": "path", "value": "../etc"}


class TestSecurityError:
    def test_defaults(self):
        err = SecurityError("access denied")
        assert err.code == "SECURITY_ERROR"
        assert err.status_code == 403


class TestDependencyError:
    def test_defaults(self):
        err = DependencyError("service unavailable")
        assert err.code == "DEPENDENCY_ERROR"
        assert err.status_code == 503


class TestToolTimeoutError:
    def test_defaults(self):
        err = ToolTimeoutError("timed out")
        assert err.code == "TIMEOUT"
        assert err.status_code == 504


class TestFormatErrorResponse:
    def test_format(self):
        err = ValidationError("bad input", field="path")
        output = format_error_response(err)
        data = json.loads(output)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert data["error"]["message"] == "bad input"
        assert data["error"]["context"]["field"] == "path"


class TestHandleToolError:
    def test_handles_ollamadev_error(self):
        err = ValidationError("bad input")
        output = handle_tool_error(err, "test_tool")
        data = json.loads(output)
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_handles_unexpected_error(self):
        err = RuntimeError("unexpected")
        output = handle_tool_error(err, "test_tool")
        data = json.loads(output)
        assert data["error"]["code"] == "INTERNAL_ERROR"
        assert "internal error" in data["error"]["message"].lower()

"""Tests for structured logging configuration."""

import json
import logging

from ollamadev_mcp_server.logging_config import (
    JSONFormatter,
    TextFormatter,
    bind_request,
    configure_logging,
    get_context,
    get_logger,
    new_request_id,
)


class TestNewRequestId:
    def test_returns_string(self):
        rid = new_request_id()
        assert isinstance(rid, str)

    def test_length(self):
        rid = new_request_id()
        assert len(rid) == 16

    def test_unique(self):
        ids = {new_request_id() for _ in range(100)}
        assert len(ids) == 100


class TestBindRequest:
    def test_bind_and_get_context(self):
        rid = bind_request(request_id="test123", tool_name="ping", agent_id="agent1")
        assert rid == "test123"
        ctx = get_context()
        assert ctx["request_id"] == "test123"
        assert ctx["tool_name"] == "ping"
        assert ctx["agent_id"] == "agent1"

    def test_bind_generates_id_if_none(self):
        rid = bind_request()
        assert len(rid) == 16
        ctx = get_context()
        assert ctx["request_id"] == rid


class TestJSONFormatter:
    def test_format_produces_json(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["message"] == "hello world"
        assert data["module"] == "test"
        assert data["line"] == 42
        assert "timestamp" in data
        assert "request_id" in data
        assert "tool_name" in data

    def test_format_includes_extra_data(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="test.py", lineno=1,
            msg="test", args=(), exc_info=None,
        )
        record.extra_data = {"key": "value"}
        output = formatter.format(record)
        data = json.loads(output)
        assert data["data"] == {"key": "value"}

    def test_format_includes_exception(self):
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test", level=logging.ERROR,
            pathname="test.py", lineno=1,
            msg="error occurred", args=(), exc_info=exc_info,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["exception"]["type"] == "ValueError"
        assert data["exception"]["message"] == "test error"


class TestTextFormatter:
    def test_format_with_context(self):
        formatter = TextFormatter("%(message)s")
        bind_request(request_id="abc", tool_name="ping")
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="test.py", lineno=1,
            msg="hello", args=(), exc_info=None,
        )
        output = formatter.format(record)
        assert "[abc/ping]" in output
        assert "hello" in output


class TestConfigureLogging:
    def test_configure_json(self):
        configure_logging(level="DEBUG", fmt="json")
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert len(root.handlers) >= 1
        assert isinstance(root.handlers[0].formatter, JSONFormatter)

    def test_configure_text(self):
        configure_logging(level="INFO", fmt="text")
        root = logging.getLogger()
        assert isinstance(root.handlers[0].formatter, TextFormatter)

    def test_quiet_noisy_loggers(self):
        configure_logging()
        assert logging.getLogger("uvicorn.access").level == logging.WARNING
        assert logging.getLogger("httpx").level == logging.WARNING


class TestGetLogger:
    def test_returns_logger(self):
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.module"

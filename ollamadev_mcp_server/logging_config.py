"""Structured logging configuration for the OllamaDev MCP server.

Provides JSON-formatted logging with request-scoped correlation IDs,
tool names, and agent IDs. All log entries include context from
ContextVars so concurrent requests are properly separated.

Usage::

    from ollamadev_mcp_server.logging_config import configure_logging, get_logger

    configure_logging()  # call once at server startup
    logger = get_logger(__name__)
    logger.info("Tool call: %s", tool_name)
"""

import json
import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

# ---------------------------------------------------------------------------
# Request-scoped context variables
# ---------------------------------------------------------------------------

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_tool_name: ContextVar[str] = ContextVar("tool_name", default="-")
_agent_id: ContextVar[str] = ContextVar("agent_id", default="-")


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    default_time_format = "%Y-%m-%dT%H:%M:%S"
    default_msec_format = "%s.%03dZ"

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # type: ignore[override]
        ct = self.converter(record.created)
        if datefmt:
            s = time.strftime(datefmt, ct)
        else:
            s = time.strftime(self.default_time_format, ct)
        return self.default_msec_format % (s, record.msecs)

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "request_id": _request_id.get("-"),
            "tool_name": _tool_name.get("-"),
            "agent_id": _agent_id.get("-"),
        }
        extra_data = getattr(record, "extra_data", None)
        if extra_data and isinstance(extra_data, dict):
            log_entry["data"] = extra_data
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc_value, _exc_tb = record.exc_info
            log_entry["exception"] = {
                "type": exc_type.__name__ if exc_type else "Unknown",
                "message": str(exc_value) if exc_value else "",
            }
        return json.dumps(log_entry, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable formatter that includes correlation context."""

    def format(self, record: logging.LogRecord) -> str:
        rid = _request_id.get("-")
        tool = _tool_name.get("-")
        base = super().format(record)
        if rid != "-" or tool != "-":
            return f"[{rid}/{tool}] {base}"
        return base


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure_logging(level: str | None = None, fmt: str | None = None) -> None:
    """Configure structured logging for the entire application.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR).
            Falls back to LOG_LEVEL env var, then INFO.
        fmt: Log format - "json" (default) or "text".
            Falls back to LOG_FORMAT env var.
    """
    log_level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    log_format = (fmt or os.environ.get("LOG_FORMAT", "json")).lower()

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level, logging.INFO))
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(TextFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(handler)

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("mcp").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def new_request_id() -> str:
    """Generate a new unique request identifier (16 hex chars)."""
    return uuid.uuid4().hex[:16]


def bind_request(
    request_id: str | None = None,
    tool_name: str = "-",
    agent_id: str = "-",
) -> str:
    """Bind request-scoped context for the current coroutine.

    Returns:
        The request ID that was bound.
    """
    rid = request_id or new_request_id()
    _request_id.set(rid)
    _tool_name.set(tool_name)
    _agent_id.set(agent_id)
    return rid


def get_context() -> dict[str, str]:
    """Return the current request context as a dict."""
    return {
        "request_id": _request_id.get("-"),
        "tool_name": _tool_name.get("-"),
        "agent_id": _agent_id.get("-"),
    }


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name."""
    return logging.getLogger(name)

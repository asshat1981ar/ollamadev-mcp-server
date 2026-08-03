"""Audit logging for destructive operations.

Writes a structured JSON-lines log to ``store/audit.log`` for every
auditable tool invocation.  The log is append-only and survives
restarts.

Usage::

    from ollamadev_mcp_server.audit import audit_log

    audit_log("delete_workspace_file", "client-abc", {"path": "foo.kt"}, result="Deleted")
"""

import json
import time
from pathlib import Path
from typing import Any

from ollamadev_mcp_server.constants import STORE_DIR
from ollamadev_mcp_server.logging_config import get_logger, _request_id

logger = get_logger(__name__)

AUDIT_LOG_FILE = STORE_DIR / "audit.log"

# Operations that require audit logging
AUDITABLE_OPERATIONS: frozenset[str] = frozenset({
    "write_workspace_file",
    "delete_workspace_file",
    "move_workspace_file",
    "apply_file_patch",
    "add_gradle_dependency",
    "git_commit_checkpoint",
    "run_shell_command",
    "update_server_settings",
    "reset_server_settings",
    "store_memory",
    "clear_memory",
})

# Keys whose values should be masked in audit entries
_SENSITIVE_KEYS = frozenset({"api_key", "token", "password", "secret", "content"})


def _mask_sensitive_args(args: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *args* with sensitive values masked."""
    masked: dict[str, Any] = {}
    for key, value in args.items():
        if any(s in key.lower() for s in _SENSITIVE_KEYS):
            if isinstance(value, str) and len(value) > 10:
                masked[key] = value[:5] + "***" + value[-5:]
            else:
                masked[key] = "***"
        else:
            masked[key] = value
    return masked


def audit_log(
    operation: str,
    client_id: str,
    arguments: dict[str, Any],
    result: str | None = None,
    error: str | None = None,
) -> None:
    """Record an auditable operation.

    Writes a single JSON line to the audit log file and emits a
    structured log entry.  No-op if *operation* is not in
    ``AUDITABLE_OPERATIONS``.
    """
    if operation not in AUDITABLE_OPERATIONS:
        return

    masked_args = _mask_sensitive_args(arguments)
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "request_id": _request_id.get("-"),
        "operation": operation,
        "client_id": client_id,
        "arguments": masked_args,
        "result_preview": result[:500] if result else None,
        "error": error,
    }

    # Append to audit log file
    try:
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.error("Failed to write audit log: %s", exc)

    # Also emit via structured logging
    logger.info(
        "AUDIT: %s by %s",
        operation,
        client_id,
        extra={"extra_data": entry},
    )


def get_audit_log_entries(limit: int = 100) -> list[dict]:
    """Read the most recent audit log entries (newest first)."""
    if not AUDIT_LOG_FILE.exists():
        return []
    entries: list[dict] = []
    try:
        with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return list(reversed(entries))

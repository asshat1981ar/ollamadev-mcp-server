"""Tests for audit logging."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from ollamadev_mcp_server.audit import (
    audit_log,
    get_audit_log_entries,
    AUDITABLE_OPERATIONS,
    AUDIT_LOG_FILE,
    _mask_sensitive_args,
)


class TestMaskSensitiveArgs:
    def test_masks_api_key(self):
        args = {"api_key": "sk-1234567890abcdef", "path": "foo.kt"}
        masked = _mask_sensitive_args(args)
        assert masked["api_key"] == "sk-12***bcdef"
        assert masked["path"] == "foo.kt"

    def test_masks_token(self):
        args = {"token": "long-token-value-here"}
        masked = _mask_sensitive_args(args)
        assert "***" in masked["token"]

    def test_masks_short_values_fully(self):
        args = {"api_key": "short"}
        masked = _mask_sensitive_args(args)
        assert masked["api_key"] == "***"

    def test_masks_content(self):
        args = {"content": "secret file content here"}
        masked = _mask_sensitive_args(args)
        assert "***" in masked["content"]

    def test_non_sensitive_unchanged(self):
        args = {"path": "foo.kt", "limit": 100}
        masked = _mask_sensitive_args(args)
        assert masked == args


class TestAuditLog:
    def test_auditable_operation_is_logged(self, tmp_path, monkeypatch):
        log_file = tmp_path / "audit.log"
        monkeypatch.setattr("ollamadev_mcp_server.audit.AUDIT_LOG_FILE", log_file)
        monkeypatch.setattr("ollamadev_mcp_server.audit.STORE_DIR", tmp_path)

        audit_log(
            operation="delete_workspace_file",
            client_id="test-client",
            arguments={"path": "foo.kt"},
            result="Deleted foo.kt",
        )

        assert log_file.exists()
        entries = get_audit_log_entries()
        assert len(entries) == 1
        assert entries[0]["operation"] == "delete_workspace_file"
        assert entries[0]["client_id"] == "test-client"
        assert entries[0]["arguments"]["path"] == "foo.kt"

    def test_non_auditable_operation_is_skipped(self, tmp_path, monkeypatch):
        log_file = tmp_path / "audit.log"
        monkeypatch.setattr("ollamadev_mcp_server.audit.AUDIT_LOG_FILE", log_file)
        monkeypatch.setattr("ollamadev_mcp_server.audit.STORE_DIR", tmp_path)

        audit_log(
            operation="ping",
            client_id="test-client",
            arguments={},
        )

        assert not log_file.exists()

    def test_multiple_entries_append(self, tmp_path, monkeypatch):
        log_file = tmp_path / "audit.log"
        monkeypatch.setattr("ollamadev_mcp_server.audit.AUDIT_LOG_FILE", log_file)
        monkeypatch.setattr("ollamadev_mcp_server.audit.STORE_DIR", tmp_path)

        for i in range(3):
            audit_log(
                operation="write_workspace_file",
                client_id="client",
                arguments={"path": f"file{i}.kt"},
            )

        entries = get_audit_log_entries()
        assert len(entries) == 3

    def test_get_audit_log_entries_limit(self, tmp_path, monkeypatch):
        log_file = tmp_path / "audit.log"
        monkeypatch.setattr("ollamadev_mcp_server.audit.AUDIT_LOG_FILE", log_file)
        monkeypatch.setattr("ollamadev_mcp_server.audit.STORE_DIR", tmp_path)

        for i in range(10):
            audit_log(
                operation="delete_workspace_file",
                client_id="client",
                arguments={"path": f"file{i}.kt"},
            )

        entries = get_audit_log_entries(limit=5)
        assert len(entries) == 5

    def test_get_audit_log_entries_newest_first(self, tmp_path, monkeypatch):
        log_file = tmp_path / "audit.log"
        monkeypatch.setattr("ollamadev_mcp_server.audit.AUDIT_LOG_FILE", log_file)
        monkeypatch.setattr("ollamadev_mcp_server.audit.STORE_DIR", tmp_path)

        audit_log("delete_workspace_file", "c", {"path": "first.kt"})
        audit_log("delete_workspace_file", "c", {"path": "second.kt"})

        entries = get_audit_log_entries()
        assert entries[0]["arguments"]["path"] == "second.kt"
        assert entries[1]["arguments"]["path"] == "first.kt"

    def test_get_audit_log_entries_empty(self, tmp_path, monkeypatch):
        log_file = tmp_path / "audit.log"
        monkeypatch.setattr("ollamadev_mcp_server.audit.AUDIT_LOG_FILE", log_file)
        entries = get_audit_log_entries()
        assert entries == []

    def test_sensitive_args_are_masked(self, tmp_path, monkeypatch):
        log_file = tmp_path / "audit.log"
        monkeypatch.setattr("ollamadev_mcp_server.audit.AUDIT_LOG_FILE", log_file)
        monkeypatch.setattr("ollamadev_mcp_server.audit.STORE_DIR", tmp_path)

        audit_log(
            operation="update_server_settings",
            client_id="client",
            arguments={"api_key": "sk-1234567890abcdef"},
        )

        entries = get_audit_log_entries()
        assert "sk-1234567890abcdef" not in json.dumps(entries)
        assert "***" in entries[0]["arguments"]["api_key"]


class TestAuditableOperations:
    def test_destructive_ops_are_auditable(self):
        assert "delete_workspace_file" in AUDITABLE_OPERATIONS
        assert "write_workspace_file" in AUDITABLE_OPERATIONS
        assert "run_shell_command" in AUDITABLE_OPERATIONS
        assert "reset_server_settings" in AUDITABLE_OPERATIONS

    def test_safe_ops_not_auditable(self):
        assert "ping" not in AUDITABLE_OPERATIONS
        assert "list_workspace_files" not in AUDITABLE_OPERATIONS
        assert "read_workspace_file" not in AUDITABLE_OPERATIONS

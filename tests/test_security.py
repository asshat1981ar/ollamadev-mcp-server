"""Tests for unified security middleware."""

import json
import pytest
from unittest.mock import patch, MagicMock

from ollamadev_mcp_server.security import SecurityContext
from ollamadev_mcp_server.errors import SecurityError, OllamaDevError


class TestSecurityContext:
    @patch("ollamadev_mcp_server.security.require_auth")
    @patch("ollamadev_mcp_server.security.get_cors_headers")
    def test_for_request(self, mock_cors, mock_auth):
        mock_auth.return_value = {"authenticated": True, "client_id": "abc123"}
        mock_cors.return_value = {"Access-Control-Allow-Origin": "*"}

        ctx = SecurityContext.for_request(path="/mcp", auth_header="Bearer token", origin="https://app.com")

        assert ctx.authenticated is True
        assert ctx.client_id == "abc123"
        assert ctx.cors_headers == {"Access-Control-Allow-Origin": "*"}
        mock_auth.assert_called_once_with("/mcp", "Bearer token")
        mock_cors.assert_called_once_with("https://app.com")

    @patch("ollamadev_mcp_server.security.require_auth")
    @patch("ollamadev_mcp_server.security.get_cors_headers")
    def test_for_request_defaults(self, mock_cors, mock_auth):
        mock_auth.return_value = {"authenticated": False, "client_id": "anonymous"}
        mock_cors.return_value = {}

        ctx = SecurityContext.for_request()

        mock_auth.assert_called_once_with("/mcp", None)
        mock_cors.assert_called_once_with(None)
        assert ctx.authenticated is False

    @patch("ollamadev_mcp_server.security._check_rate_limit")
    def test_check_rate_limit(self, mock_check):
        ctx = SecurityContext(authenticated=True, client_id="abc", cors_headers={})
        ctx.check_rate_limit(tool_name="ping")
        mock_check.assert_called_once_with("abc", "ping")

    @patch("ollamadev_mcp_server.security._audit_log")
    def test_audit(self, mock_audit):
        ctx = SecurityContext(authenticated=True, client_id="abc", cors_headers={})
        ctx.audit(
            operation="delete_workspace_file",
            arguments={"path": "foo.kt"},
            result="Deleted",
        )
        mock_audit.assert_called_once_with(
            operation="delete_workspace_file",
            client_id="abc",
            arguments={"path": "foo.kt"},
            result="Deleted",
            error=None,
        )

    @patch("ollamadev_mcp_server.security._audit_log")
    def test_audit_with_error(self, mock_audit):
        ctx = SecurityContext(authenticated=True, client_id="abc", cors_headers={})
        ctx.audit(
            operation="write_workspace_file",
            arguments={"path": "foo.kt"},
            error="Permission denied",
        )
        mock_audit.assert_called_once_with(
            operation="write_workspace_file",
            client_id="abc",
            arguments={"path": "foo.kt"},
            result=None,
            error="Permission denied",
        )


class TestSecurityContextIntegration:
    @patch("ollamadev_mcp_server.auth.AUTH_ENABLED", False)
    def test_full_flow_auth_disabled(self):
        ctx = SecurityContext.for_request(path="/mcp")
        assert ctx.authenticated is False
        assert ctx.client_id == "anonymous"
        # Rate limit and audit should not raise
        ctx.check_rate_limit(tool_name="ping")

    @patch("ollamadev_mcp_server.auth.AUTH_ENABLED", True)
    @patch("ollamadev_mcp_server.auth.API_KEY", "test-key")
    def test_full_flow_auth_enabled(self):
        ctx = SecurityContext.for_request(
            path="/mcp",
            auth_header="Bearer test-key",
        )
        assert ctx.authenticated is True
        assert len(ctx.client_id) == 16

    @patch("ollamadev_mcp_server.auth.AUTH_ENABLED", True)
    def test_full_flow_auth_missing_token(self):
        with pytest.raises(SecurityError):
            SecurityContext.for_request(path="/mcp")

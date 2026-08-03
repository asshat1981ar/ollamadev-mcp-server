"""Tests for authentication middleware."""

import hashlib
import pytest
from unittest.mock import patch

from ollamadev_mcp_server.auth import (
    AUTH_ENABLED,
    extract_bearer_token,
    verify_api_key,
    require_auth,
    client_id_from_token,
)
from ollamadev_mcp_server.errors import SecurityError


class TestExtractBearerToken:
    def test_valid_bearer_token(self):
        assert extract_bearer_token("Bearer sk-abc123") == "sk-abc123"

    def test_case_insensitive_scheme(self):
        assert extract_bearer_token("bearer sk-abc123") == "sk-abc123"
        assert extract_bearer_token("BEARER sk-abc123") == "sk-abc123"

    def test_none_header(self):
        assert extract_bearer_token(None) is None

    def test_empty_header(self):
        assert extract_bearer_token("") is None

    def test_wrong_scheme(self):
        assert extract_bearer_token("Basic abc123") is None

    def test_missing_token(self):
        assert extract_bearer_token("Bearer ") is None
        assert extract_bearer_token("Bearer") is None

    def test_extra_whitespace(self):
        assert extract_bearer_token("Bearer   sk-abc123  ") == "sk-abc123"


class TestVerifyApiKey:
    def test_empty_key_always_fails(self):
        assert verify_api_key("") is False

    @patch("ollamadev_mcp_server.auth.API_KEY", "test-key-123")
    def test_matches_plain_key(self):
        assert verify_api_key("test-key-123") is True

    @patch("ollamadev_mcp_server.auth.API_KEY", "test-key-123")
    def test_rejects_wrong_key(self):
        assert verify_api_key("wrong-key") is False

    @patch("ollamadev_mcp_server.auth.API_KEY", "")
    @patch("ollamadev_mcp_server.auth.API_KEY_HASH", hashlib.sha256(b"hashed-key").hexdigest())
    def test_matches_hashed_key(self):
        assert verify_api_key("hashed-key") is True

    @patch("ollamadev_mcp_server.auth.API_KEY", "")
    @patch("ollamadev_mcp_server.auth.API_KEY_HASH", hashlib.sha256(b"hashed-key").hexdigest())
    def test_rejects_wrong_hashed_key(self):
        assert verify_api_key("wrong-key") is False

    @patch("ollamadev_mcp_server.auth.API_KEY", "")
    @patch("ollamadev_mcp_server.auth.API_KEY_HASH", "")
    def test_no_configured_key_always_fails(self):
        assert verify_api_key("any-key") is False


class TestClientIdFromToken:
    def test_returns_16_char_hex(self):
        cid = client_id_from_token("test-token")
        assert len(cid) == 16
        assert all(c in "0123456789abcdef" for c in cid)

    def test_deterministic(self):
        assert client_id_from_token("same") == client_id_from_token("same")

    def test_different_tokens_different_ids(self):
        assert client_id_from_token("a") != client_id_from_token("b")


class TestRequireAuth:
    @patch("ollamadev_mcp_server.auth.AUTH_ENABLED", False)
    def test_disabled_returns_anonymous(self):
        ctx = require_auth("/mcp")
        assert ctx["authenticated"] is False
        assert ctx["client_id"] == "anonymous"

    @patch("ollamadev_mcp_server.auth.AUTH_ENABLED", True)
    def test_public_path_bypasses_auth(self):
        ctx = require_auth("/health")
        assert ctx["authenticated"] is False
        assert ctx["client_id"] == "public"

    @patch("ollamadev_mcp_server.auth.AUTH_ENABLED", True)
    def test_missing_token_raises(self):
        with pytest.raises(SecurityError, match="Missing"):
            require_auth("/mcp", auth_header=None)

    @patch("ollamadev_mcp_server.auth.AUTH_ENABLED", True)
    @patch("ollamadev_mcp_server.auth.API_KEY", "valid-key")
    def test_valid_token_succeeds(self):
        ctx = require_auth("/mcp", auth_header="Bearer valid-key")
        assert ctx["authenticated"] is True
        assert len(ctx["client_id"]) == 16

    @patch("ollamadev_mcp_server.auth.AUTH_ENABLED", True)
    @patch("ollamadev_mcp_server.auth.API_KEY", "valid-key")
    def test_invalid_token_raises(self):
        with pytest.raises(SecurityError, match="Invalid"):
            require_auth("/mcp", auth_header="Bearer wrong-key")

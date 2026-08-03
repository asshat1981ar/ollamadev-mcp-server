"""Tests for CORS configuration."""

from unittest.mock import patch

from ollamadev_mcp_server.cors import get_cors_headers


class TestGetCorsHeaders:
    @patch("ollamadev_mcp_server.cors.CORS_ENABLED", True)
    @patch("ollamadev_mcp_server.cors.CORS_ALLOWED_ORIGINS", ["*"])
    def test_wildcard_allows_any_origin(self):
        headers = get_cors_headers(origin="https://example.com")
        assert headers["Access-Control-Allow-Origin"] == "https://example.com"

    @patch("ollamadev_mcp_server.cors.CORS_ENABLED", True)
    @patch("ollamadev_mcp_server.cors.CORS_ALLOWED_ORIGINS", ["*"])
    def test_no_origin_returns_wildcard(self):
        headers = get_cors_headers(origin=None)
        assert headers["Access-Control-Allow-Origin"] == "*"

    @patch("ollamadev_mcp_server.cors.CORS_ENABLED", True)
    @patch("ollamadev_mcp_server.cors.CORS_ALLOWED_ORIGINS", ["https://app.com"])
    def test_specific_origin_allowed(self):
        headers = get_cors_headers(origin="https://app.com")
        assert headers["Access-Control-Allow-Origin"] == "https://app.com"

    @patch("ollamadev_mcp_server.cors.CORS_ENABLED", True)
    @patch("ollamadev_mcp_server.cors.CORS_ALLOWED_ORIGINS", ["https://app.com"])
    def test_unknown_origin_rejected(self):
        headers = get_cors_headers(origin="https://evil.com")
        assert headers == {}

    @patch("ollamadev_mcp_server.cors.CORS_ENABLED", False)
    def test_disabled_returns_empty(self):
        headers = get_cors_headers(origin="https://example.com")
        assert headers == {}

    @patch("ollamadev_mcp_server.cors.CORS_ENABLED", True)
    @patch("ollamadev_mcp_server.cors.CORS_ALLOWED_ORIGINS", ["*"])
    def test_includes_standard_headers(self):
        headers = get_cors_headers(origin="https://example.com")
        assert "Access-Control-Allow-Methods" in headers
        assert "Access-Control-Allow-Headers" in headers
        assert "Access-Control-Max-Age" in headers

    @patch("ollamadev_mcp_server.cors.CORS_ENABLED", True)
    @patch("ollamadev_mcp_server.cors.CORS_ALLOWED_ORIGINS", ["https://a.com", "https://b.com"])
    def test_multiple_allowed_origins(self):
        assert get_cors_headers("https://a.com")["Access-Control-Allow-Origin"] == "https://a.com"
        assert get_cors_headers("https://b.com")["Access-Control-Allow-Origin"] == "https://b.com"
        assert get_cors_headers("https://c.com") == {}

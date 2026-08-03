"""CORS configuration for the OllamaDev MCP server.

Generates CORS response headers based on configurable allowed origins.
CORS is **enabled by default** with a permissive wildcard policy.
Set ``CORS_ALLOWED_ORIGINS`` to restrict.

Usage::

    from ollamadev_mcp_server.cors import get_cors_headers

    headers = get_cors_headers(origin="https://ollamadev.app")
"""

import os

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CORS_ENABLED: bool = os.environ.get("CORS_ENABLED", "true").lower() == "true"

_raw_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "*")
CORS_ALLOWED_ORIGINS: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]

_raw_methods = os.environ.get("CORS_ALLOWED_METHODS", "POST,OPTIONS")
CORS_ALLOWED_METHODS: list[str] = [m.strip() for m in _raw_methods.split(",") if m.strip()]

_raw_headers = os.environ.get(
    "CORS_ALLOWED_HEADERS",
    "Content-Type,Authorization,MCP-Protocol-Version,Mcp-Session-Id",
)
CORS_ALLOWED_HEADERS: list[str] = [h.strip() for h in _raw_headers.split(",") if h.strip()]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_cors_headers(origin: str | None = None) -> dict[str, str]:
    """Return CORS headers for a response.

    Returns an empty dict when CORS is disabled or the origin is not
    allowed.
    """
    if not CORS_ENABLED:
        return {}

    allowed = False
    if "*" in CORS_ALLOWED_ORIGINS:
        allowed = True
    elif origin and origin in CORS_ALLOWED_ORIGINS:
        allowed = True

    if not allowed:
        return {}

    return {
        "Access-Control-Allow-Origin": origin or "*",
        "Access-Control-Allow-Methods": ", ".join(CORS_ALLOWED_METHODS),
        "Access-Control-Allow-Headers": ", ".join(CORS_ALLOWED_HEADERS),
        "Access-Control-Max-Age": "86400",
    }

"""Authentication middleware for the OllamaDev MCP server.

Supports bearer-token authentication with configurable API keys.
Authentication is **disabled by default** for backward compatibility.
Set ``AUTH_ENABLED=true`` and provide ``API_KEY`` or ``API_KEY_HASH``
to enable.

Usage::

    from ollamadev_mcp_server.auth import require_auth

    ctx = require_auth("/mcp", auth_header="Bearer sk-...")
"""

import hashlib
import hmac
import os

from ollamadev_mcp_server.errors import SecurityError
from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration (read once at import time, like constants.py)
# ---------------------------------------------------------------------------

AUTH_ENABLED: bool = os.environ.get("AUTH_ENABLED", "false").lower() == "true"
API_KEY: str = os.environ.get("API_KEY", "")
API_KEY_HASH: str = os.environ.get("API_KEY_HASH", "")  # SHA-256 hex digest

# Paths that never require authentication
PUBLIC_PATHS: frozenset[str] = frozenset({"/health", "/ping", "/metrics"})


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------


def verify_api_key(provided_key: str) -> bool:
    """Verify an API key against the configured key or hash.

    Uses constant-time comparison to prevent timing attacks.
    """
    if not provided_key:
        return False

    # Check against plain key (development only)
    if API_KEY and hmac.compare_digest(provided_key, API_KEY):
        return True

    # Check against hashed key (production)
    if API_KEY_HASH:
        provided_hash = hashlib.sha256(provided_key.encode("utf-8")).hexdigest()
        if hmac.compare_digest(provided_hash, API_KEY_HASH):
            return True

    return False


def extract_bearer_token(auth_header: str | None) -> str | None:
    """Extract the bearer token from an Authorization header value.

    Returns ``None`` if the header is missing or malformed.
    """
    if not auth_header:
        return None
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token if token else None


def client_id_from_token(token: str) -> str:
    """Derive a stable, opaque client ID from a token (for audit logs)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def require_auth(path: str, auth_header: str | None = None) -> dict:
    """Check authentication for a request.

    Args:
        path: The request path (e.g. ``/mcp``).
        auth_header: The ``Authorization`` header value.

    Returns:
        A context dict with ``authenticated`` (bool) and ``client_id`` (str).

    Raises:
        SecurityError: If authentication is enabled and the token is
            missing or invalid.
    """
    if not AUTH_ENABLED:
        return {"authenticated": False, "client_id": "anonymous"}

    if path in PUBLIC_PATHS:
        return {"authenticated": False, "client_id": "public"}

    token = extract_bearer_token(auth_header)
    if not token:
        logger.warning("Missing authentication token for path: %s", path)
        raise SecurityError("Missing or invalid authentication token")

    if not verify_api_key(token):
        logger.warning("Invalid authentication token for path: %s", path)
        raise SecurityError("Invalid authentication token")

    cid = client_id_from_token(token)
    logger.info("Authenticated client: %s", cid)
    return {"authenticated": True, "client_id": cid}

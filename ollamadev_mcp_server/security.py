"""Unified security middleware for the OllamaDev MCP server.

Ties together authentication, rate limiting, audit logging, and CORS
into a single ``SecurityContext`` that can be applied to every request.

Usage::

    from ollamadev_mcp_server.security import SecurityContext

    ctx = SecurityContext.for_request(path="/mcp", auth_header="Bearer ...")
    ctx.check_rate_limit(tool_name="ping")
    ctx.audit("delete_workspace_file", arguments={"path": "..."}, result="Deleted")
"""

from typing import Any

from ollamadev_mcp_server.audit import audit_log as _audit_log
from ollamadev_mcp_server.auth import require_auth
from ollamadev_mcp_server.cors import get_cors_headers
from ollamadev_mcp_server.logging_config import get_logger
from ollamadev_mcp_server.rate_limit import check_rate_limit as _check_rate_limit

logger = get_logger(__name__)


class SecurityContext:
    """Per-request security context.

    Created once per request, then passed through the tool-dispatch
    pipeline so every layer can check auth, enforce rate limits, and
    record audit entries.
    """

    def __init__(
        self,
        *,
        authenticated: bool,
        client_id: str,
        cors_headers: dict[str, str],
    ):
        self.authenticated = authenticated
        self.client_id = client_id
        self.cors_headers = cors_headers

    # --- Factory ---

    @classmethod
    def for_request(
        cls,
        path: str = "/mcp",
        auth_header: str | None = None,
        origin: str | None = None,
    ) -> "SecurityContext":
        """Build a security context for an incoming request."""
        auth_ctx = require_auth(path, auth_header)
        cors = get_cors_headers(origin)
        return cls(
            authenticated=auth_ctx["authenticated"],
            client_id=auth_ctx["client_id"],
            cors_headers=cors,
        )

    # --- Rate limiting ---

    def check_rate_limit(self, tool_name: str | None = None) -> None:
        """Enforce rate limits for this client."""
        _check_rate_limit(self.client_id, tool_name)

    # --- Audit ---

    def audit(
        self,
        operation: str,
        arguments: dict[str, Any],
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Record an auditable operation."""
        _audit_log(
            operation=operation,
            client_id=self.client_id,
            arguments=arguments,
            result=result,
            error=error,
        )

"""
OllamaDev companion MCP server — MCP Python SDK v2 beta.

Exposes a comprehensive toolbox of ~49 tools over HTTP Streamable transport.
Connect from OllamaDev: Add Server → URL: http://<host>:5000/mcp
"""

from mcp.server import MCPServer

from ollamadev_mcp_server.logging_config import configure_logging, get_logger

logger = get_logger(__name__)


def _register_health_tools(mcp: MCPServer) -> None:
    """Register the Phase 1 health-check tools."""
    import json as _json

    from ollamadev_mcp_server.config import get_config
    from ollamadev_mcp_server.health import get_health_status

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": True})
    def get_server_health(detailed: bool = False) -> str:
        """Return server health status including workspace, Ollama, and settings checks.

        Args:
            detailed: If True, include per-dependency check details (default: False).

        Returns:
            JSON with overall status (UP/DOWN/DEGRADED), uptime, and optionally
            per-dependency check results.
        """
        config = get_config()
        status = get_health_status(
            workspace_root=config.workspace_root,
            ollama_url=config.ollama_url,
            detailed=detailed,
        )
        return _json.dumps(status, indent=2)

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": True})
    def get_server_diagnostics() -> str:
        """Return server diagnostics: timeouts, logging config, and module info.

        Returns:
            JSON with timeout table, log level, and registered module count.
        """
        from ollamadev_mcp_server.timeouts import get_all_timeouts
        import logging as _logging

        config = get_config()
        root = _logging.getLogger()
        log_level = _logging.getLevelName(root.level) if root.level else "NOTSET"

        return _json.dumps(
            {
                "log_level": log_level,
                "timeouts": get_all_timeouts(),
                "workspace_root": str(config.workspace_root),
                "ollama_url": config.ollama_url,
            },
            indent=2,
        )


def _register_security_tools(mcp: MCPServer) -> None:
    """Register the Phase 2 security/audit tools."""
    import json as _json

    from ollamadev_mcp_server.audit import get_audit_log_entries

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": True})
    def get_audit_log(limit: int = 100) -> str:
        """Return recent audit log entries (destructive operations only).

        Args:
            limit: Maximum number of entries to return (default: 100).

        Returns:
            JSON array of audit entries, newest first.  Each entry includes
            timestamp, operation, client_id, masked arguments, and result preview.
        """
        entries = get_audit_log_entries(limit=limit)
        return _json.dumps(entries, indent=2, ensure_ascii=False)


def main() -> None:
    configure_logging()
    logger.info("Starting OllamaDev MCP server")

    # Load configuration
    from ollamadev_mcp_server.config import get_config
    config = get_config()

    # Register tool modules using the registry
    from ollamadev_mcp_server.registry import get_registry, register_default_modules
    register_default_modules()
    registry = get_registry()

    mcp = MCPServer("OllamaDev Toolbox")
    registry.register_all(mcp)

    # Phase 1: observability tools
    _register_health_tools(mcp)

    # Phase 2: security/audit tools
    _register_security_tools(mcp)

    # Start config watcher for hot-reload (optional, controlled by env var)
    import os
    if os.environ.get("CONFIG_WATCHER_ENABLED", "false").lower() == "true":
        from ollamadev_mcp_server.config_watcher import start_config_watcher
        start_config_watcher()

    # Start lightweight metrics HTTP server (MVP)
    try:
        from ollamadev_mcp_server.metrics_server import start_from_env

        start_from_env()
        logger.info("Metrics server started (env METRICS_PORT)")
    except Exception:
        logger.exception("Unable to start metrics server")

    logger.info(
        "All tools registered (%d modules), starting HTTP server on %s:%d",
        len(registry.get_modules()),
        config.host,
        config.port,
    )
    mcp.run(transport="streamable-http", host=config.host, port=config.port)


if __name__ == "__main__":
    main()

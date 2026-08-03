"""Health check tools for the OllamaDev MCP server.

Provides dependency health checks (workspace filesystem, Ollama API,
settings file) exposed as MCP tools.  The ``get_server_health`` tool
returns a JSON summary suitable for monitoring systems.

Usage::

    from ollamadev_mcp_server.health import get_health_status

    status = get_health_status(detailed=True)
"""

import json
import os
import time

import requests

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

_START = time.time()


def _check_workspace(workspace_root: "Path") -> dict:  # noqa: F821
    """Check workspace filesystem health."""
    from pathlib import Path as _Path
    try:
        wr = _Path(workspace_root)
        if not wr.exists():
            return {"status": "DOWN", "detail": f"Workspace root does not exist: {wr}"}
        if not os.access(str(wr), os.R_OK | os.W_OK):
            return {"status": "DEGRADED", "detail": "Workspace root is not readable/writable"}
        return {"status": "UP", "path": str(wr)}
    except Exception as exc:
        return {"status": "DOWN", "detail": str(exc)}


def _check_ollama(ollama_url: str) -> dict:
    """Check Ollama API health."""
    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=5)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            return {"status": "UP", "url": ollama_url, "model_count": len(models)}
        return {"status": "DEGRADED", "detail": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"status": "DOWN", "detail": f"Cannot connect to {ollama_url}: {exc}"}


def _check_settings() -> dict:
    """Check settings file accessibility."""
    from ollamadev_mcp_server.persistence import settings_file_path
    try:
        path = settings_file_path()
        parent = path.parent
        if not parent.exists():
            return {"status": "DEGRADED", "detail": f"Settings directory does not exist: {parent}"}
        return {"status": "UP", "path": str(path)}
    except Exception as exc:
        return {"status": "DOWN", "detail": str(exc)}


def get_health_status(
    workspace_root: "Path",  # noqa: F821
    ollama_url: str,
    detailed: bool = False,
) -> dict:
    """Compute overall health status.

    Args:
        workspace_root: Path to the workspace root.
        ollama_url: URL of the Ollama API.
        detailed: If True, include per-check details.

    Returns:
        Dict with ``status`` (UP/DOWN/DEGRADED), ``uptime_seconds``,
        ``timestamp``, and optionally ``checks``.
    """
    checks = {
        "workspace": _check_workspace(workspace_root),
        "ollama": _check_ollama(ollama_url),
        "settings": _check_settings(),
    }

    statuses = [c["status"] for c in checks.values()]
    if all(s == "UP" for s in statuses):
        overall = "UP"
    elif any(s == "DOWN" for s in statuses):
        overall = "DOWN"
    else:
        overall = "DEGRADED"

    result: dict = {
        "status": overall,
        "uptime_seconds": round(time.time() - _START, 1),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if detailed:
        result["checks"] = checks
    return result

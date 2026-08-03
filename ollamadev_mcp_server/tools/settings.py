"""Runtime settings tools for the OllamaDev MCP server.

Settings are persisted as JSON (default: ``<WORKSPACE_ROOT>/store/server_settings.json``,
overridable with the ``OLLAMADEV_SETTINGS_FILE`` env var) and follow the precedence:

    environment variable > persisted settings file > code default

Most settings are read once at server startup, so changes made via
``update_server_settings`` take effect on the next server restart.
``get_server_settings`` always reports the live effective values.
"""

import json
import os
from pathlib import Path

from mcp.server import MCPServer

from ollamadev_mcp_server import constants
from ollamadev_mcp_server.tool_decorator import tool_runtime
from ollamadev_mcp_server.tool_runtime import ToolContext
from ollamadev_mcp_server.persistence import (
    clear_persisted_settings,
    load_persisted_settings,
    save_persisted_settings,
)

ALLOWED_KEYS = (
    "workspace_root",
    "ollama_url",
    "ollama_api_key",
    "anthropic_api_key",
    "anthropic_auth_token",
    "anthropic_base_url",
    "default_cloud_model",
)

# Keys whose values are never echoed back in full.
SECRET_KEYS = frozenset({"ollama_api_key", "anthropic_api_key", "anthropic_auth_token"})

# Constants are resolved at import time, so every persisted key needs a restart.
RESTART_REQUIRED_KEYS = frozenset(ALLOWED_KEYS)

SETTINGS_FILE = Path(
    os.environ.get(
        "OLLAMADEV_SETTINGS_FILE",
        str(constants.WORKSPACE_ROOT / "store" / "server_settings.json"),
    )
)


def _masked(value: str) -> str:
    return "***" if value else ""


def effective_settings() -> dict:
    """Build a snapshot of the live effective configuration."""
    persisted = load_persisted_settings(SETTINGS_FILE)
    return {
        "workspace_root": str(constants.WORKSPACE_ROOT),
        "ollama_url": constants.OLLAMA_URL,
        "ollama_api_key_set": bool(constants.OLLAMA_API_KEY),
        "ollama_api_key": _masked(constants.OLLAMA_API_KEY),
        "anthropic_api_key_set": bool(constants.ANTHROPIC_API_KEY),
        "anthropic_api_key": _masked(constants.ANTHROPIC_API_KEY),
        "anthropic_auth_token_set": bool(constants.ANTHROPIC_AUTH_TOKEN),
        "anthropic_auth_token": _masked(constants.ANTHROPIC_AUTH_TOKEN),
        "anthropic_base_url": constants.ANTHROPIC_BASE_URL,
        "default_cloud_model": constants.DEFAULT_CLOUD_MODEL,
        "settings_file": str(SETTINGS_FILE),
        "store_dir": str(constants.STORE_DIR),
        "sprint_phases": list(constants.SPRINT_PHASES),
        "persisted_keys": sorted(persisted.keys()),
    }


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": True})
    @tool_runtime(name="get_server_settings")
    def get_server_settings(ctx: ToolContext = None) -> str:
        """Return the effective server configuration as JSON.

        Precedence: environment variable > persisted settings file > code default.
        Secret values are masked ('***') and reported via *_set flags.
        """
        return effective_settings()

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": False})
    @tool_runtime(name="update_server_settings")
    def update_server_settings(ctx: ToolContext = None, settings: dict = None) -> str:
        """Persist new server settings to the settings JSON file.

        Args:
            settings: Dict of allowed keys: workspace_root, ollama_url, ollama_api_key,
                      anthropic_api_key, anthropic_auth_token, anthropic_base_url,
                      default_cloud_model. Each value must be a non-empty string.

        Returns:
            Confirmation JSON including the settings file path, the saved values
            (secrets masked), and the keys that require a server restart.
        """
        if not isinstance(settings, dict) or not settings:
            raise ValueError("settings must be a non-empty dict of allowed keys")

        unknown = sorted(set(settings) - set(ALLOWED_KEYS))
        if unknown:
            raise ValueError(
                f"Unknown setting keys: {', '.join(unknown)}. "
                f"Allowed: {', '.join(ALLOWED_KEYS)}"
            )

        for key, value in settings.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Setting '{key}' must be a non-empty string")

        persisted = load_persisted_settings(SETTINGS_FILE)
        persisted.update({key: value.strip() for key, value in settings.items()})
        save_persisted_settings(persisted, SETTINGS_FILE)

        return {
            "status": "saved",
            "settings_file": str(SETTINGS_FILE),
            "saved": {
                key: (_masked(value) if key in SECRET_KEYS else value)
                for key, value in settings.items()
            },
            "restart_required": sorted(set(settings) & RESTART_REQUIRED_KEYS),
        }

    @mcp.tool(annotations={"destructiveHint": True, "readOnlyHint": False})
    @tool_runtime(name="reset_server_settings")
    def reset_server_settings(ctx: ToolContext = None) -> str:
        """Delete the persisted settings file and revert to env/code defaults.

        Warning: this discards all persisted overrides. A server restart is required
        for the revert to take effect.
        """
        removed = clear_persisted_settings(SETTINGS_FILE)
        return {
            "status": "reset",
            "removed_file": removed,
            "settings_file": str(SETTINGS_FILE),
            "note": "Restart the server to apply environment/default configuration.",
        }

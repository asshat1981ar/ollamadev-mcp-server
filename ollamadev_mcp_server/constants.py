"""Shared constants for the OllamaDev MCP toolbox.

Effective values follow the precedence:

    environment variable > persisted settings file > code default

The persisted settings file defaults to ``<WORKSPACE_ROOT>/store/server_settings.json``
and can be overridden with the ``OLLAMADEV_SETTINGS_FILE`` environment variable.
See ``ollamadev_mcp_server.tools.settings`` for the tools that manage it.
"""

import os
from pathlib import Path

from ollamadev_mcp_server.persistence import load_persisted_settings

_PERSISTED = load_persisted_settings()


def _resolve(key: str, default: str) -> str:
    """Return the env var for `key`, else the persisted value, else `default`."""
    env_key = key.upper()
    if env_key in os.environ:
        return os.environ[env_key]
    value = _PERSISTED.get(key)
    if value not in (None, ""):
        return str(value)
    return default


WORKSPACE_ROOT = Path(_resolve("workspace_root", "/home/userland/OllamaDev")).resolve()
OLLAMA_URL = _resolve("ollama_url", "http://localhost:11434").rstrip("/")
OLLAMA_API_KEY = _resolve("ollama_api_key", "")

# Cloud model provider configuration (used by suggest_next_action)
ANTHROPIC_API_KEY = _resolve("anthropic_api_key", "")
ANTHROPIC_AUTH_TOKEN = _resolve("anthropic_auth_token", "")
ANTHROPIC_BASE_URL = _resolve("anthropic_base_url", "https://api.anthropic.com").rstrip("/")
DEFAULT_CLOUD_MODEL = (
    os.environ.get("ANTHROPIC_DEFAULT_MODEL")
    or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
    or _PERSISTED.get("default_cloud_model")
    or "claude-sonnet-5-20251001"
)

# Cloudflare Computer integration — a remote, SQLite-backed virtual workspace
# (Durable Object) reached through its HTTP surface. The computer repo's
# examples expose: PUT/GET  /c/<name>/file/workspace/<path>  and
# POST /c/<name>/exec  with {"command", "cwd"}.
CF_COMPUTER_BASE_URL = _resolve("cf_computer_base_url", "http://127.0.0.1:8787").rstrip("/")
CF_COMPUTER_WORKSPACE = _resolve("cf_computer_workspace", "compute")
CF_COMPUTER_TIMEOUT = int(_resolve("cf_computer_timeout", "30"))

STORE_DIR = WORKSPACE_ROOT / "store"

# Phase order for sprint artifacts
SPRINT_PHASES = [
    "discovery",
    "design",
    "implementation",
    "verification",
    "integration",
    "retrospective",
]

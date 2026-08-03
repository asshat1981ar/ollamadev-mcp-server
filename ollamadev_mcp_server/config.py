"""Server configuration management.

Provides a ``ServerConfig`` dataclass that consolidates all configuration
from environment variables and persisted settings.  Replaces the scattered
global constants in ``constants.py`` with a single, injectable config object.

Usage::

    from ollamadev_mcp_server.config import get_config

    config = get_config()
    print(config.workspace_root)
    print(config.ollama_url)
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ollamadev_mcp_server.logging_config import get_logger
from ollamadev_mcp_server.persistence import load_persisted_settings, settings_file_path

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ServerConfig:
    """Immutable server configuration.

    All fields are resolved at construction time from environment variables,
    persisted settings, and defaults (in that priority order).
    """

    # Workspace
    workspace_root: Path
    store_dir: Path

    # Ollama
    ollama_url: str
    ollama_api_key: str

    # Cloud provider (Anthropic)
    anthropic_api_key: str
    anthropic_auth_token: str
    anthropic_base_url: str
    default_cloud_model: str

    # Sprint phases
    sprint_phases: list[str] = field(
        default_factory=lambda: [
            "discovery",
            "design",
            "implementation",
            "verification",
            "integration",
            "retrospective",
        ]
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 5000

    # Timeouts
    default_tool_timeout: int = 60
    default_llm_timeout: int = 120
    default_shell_timeout: int = 300
    default_gradle_timeout: int = 600
    default_autonomous_timeout: int = 3600

    # Security (Phase 2)
    auth_enabled: bool = False
    api_key: str = ""
    api_key_hash: str = ""
    rate_limit_enabled: bool = True
    default_rate_limit: int = 100
    cors_enabled: bool = True

    # Logging (Phase 1)
    log_level: str = "INFO"
    log_format: str = "json"

    @property
    def settings_file(self) -> Path:
        """Return the path to the persisted settings file."""
        return settings_file_path()


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def _resolve(key: str, default: str, persisted: dict[str, str]) -> str:
    """Resolve a config value: env var > persisted > default."""
    env_key = key.upper()
    if env_key in os.environ:
        return os.environ[env_key]
    value = persisted.get(key)
    if value not in (None, ""):
        return str(value)
    return default


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_config() -> ServerConfig:
    """Load server configuration from environment and persisted settings.

    Priority: environment variable > persisted settings file > code default.
    """
    persisted = load_persisted_settings()

    workspace_root = Path(
        _resolve("workspace_root", "/home/userland/OllamaDev", persisted)
    ).resolve()

    return ServerConfig(
        workspace_root=workspace_root,
        store_dir=workspace_root / "store",
        ollama_url=_resolve("ollama_url", "http://localhost:11434", persisted).rstrip("/"),
        ollama_api_key=_resolve("ollama_api_key", "", persisted),
        anthropic_api_key=_resolve("anthropic_api_key", "", persisted),
        anthropic_auth_token=_resolve("anthropic_auth_token", "", persisted),
        anthropic_base_url=_resolve(
            "anthropic_base_url", "https://api.anthropic.com", persisted
        ).rstrip("/"),
        default_cloud_model=(
            os.environ.get("ANTHROPIC_DEFAULT_MODEL")
            or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
            or persisted.get("default_cloud_model")
            or "claude-sonnet-5-20251001"
        ),
        host=os.environ.get("SERVER_HOST", "0.0.0.0"),
        port=int(os.environ.get("SERVER_PORT", "5000")),
        default_tool_timeout=int(os.environ.get("DEFAULT_TOOL_TIMEOUT", "60")),
        default_llm_timeout=int(os.environ.get("DEFAULT_LLM_TIMEOUT", "120")),
        default_shell_timeout=int(os.environ.get("DEFAULT_SHELL_TIMEOUT", "300")),
        default_gradle_timeout=int(os.environ.get("DEFAULT_GRADLE_TIMEOUT", "600")),
        default_autonomous_timeout=int(
            os.environ.get("DEFAULT_AUTONOMOUS_TIMEOUT", "3600")
        ),
        auth_enabled=os.environ.get("AUTH_ENABLED", "false").lower() == "true",
        api_key=os.environ.get("API_KEY", ""),
        api_key_hash=os.environ.get("API_KEY_HASH", ""),
        rate_limit_enabled=os.environ.get("RATE_LIMIT_ENABLED", "true").lower() == "true",
        default_rate_limit=int(os.environ.get("DEFAULT_RATE_LIMIT", "100")),
        cors_enabled=os.environ.get("CORS_ENABLED", "true").lower() == "true",
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        log_format=os.environ.get("LOG_FORMAT", "json").lower(),
    )


# ---------------------------------------------------------------------------
# Global config instance
# ---------------------------------------------------------------------------

_config: ServerConfig | None = None


def get_config() -> ServerConfig:
    """Get the global server config.  Loads on first access."""
    global _config
    if _config is None:
        _config = load_config()
        logger.info("Configuration loaded: workspace=%s", _config.workspace_root)
    return _config


def reload_config() -> ServerConfig:
    """Reload configuration from disk/environment.

    Returns the new config instance.
    """
    global _config
    _config = load_config()
    logger.info("Configuration reloaded: workspace=%s", _config.workspace_root)
    return _config


def override_config(**overrides: Any) -> ServerConfig:
    """Create a config with overrides (for testing).

    Returns a new ``ServerConfig`` instance with the specified fields replaced.
    """
    import dataclasses

    base = get_config()
    return dataclasses.replace(base, **overrides)


def reset_config() -> None:
    """Reset the global config (for testing)."""
    global _config
    _config = None

"""Tests for server configuration management."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ollamadev_mcp_server.config import (
    ServerConfig,
    get_config,
    load_config,
    override_config,
    reload_config,
    reset_config,
)


class TestServerConfig:
    def test_config_is_frozen(self):
        config = load_config()
        with pytest.raises(AttributeError):
            config.workspace_root = Path("/tmp")

    def test_config_has_all_fields(self):
        config = load_config()
        assert hasattr(config, "workspace_root")
        assert hasattr(config, "ollama_url")
        assert hasattr(config, "anthropic_api_key")
        assert hasattr(config, "host")
        assert hasattr(config, "port")
        assert hasattr(config, "auth_enabled")

    def test_settings_file_property(self):
        config = load_config()
        assert config.settings_file is not None
        assert isinstance(config.settings_file, Path)


class TestLoadConfig:
    def test_load_config_returns_server_config(self):
        config = load_config()
        assert isinstance(config, ServerConfig)

    def test_load_config_uses_defaults(self):
        config = load_config()
        assert config.host == "0.0.0.0"
        assert config.port == 5000
        assert config.log_level == "INFO"

    def test_load_config_from_env(self, monkeypatch):
        monkeypatch.setenv("SERVER_HOST", "127.0.0.1")
        monkeypatch.setenv("SERVER_PORT", "8080")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        config = load_config()
        assert config.host == "127.0.0.1"
        assert config.port == 8080
        assert config.log_level == "DEBUG"


class TestGetConfig:
    def test_get_config_returns_same_instance(self):
        reset_config()
        config1 = get_config()
        config2 = get_config()
        assert config1 is config2

    def test_get_config_loads_on_first_access(self):
        reset_config()
        config = get_config()
        assert config is not None
        assert isinstance(config, ServerConfig)


class TestReloadConfig:
    def test_reload_config_returns_new_instance(self):
        reset_config()
        config1 = get_config()
        config2 = reload_config()
        assert config1 is not config2

    def test_reload_config_updates_global(self):
        reset_config()
        config1 = get_config()
        config2 = reload_config()
        config3 = get_config()
        assert config3 is config2
        assert config3 is not config1


class TestOverrideConfig:
    def test_override_config_creates_new_instance(self):
        reset_config()
        original = get_config()
        overridden = override_config(host="localhost", port=9999)
        assert overridden is not original
        assert overridden.host == "localhost"
        assert overridden.port == 9999

    def test_override_config_preserves_other_fields(self):
        reset_config()
        original = get_config()
        overridden = override_config(host="localhost")
        assert overridden.ollama_url == original.ollama_url
        assert overridden.log_level == original.log_level


class TestResetConfig:
    def test_reset_config_clears_global(self):
        reset_config()
        config1 = get_config()
        reset_config()
        config2 = get_config()
        assert config1 is not config2

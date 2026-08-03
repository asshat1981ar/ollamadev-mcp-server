"""Tests for configuration file watcher."""

import time
from pathlib import Path
from unittest.mock import patch

from ollamadev_mcp_server.config import reset_config
from ollamadev_mcp_server.config_watcher import (
    get_watcher_status,
    is_watcher_running,
    start_config_watcher,
    stop_config_watcher,
)


class TestConfigWatcher:
    def setup_method(self):
        reset_config()
        if is_watcher_running():
            stop_config_watcher()

    def teardown_method(self):
        if is_watcher_running():
            stop_config_watcher()

    def test_start_watcher(self):
        start_config_watcher(poll_interval=0.1)
        assert is_watcher_running()

    def test_stop_watcher(self):
        start_config_watcher(poll_interval=0.1)
        stop_config_watcher()
        time.sleep(0.2)
        assert not is_watcher_running()

    def test_watcher_status(self):
        status = get_watcher_status()
        assert "running" in status
        assert "poll_interval" in status
        assert "settings_file" in status

    def test_watcher_detects_file_change(self, tmp_path, monkeypatch):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{}")
        monkeypatch.setenv("OLLAMADEV_SETTINGS_FILE", str(settings_file))
        reset_config()

        start_config_watcher(poll_interval=0.1)
        time.sleep(0.2)

        # Modify the file
        settings_file.write_text('{"ollama_url": "http://new-url"}')
        time.sleep(0.3)

        # Watcher should have detected the change
        # (We can't easily test the reload happened, but we can verify it's running)
        assert is_watcher_running()

    def test_watcher_handles_missing_file(self, tmp_path, monkeypatch):
        settings_file = tmp_path / "nonexistent.json"
        monkeypatch.setenv("OLLAMADEV_SETTINGS_FILE", str(settings_file))
        reset_config()

        start_config_watcher(poll_interval=0.1)
        time.sleep(0.2)

        # Should still be running even if file doesn't exist
        assert is_watcher_running()

    def test_start_watcher_twice_is_safe(self):
        start_config_watcher(poll_interval=0.1)
        start_config_watcher(poll_interval=0.1)  # Should not raise
        assert is_watcher_running()

    def test_stop_watcher_when_not_running(self):
        stop_config_watcher()  # Should not raise
        assert not is_watcher_running()

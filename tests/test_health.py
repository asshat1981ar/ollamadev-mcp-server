"""Tests for health check tools."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from ollamadev_mcp_server.health import (
    _check_ollama,
    _check_settings,
    _check_workspace,
    get_health_status,
)


class TestCheckWorkspace:
    def test_workspace_exists_and_accessible(self, tmp_path):
        result = _check_workspace(tmp_path)
        assert result["status"] == "UP"
        assert result["path"] == str(tmp_path)

    def test_workspace_does_not_exist(self, tmp_path):
        missing = tmp_path / "nonexistent"
        result = _check_workspace(missing)
        assert result["status"] == "DOWN"
        assert "does not exist" in result["detail"]


class TestCheckOllama:
    def test_ollama_up(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "llama3"}]}
        with patch("ollamadev_mcp_server.health.requests") as mock_requests:
            mock_requests.get.return_value = mock_resp
            result = _check_ollama("http://localhost:11434")
            assert result["status"] == "UP"
            assert result["model_count"] == 1

    def test_ollama_down(self):
        with patch("ollamadev_mcp_server.health.requests") as mock_requests:
            mock_requests.get.side_effect = Exception("Connection refused")
            result = _check_ollama("http://localhost:11434")
            assert result["status"] == "DOWN"
            assert "Cannot connect" in result["detail"]

    def test_ollama_degraded(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with patch("ollamadev_mcp_server.health.requests") as mock_requests:
            mock_requests.get.return_value = mock_resp
            result = _check_ollama("http://localhost:11434")
            assert result["status"] == "DEGRADED"


class TestCheckSettings:
    def test_settings_accessible(self, tmp_path, monkeypatch):
        settings_file = tmp_path / "store" / "server_settings.json"
        settings_file.parent.mkdir(parents=True)
        monkeypatch.setenv("OLLAMADEV_SETTINGS_FILE", str(settings_file))
        result = _check_settings()
        assert result["status"] == "UP"


class TestGetHealthStatus:
    def test_all_up(self, tmp_path):
        with patch("ollamadev_mcp_server.health._check_ollama") as mock_ollama:
            mock_ollama.return_value = {"status": "UP"}
            with patch("ollamadev_mcp_server.health._check_settings") as mock_settings:
                mock_settings.return_value = {"status": "UP"}
                result = get_health_status(
                    workspace_root=tmp_path,
                    ollama_url="http://localhost:11434",
                    detailed=True,
                )
                assert result["status"] == "UP"
                assert "checks" in result
                assert "uptime_seconds" in result
                assert "timestamp" in result

    def test_one_down_means_down(self, tmp_path):
        with patch("ollamadev_mcp_server.health._check_ollama") as mock_ollama:
            mock_ollama.return_value = {"status": "DOWN", "detail": "fail"}
            with patch("ollamadev_mcp_server.health._check_settings") as mock_settings:
                mock_settings.return_value = {"status": "UP"}
                result = get_health_status(
                    workspace_root=tmp_path,
                    ollama_url="http://localhost:11434",
                )
                assert result["status"] == "DOWN"

    def test_degraded_when_mixed(self, tmp_path):
        with patch("ollamadev_mcp_server.health._check_ollama") as mock_ollama:
            mock_ollama.return_value = {"status": "DEGRADED"}
            with patch("ollamadev_mcp_server.health._check_settings") as mock_settings:
                mock_settings.return_value = {"status": "UP"}
                result = get_health_status(
                    workspace_root=tmp_path,
                    ollama_url="http://localhost:11434",
                )
                assert result["status"] == "DEGRADED"

    def test_not_detailed_omits_checks(self, tmp_path):
        with patch("ollamadev_mcp_server.health._check_ollama") as mock_ollama:
            mock_ollama.return_value = {"status": "UP"}
            with patch("ollamadev_mcp_server.health._check_settings") as mock_settings:
                mock_settings.return_value = {"status": "UP"}
                result = get_health_status(
                    workspace_root=tmp_path,
                    ollama_url="http://localhost:11434",
                    detailed=False,
                )
                assert "checks" not in result

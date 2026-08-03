"""Integration tests for health tools registered via server.py."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from mcp.server import MCPServer


def _make_server(tmp_workspace: Path) -> MCPServer:
    import ollamadev_mcp_server.tools.filesystem as fs_mod
    import ollamadev_mcp_server.constants as const_mod
    from server import _register_health_tools
    fs_mod.WORKSPACE_ROOT = tmp_workspace
    # Patch constants used by _register_health_tools
    original_wr = const_mod.WORKSPACE_ROOT
    original_ou = const_mod.OLLAMA_URL
    const_mod.WORKSPACE_ROOT = tmp_workspace
    const_mod.OLLAMA_URL = "http://localhost:11434"
    mcp = MCPServer("Test Health")
    _register_health_tools(mcp)
    # Restore constants after registration (tools capture via closure)
    const_mod.WORKSPACE_ROOT = original_wr
    const_mod.OLLAMA_URL = original_ou
    return mcp


class TestGetServerHealth:
    def test_returns_json(self, tmp_path):
        mcp = _make_server(tmp_path)
        with patch("ollamadev_mcp_server.health._check_ollama") as mock_ollama:
            mock_ollama.return_value = {"status": "UP"}
            with patch("ollamadev_mcp_server.health._check_settings") as mock_settings:
                mock_settings.return_value = {"status": "UP"}
                result = asyncio.run(mcp.call_tool("get_server_health", {"detailed": True}))
                data = json.loads(result.content[0].text)
                assert "status" in data
                assert "uptime_seconds" in data
                assert "checks" in data

    def test_not_detailed(self, tmp_path):
        mcp = _make_server(tmp_path)
        with patch("ollamadev_mcp_server.health._check_ollama") as mock_ollama:
            mock_ollama.return_value = {"status": "UP"}
            with patch("ollamadev_mcp_server.health._check_settings") as mock_settings:
                mock_settings.return_value = {"status": "UP"}
                result = asyncio.run(mcp.call_tool("get_server_health", {}))
                data = json.loads(result.content[0].text)
                assert "status" in data
                assert "checks" not in data


class TestGetServerDiagnostics:
    def test_returns_json(self, tmp_path):
        mcp = _make_server(tmp_path)
        result = asyncio.run(mcp.call_tool("get_server_diagnostics", {}))
        data = json.loads(result.content[0].text)
        assert "log_level" in data
        assert "timeouts" in data
        assert "workspace_root" in data
        assert "ollama_url" in data
        assert isinstance(data["timeouts"], dict)
        assert len(data["timeouts"]) > 0

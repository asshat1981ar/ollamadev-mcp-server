"""Tests for the sandbox execution tools."""

import asyncio
import json
import tempfile
from pathlib import Path

from mcp.server import MCPServer

from ollamadev_mcp_server.tools import sandbox


def _make_server(tmp_workspace: Path) -> MCPServer:
    """Create a test MCP server with sandbox tools rooted in a temp workspace."""
    import ollamadev_mcp_server.tools.sandbox as sandbox_mod
    sandbox_mod.WORKSPACE_ROOT = tmp_workspace
    mcp = MCPServer("Test Sandbox")
    sandbox.register(mcp)
    return mcp


def test_get_sandbox_status_returns_json():
    with tempfile.TemporaryDirectory() as tmp:
        mcp = _make_server(Path(tmp))
        result = asyncio.run(mcp.call_tool("get_sandbox_status", {}))
        data = json.loads(result.content[0].text)
        assert data["workspace_root"] == tmp
        assert "pytest_available" in data
        assert "gradlew_present" in data


def test_run_pytest_fails_gracefully_when_missing(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        mcp = _make_server(workspace)
        monkeypatch.setenv("PATH", "/nonexistent")
        result = asyncio.run(mcp.call_tool("run_pytest", {"path": tmp}))
        data = json.loads(result.content[0].text)
        assert data["returncode"] == -1
        assert "pytest is not installed" in data["error"]


def test_run_shell_command_echo():
    with tempfile.TemporaryDirectory() as tmp:
        mcp = _make_server(Path(tmp))
        result = asyncio.run(mcp.call_tool("run_shell_command", {"command": "echo hello-from-sandbox"}))
        data = json.loads(result.content[0].text)
        assert data["returncode"] == 0
        assert data["status"] == "PASSED"
        assert "hello-from-sandbox" in data["output"]


def test_run_shell_command_failure():
    with tempfile.TemporaryDirectory() as tmp:
        mcp = _make_server(Path(tmp))
        result = asyncio.run(mcp.call_tool("run_shell_command", {"command": "exit 7"}))
        data = json.loads(result.content[0].text)
        assert data["returncode"] == 7
        assert data["status"] == "FAILED"

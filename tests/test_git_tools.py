"""Tests for the git tools."""

import asyncio
import subprocess
from pathlib import Path

import pytest
from mcp.server import MCPServer

from ollamadev_mcp_server.tools import git_tools


def _make_server(tmp_workspace: Path) -> MCPServer:
    import ollamadev_mcp_server.tools.git_tools as git_mod
    import ollamadev_mcp_server.tools.filesystem as fs_mod
    git_mod.WORKSPACE_ROOT = tmp_workspace
    fs_mod.WORKSPACE_ROOT = tmp_workspace
    mcp = MCPServer("Test Git")
    git_tools.register(mcp)
    return mcp


@pytest.fixture
def git_workspace(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "agent@test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test Agent"], check=True)
    (tmp_path / "README.md").write_text("# Repo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "initial"], check=True)
    return tmp_path


def test_git_log_shows_commit(git_workspace):
    mcp = _make_server(git_workspace)
    result = asyncio.run(mcp.call_tool("git_log", {"limit": 5}))
    assert "initial" in result.content[0].text


def test_git_status_diff_shows_changes(git_workspace):
    (git_workspace / "README.md").write_text("# Repo\nchanged\n", encoding="utf-8")
    mcp = _make_server(git_workspace)
    result = asyncio.run(mcp.call_tool("git_status_diff", {}))
    text = result.content[0].text
    assert "README.md" in text
    assert "changed" in text


def test_git_commit_checkpoint_creates_commit(git_workspace):
    (git_workspace / "notes.md").write_text("hi\n", encoding="utf-8")
    mcp = _make_server(git_workspace)
    result = asyncio.run(mcp.call_tool("git_commit_checkpoint", {"message": "checkpoint"}))
    assert "checkpoint" in result.content[0].text
    log = asyncio.run(mcp.call_tool("git_log", {"limit": 3}))
    assert "checkpoint" in log.content[0].text


def test_git_unavailable_returns_error(monkeypatch, tmp_path):
    mcp = _make_server(tmp_path)
    monkeypatch.setattr(git_tools, "_git_available", lambda: False)
    result = asyncio.run(mcp.call_tool("git_status_diff", {}))
    assert "git command not found" in result.content[0].text
    result = asyncio.run(mcp.call_tool("git_commit_checkpoint", {"message": "x"}))
    assert "git command not found" in result.content[0].text
    result = asyncio.run(mcp.call_tool("git_log", {}))
    assert "git command not found" in result.content[0].text

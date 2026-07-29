"""Tests for the filesystem tools."""

import asyncio
import tempfile
from pathlib import Path

from mcp.server import MCPServer

from ollamadev_mcp_server.tools import filesystem


def _make_server(tmp_workspace: Path) -> MCPServer:
    """Create a test MCP server with filesystem tools rooted in a temp workspace."""
    import ollamadev_mcp_server.tools.filesystem as fs_mod
    fs_mod.WORKSPACE_ROOT = tmp_workspace
    mcp = MCPServer("Test Filesystem")
    filesystem.register(mcp)
    return mcp


def test_write_workspace_file_creates_file_and_parents():
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        mcp = _make_server(workspace)
        result = asyncio.run(mcp.call_tool("write_workspace_file", {
            "path": "store/integration/test_output.md",
            "content": "# Integration Test Output\n\nVerified: write_workspace_file lands on disk.",
        }))
        assert result.content
        assert "Written" in result.content[0].text
        target = workspace / "store/integration/test_output.md"
        assert target.exists()
        assert "Verified: write_workspace_file lands on disk." in target.read_text(encoding="utf-8")


def test_list_workspace_files_includes_written_file():
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        mcp = _make_server(workspace)
        asyncio.run(mcp.call_tool("write_workspace_file", {
            "path": "store/integration/listed_file.py",
            "content": "print('hello from integration test')",
        }))
        result = asyncio.run(mcp.call_tool("list_workspace_files", {"root": "store/integration"}))
        files = result.content[0].text if result.content else ""
        assert "store/integration/listed_file.py" in files

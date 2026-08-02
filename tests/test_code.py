"""Tests for the code-intelligence tools."""

import asyncio
from pathlib import Path

import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ollamadev_mcp_server.tools import code

SAMPLE_KT = """\
package com.example.data

import java.time.Instant

data class Foo(val id: Int)

class Bar {
    fun greet(name: String): String = "hi $name"
}

val topLevel = 1

// TODO(agent): refactor this
// FIXME: urgent
"""


def _make_server(tmp_workspace: Path) -> MCPServer:
    import ollamadev_mcp_server.tools.code as code_mod
    import ollamadev_mcp_server.tools.filesystem as fs_mod
    code_mod.WORKSPACE_ROOT = tmp_workspace
    fs_mod.WORKSPACE_ROOT = tmp_workspace
    mcp = MCPServer("Test Code")
    code.register(mcp)
    return mcp


def test_search_workspace_finds_matches(tmp_path):
    (tmp_path / "Foo.kt").write_text(SAMPLE_KT, encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("search_workspace", {"pattern": "class Bar", "context_lines": 0}))
    text = result.content[0].text
    assert "Foo.kt" in text
    assert "class Bar" in text


def test_search_workspace_no_matches(tmp_path):
    (tmp_path / "Foo.kt").write_text(SAMPLE_KT, encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("search_workspace", {"pattern": "zzzznomatch", "context_lines": 0}))
    assert result.content[0].text == "No matches found."


def test_get_file_outline_extracts_signatures(tmp_path):
    (tmp_path / "Foo.kt").write_text(SAMPLE_KT, encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("get_file_outline", {"path": "Foo.kt"}))
    text = result.content[0].text
    assert "Outline of Foo.kt" in text
    assert "data class Foo" in text
    assert "class Bar" in text
    assert "fun greet" in text
    assert "val topLevel" in text


def test_get_file_outline_missing_raises(tmp_path):
    mcp = _make_server(tmp_path)
    with pytest.raises(ToolError, match="File not found"):
        asyncio.run(mcp.call_tool("get_file_outline", {"path": "missing.kt"}))


def test_find_symbol_finds_class(tmp_path):
    (tmp_path / "Foo.kt").write_text(SAMPLE_KT, encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("find_symbol", {"name": "Bar", "symbol_type": "class"}))
    assert "Foo.kt" in result.content[0].text


def test_find_symbol_invalid_type_raises(tmp_path):
    mcp = _make_server(tmp_path)
    with pytest.raises(ToolError, match="symbol_type"):
        asyncio.run(mcp.call_tool("find_symbol", {"name": "Bar", "symbol_type": "nonsense"}))


def test_get_todos_extracts_markers(tmp_path):
    (tmp_path / "Foo.kt").write_text(SAMPLE_KT, encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("get_todos", {}))
    text = result.content[0].text
    assert "TODO" in text
    assert "FIXME" in text


def test_get_todos_none(tmp_path):
    (tmp_path / "Clean.kt").write_text("package clean\n", encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("get_todos", {}))
    assert "No TODOs found." in result.content[0].text


def test_get_todos_empty_patterns(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("get_todos", {"patterns": []}))
    assert "No markers specified." in result.content[0].text

"""Tests for the agent-memory tools."""

import asyncio
import json
from pathlib import Path

from mcp.server import MCPServer

from ollamadev_mcp_server.tools import memory


def _make_server(tmp_workspace: Path) -> MCPServer:
    import ollamadev_mcp_server.tools.memory as mem_mod
    mem_mod.STORE_DIR = tmp_workspace / "store"
    mem_mod._MEMORY_FILE = tmp_workspace / "store" / "agent_memory.json"
    mcp = MCPServer("Test Memory")
    memory.register(mcp)
    return mcp


def test_store_recall_clear_roundtrip(tmp_path):
    mcp = _make_server(tmp_path)
    stored = asyncio.run(mcp.call_tool("store_memory", {"key": "lesson", "value": "always test"}))
    stored_response = json.loads(stored.content[0].text)
    assert stored_response["success"] is True
    assert "Stored memory 'lesson'" in stored_response["data"]

    recalled = asyncio.run(mcp.call_tool("recall_memory", {"key": "lesson"}))
    recalled_response = json.loads(recalled.content[0].text)
    assert recalled_response["success"] is True
    assert recalled_response["data"] == "always test"

    listed = asyncio.run(mcp.call_tool("list_memories", {}))
    listed_response = json.loads(listed.content[0].text)
    assert listed_response["success"] is True
    assert "lesson" in listed_response["data"]

    cleared = asyncio.run(mcp.call_tool("clear_memory", {"key": "lesson"}))
    cleared_response = json.loads(cleared.content[0].text)
    assert cleared_response["success"] is True
    assert "Cleared memory 'lesson'." in cleared_response["data"]

    missing = asyncio.run(mcp.call_tool("recall_memory", {"key": "lesson"}))
    missing_response = json.loads(missing.content[0].text)
    assert missing_response["success"] is True
    assert "Memory not found." in missing_response["data"]


def test_recall_missing(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("recall_memory", {"key": "nope"}))
    response = json.loads(result.content[0].text)
    assert response["success"] is True
    assert "Memory not found." in response["data"]


def test_list_memories_empty(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("list_memories", {}))
    response = json.loads(result.content[0].text)
    assert response["success"] is True
    assert "No memories stored." in response["data"]


def test_corrupt_memory_file_is_tolerated(tmp_path):
    store = tmp_path / "store"
    store.mkdir(parents=True)
    (store / "agent_memory.json").write_text("{broken", encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("list_memories", {}))
    response = json.loads(result.content[0].text)
    assert response["success"] is True
    assert "No memories stored." in response["data"]


def test_memory_persists_to_disk(tmp_path):
    mcp = _make_server(tmp_path)
    asyncio.run(mcp.call_tool("store_memory", {"key": "k", "value": "v"}))
    on_disk = json.loads((tmp_path / "store" / "agent_memory.json").read_text(encoding="utf-8"))
    assert on_disk["k"] == "v"

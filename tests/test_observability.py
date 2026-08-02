"""Tests for the observability / transcript tools."""

import asyncio
import json
from pathlib import Path

from mcp.server import MCPServer

from ollamadev_mcp_server.tools import observability


def _make_server(tmp_workspace: Path) -> MCPServer:
    import ollamadev_mcp_server.tools.observability as obs_mod
    obs_mod.WORKSPACE_ROOT = tmp_workspace
    mcp = MCPServer("Test Observability")
    observability.register(mcp)
    return mcp


def test_transcript_missing(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("get_task_transcript", {"task_id": 42}))
    text = result.content[0].text
    assert "No transcript export found for task 42" in text
    assert "task_transcript_42.json" in text


def test_transcript_json_to_markdown(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    (store / "task_transcript_7.json").write_text(
        json.dumps(
            [
                {"agentName": "Planner", "agentRole": "Architect", "actionType": "THINKING", "content": "step one"},
                {"agentName": "QA", "agentRole": "QA", "actionType": "VERIFICATION", "content": "all good"},
            ]
        ),
        encoding="utf-8",
    )
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("get_task_transcript", {"task_id": 7}))
    text = result.content[0].text
    assert "Task 7 Transcript" in text
    assert "Planner" in text
    assert "step one" in text


def test_transcript_json_passthrough(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    (store / "task_transcript_7.json").write_text('[{"agentName": "QA"}]', encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("get_task_transcript", {"task_id": 7, "format": "json"}))
    data = json.loads(result.content[0].text)
    assert data[0]["agentName"] == "QA"


def test_transcript_invalid_json(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    (store / "task_transcript_3.json").write_text("{oops", encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("get_task_transcript", {"task_id": 3}))
    assert "not valid JSON" in result.content[0].text


def test_transcript_markdown_passthrough(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    (store / "task_transcript_9.md").write_text("# Task 9\n\nnotes", encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("get_task_transcript", {"task_id": 9}))
    assert result.content[0].text == "# Task 9\n\nnotes"

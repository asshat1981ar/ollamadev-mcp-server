"""Tests for the meta / agentic tools."""

import asyncio
import json

import pytest
import requests
from mcp.server import MCPServer

from ollamadev_mcp_server.tools import meta


def _make_server() -> MCPServer:
    mcp = MCPServer("Test Meta")
    meta.register(mcp)
    return mcp


def test_ping_returns_json():
    mcp = _make_server()
    result = asyncio.run(mcp.call_tool("ping", {}))
    response = json.loads(result.content[0].text)
    # New unified response format
    assert response["success"] is True
    assert response["tool"] == "ping"
    assert "duration_ms" in response
    assert response["data"]["name"] == "OllamaDev Toolbox"
    assert "version" in response["data"]
    assert response["data"]["uptime_seconds"] >= 0


def test_describe_tools_all():
    mcp = _make_server()
    result = asyncio.run(mcp.call_tool("describe_tools", {}))
    response = json.loads(result.content[0].text)
    assert response["success"] is True
    text = response["data"]
    assert "list_workspace_files" in text
    assert "run_gradle_tests" in text
    assert "get_server_settings" in text


def test_describe_tools_category_filter():
    mcp = _make_server()
    result = asyncio.run(mcp.call_tool("describe_tools", {"category": "verification"}))
    response = json.loads(result.content[0].text)
    assert response["success"] is True
    text = response["data"]
    assert "run_gradle_tests" in text
    assert "list_workspace_files" not in text


def test_extract_json_strips_fences():
    raw = '```json\n{"tool_name": "ping"}\n```'
    assert meta._extract_json(raw) == {"tool_name": "ping"}


def test_extract_json_grabs_object_from_noise():
    raw = 'here is the result {"tool_name": "ping", "arguments": {}, "reasoning": "r", "confidence": 0.9} ok'
    assert meta._extract_json(raw)["tool_name"] == "ping"


def test_extract_json_rejects_no_object():
    with pytest.raises(ValueError, match="No JSON object"):
        meta._extract_json("no json here")


def test_parse_recommendation_valid():
    parsed = meta._parse_recommendation(
        '{"tool_name": "ping", "arguments": {}, "reasoning": "r", "confidence": 0.8}'
    )
    assert parsed["tool_name"] == "ping"
    assert parsed["confidence"] == 0.8


def test_parse_recommendation_missing_key():
    with pytest.raises(ValueError, match="Missing key"):
        meta._parse_recommendation('{"tool_name": "ping"}')


def test_suggest_next_action_success(monkeypatch):
    mcp = _make_server()
    monkeypatch.setattr(
        meta,
        "_ask_ollama",
        lambda *a, **k: '{"tool_name": "run_gradle_tests", "arguments": {}, "reasoning": "verify", "confidence": 0.9}',
    )
    result = asyncio.run(
        mcp.call_tool(
            "suggest_next_action",
            {"goal": "make tests pass", "phase": "VERIFICATION", "context": "", "model": "test", "provider": "ollama"},
        )
    )
    response = json.loads(result.content[0].text)
    assert response["success"] is True
    data = json.loads(response["data"]) if isinstance(response["data"], str) else response["data"]
    assert data["tool_name"] == "run_gradle_tests"
    assert data["confidence"] == 0.9


def test_suggest_next_action_connection_error(monkeypatch):
    mcp = _make_server()

    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(meta, "_ask_ollama", boom)
    result = asyncio.run(
        mcp.call_tool(
            "suggest_next_action",
            {"goal": "x", "phase": "DESIGN", "context": "", "model": "test", "provider": "ollama"},
        )
    )
    response = json.loads(result.content[0].text)
    assert response["success"] is True
    data = json.loads(response["data"]) if isinstance(response["data"], str) else response["data"]
    assert data["tool_name"] is None
    assert "not reachable" in data["reasoning"]

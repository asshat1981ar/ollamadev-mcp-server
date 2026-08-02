"""Tests for the server-settings tools and persistence helpers."""

import asyncio
import json

import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ollamadev_mcp_server import constants
from ollamadev_mcp_server import persistence
from ollamadev_mcp_server.tools import settings


def _make_server() -> MCPServer:
    mcp = MCPServer("Test Settings")
    settings.register(mcp)
    return mcp


def test_get_server_settings_returns_effective_snapshot(monkeypatch, tmp_path):
    settings_file = tmp_path / "server_settings.json"
    monkeypatch.setattr(settings, "SETTINGS_FILE", settings_file)
    mcp = _make_server()
    result = asyncio.run(mcp.call_tool("get_server_settings", {}))
    data = json.loads(result.content[0].text)
    assert data["settings_file"] == str(settings_file)
    assert data["workspace_root"] == str(constants.WORKSPACE_ROOT)
    assert "ollama_url" in data
    assert "default_cloud_model" in data
    assert "sprint_phases" in data
    assert data["persisted_keys"] == []


def test_update_server_settings_persists_and_masks_secrets(monkeypatch, tmp_path):
    settings_file = tmp_path / "server_settings.json"
    monkeypatch.setattr(settings, "SETTINGS_FILE", settings_file)
    mcp = _make_server()
    result = asyncio.run(
        mcp.call_tool(
            "update_server_settings",
            {"settings": {"ollama_url": "http://localhost:11434", "anthropic_api_key": "sk-secret"}},
        )
    )
    data = json.loads(result.content[0].text)
    assert data["status"] == "saved"
    assert data["settings_file"] == str(settings_file)
    assert data["saved"]["ollama_url"] == "http://localhost:11434"
    assert data["saved"]["anthropic_api_key"] == "***"
    assert "anthropic_api_key" in data["restart_required"]

    # File was written atomically (no .tmp leftovers) and stores the raw secret.
    on_disk = json.loads(settings_file.read_text(encoding="utf-8"))
    assert on_disk["ollama_url"] == "http://localhost:11434"
    assert on_disk["anthropic_api_key"] == "sk-secret"
    assert not settings_file.with_name(settings_file.name + ".tmp").exists()


def test_update_server_settings_rejects_unknown_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "server_settings.json")
    mcp = _make_server()
    with pytest.raises(ToolError, match="Unknown setting keys"):
        asyncio.run(mcp.call_tool("update_server_settings", {"settings": {"bogus": "x"}}))


def test_update_server_settings_rejects_non_string_values(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "server_settings.json")
    mcp = _make_server()
    with pytest.raises(ToolError, match="non-empty string"):
        asyncio.run(mcp.call_tool("update_server_settings", {"settings": {"ollama_url": ""}}))


def test_update_server_settings_merges_not_replaces(monkeypatch, tmp_path):
    settings_file = tmp_path / "server_settings.json"
    monkeypatch.setattr(settings, "SETTINGS_FILE", settings_file)
    mcp = _make_server()
    asyncio.run(mcp.call_tool("update_server_settings", {"settings": {"ollama_url": "http://a:1"}}))
    asyncio.run(mcp.call_tool("update_server_settings", {"settings": {"default_cloud_model": "m"}}))
    on_disk = json.loads(settings_file.read_text(encoding="utf-8"))
    assert on_disk["ollama_url"] == "http://a:1"
    assert on_disk["default_cloud_model"] == "m"


def test_reset_server_settings_removes_file(monkeypatch, tmp_path):
    settings_file = tmp_path / "server_settings.json"
    monkeypatch.setattr(settings, "SETTINGS_FILE", settings_file)
    mcp = _make_server()
    asyncio.run(mcp.call_tool("update_server_settings", {"settings": {"ollama_url": "http://a:1"}}))
    assert settings_file.exists()
    result = asyncio.run(mcp.call_tool("reset_server_settings", {}))
    data = json.loads(result.content[0].text)
    assert data["status"] == "reset"
    assert data["removed_file"] is True
    assert not settings_file.exists()


def test_reset_server_settings_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "no-such.json")
    mcp = _make_server()
    result = asyncio.run(mcp.call_tool("reset_server_settings", {}))
    data = json.loads(result.content[0].text)
    assert data["removed_file"] is False


# --- persistence helpers ---


def test_persistence_roundtrip(tmp_path):
    target = tmp_path / "store" / "server_settings.json"
    persistence.save_persisted_settings({"ollama_url": "http://x:1"}, target)
    assert persistence.load_persisted_settings(target) == {"ollama_url": "http://x:1"}


def test_persistence_load_missing_and_corrupt(tmp_path):
    assert persistence.load_persisted_settings(tmp_path / "nope.json") == {}
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert persistence.load_persisted_settings(corrupt) == {}


def test_persistence_clear(tmp_path):
    target = tmp_path / "s.json"
    persistence.save_persisted_settings({"a": "b"}, target)
    assert persistence.clear_persisted_settings(target) is True
    assert not target.exists()
    assert persistence.clear_persisted_settings(target) is False

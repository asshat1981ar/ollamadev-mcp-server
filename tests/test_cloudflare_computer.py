"""Tests for the Cloudflare Computer tool module (HTTP-surface proxy)."""

import json

import pytest
from mcp.server import MCPServer

from ollamadev_mcp_server.tools import cloudflare_computer as cc


class _Resp:
    def __init__(self, status_code=200, body=b"", text=""):
        self.status_code = status_code
        self.content = body
        self.text = text or body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)


@pytest.fixture(autouse=True)
def _reset_config():
    cc._CONFIG.update(
        {
            "base_url": "http://127.0.0.1:8787",
            "workspace": "compute",
            "timeout": 30,
        }
    )
    yield
    cc._CONFIG.update(
        {
            "base_url": "http://127.0.0.1:8787",
            "workspace": "compute",
            "timeout": 30,
        }
    )


def _register(mcp: MCPServer) -> MCPServer:
    mcp = mcp or MCPServer("Test Cloudflare Computer")
    cc.register(mcp)
    return mcp


def _call(mcp: MCPServer, name: str, args: dict) -> dict:
    result = __import__("asyncio").run(mcp.call_tool(name, args))
    return json.loads(result.content[0].text)


def test_url_building_uses_surface_layout():
    cc._CONFIG["base_url"] = "http://example.com"
    cc._CONFIG["workspace"] = "compute"
    assert cc._file_url("notes/todo.md") == "http://example.com/c/compute/file/workspace/notes/todo.md"
    assert cc._file_url("/workspace/notes/todo.md") == "http://example.com/c/compute/file/workspace/workspace/notes/todo.md"
    assert cc._exec_url() == "http://example.com/c/compute/exec"


def test_status_reports_reachable(monkeypatch):
    monkeypatch.setattr(cc.requests, "get", lambda url, timeout=30: _Resp(200, b"surface index"))
    mcp = _register(None)
    out = _call(mcp, "cf_workspace_status", {})
    assert out["success"]
    assert out["data"]["ok"] is True
    assert out["data"]["reachable"] is True


def test_status_unreachable_returns_helpful_error(monkeypatch):
    def boom(url, timeout=30):
        raise cc.requests.ConnectionError("refused")

    monkeypatch.setattr(cc.requests, "get", boom)
    mcp = _register(None)
    out = _call(mcp, "cf_workspace_status", {})
    assert not out["data"]["ok"]
    assert "CF_COMPUTER_BASE_URL" in out["data"]["error"]


def test_read_file_happy_path(monkeypatch):
    monkeypatch.setattr(cc.requests, "get", lambda url, timeout=30: _Resp(200, b"hello world"))
    mcp = _register(None)
    out = _call(mcp, "cf_read_workspace_file", {"path": "workspace/notes/todo.md"})
    assert out["data"]["ok"] is True
    assert out["data"]["content"] == "hello world"
    assert out["data"]["size"] == 11


def test_read_file_404(monkeypatch):
    monkeypatch.setattr(cc.requests, "get", lambda url, timeout=30: _Resp(404, b"missing"))
    mcp = _register(None)
    out = _call(mcp, "cf_read_workspace_file", {"path": "workspace/nope.md"})
    assert not out["data"]["ok"]
    assert out["data"]["http_status"] == 404


def test_write_file_happy_path(monkeypatch):
    captured = {}

    def put(url, data, timeout=30):
        captured["url"] = url
        captured["data"] = data
        return _Resp(204, b"")

    monkeypatch.setattr(cc.requests, "put", put)
    mcp = _register(None)
    out = _call(mcp, "cf_write_workspace_file", {"path": "workspace/out.txt", "content": "abc"})
    assert out["data"]["ok"] is True
    assert out["data"]["bytes"] == 3
    assert captured["data"] == b"abc"
    assert "file/workspace/workspace/out.txt" in captured["url"]


def test_exec_flattens_runtime_result(monkeypatch):
    payload = {
        "status": "completed",
        "exitCode": 0,
        "stdout": "ok",
        "stderr": "",
        "sync": {"status": "complete", "applied": 0, "skipped": []},
    }
    monkeypatch.setattr(
        cc.requests,
        "post",
        lambda url, **kwargs: _Resp(200, text=json.dumps(payload)),
    )
    mcp = _register(None)
    out = _call(mcp, "cf_exec_workspace", {"command": "pwd", "cwd": "/workspace"})
    assert out["data"]["ok"] is True
    assert out["data"]["exitCode"] == 0
    assert out["data"]["stdout"] == "ok"


def test_git_routes_through_exec(monkeypatch):
    payload = {"status": "completed", "exitCode": 0, "stdout": "main", "stderr": ""}
    seen = {}

    def post(url, **kwargs):
        seen["payload"] = kwargs.get("json")
        return _Resp(200, text=json.dumps(payload))

    monkeypatch.setattr(cc.requests, "post", post)
    mcp = _register(None)
    out = _call(mcp, "cf_git_workspace", {"args": "branch --show-current", "cwd": "/workspace"})
    assert out["data"]["ok"] is True
    assert seen["payload"]["command"] == "git branch --show-current"


def test_unknown_endpoint_returns_not_configured(monkeypatch):
    monkeypatch.setattr(cc.requests, "post", lambda url, json=None, timeout=30: _Resp(500, b"boom"))
    mcp = _register(None)
    out = _call(mcp, "cf_exec_workspace", {"command": "ls"})
    assert not out["data"]["ok"]

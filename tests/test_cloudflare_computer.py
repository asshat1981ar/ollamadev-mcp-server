"""Tests for the hardened Cloudflare Computer tool module."""

import asyncio
import base64
import json

import pytest
from mcp.server import MCPServer

from ollamadev_mcp_server.tools import cloudflare_computer as cc


class _Resp:
    def __init__(self, status_code=200, content=b"", text=None, headers=None):
        self.status_code = status_code
        if text is not None:
            content = text.encode("utf-8")
        self.content = content
        self.headers = headers or {}

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    cc._CONFIG.update(
        {
            "base_url": "http://127.0.0.1:8787",
            "workspace": "compute",
            "timeout": 30,
            "max_retries": 1,
            "max_read_bytes": 2 * 1024 * 1024,
            "max_exec_output_bytes": 256 * 1024,
        }
    )
    cc._BREAKER.reset()
    monkeypatch.setattr(cc.time, "sleep", lambda *_: None)
    yield


def _register() -> MCPServer:
    mcp = MCPServer("Test Cloudflare Computer")
    cc.register(mcp)
    return mcp


def _call(mcp: MCPServer, name: str, args: dict) -> dict:
    result = asyncio.run(mcp.call_tool(name, args))
    return json.loads(result.content[0].text)


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_bad_base_url_scheme_rejected():
    cc._CONFIG["base_url"] = "ftp://nope.com"
    mcp = _register()
    out = _call(mcp, "cf_workspace_status", {})
    assert not out["data"]["ok"]
    assert out["data"]["code"] == "CONFIG_ERROR"


def test_bad_workspace_name_rejected():
    cc._CONFIG["workspace"] = "bad name!"
    mcp = _register()
    out = _call(mcp, "cf_workspace_status", {})
    assert not out["data"]["ok"]
    assert "WORKSPACE" in out["data"]["error"]


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def test_status_reports_reachable(monkeypatch):
    monkeypatch.setattr(cc, "_safe_get", lambda url, timeout=None: _Resp(200, b"surface index"))
    out = _call(_register(), "cf_workspace_status", {})
    assert out["data"]["ok"] is True
    assert out["data"]["reachable"] is True
    assert out["data"]["surface"] == "surface index"
    assert out["data"]["circuit"]["state"] == "closed"


def test_status_unreachable(monkeypatch):
    def fail(url, timeout=None):
        raise cc.requests.ConnectionError("refused")

    monkeypatch.setattr(cc, "_safe_get", fail)
    out = _call(_register(), "cf_workspace_status", {})
    assert not out["data"]["ok"]
    assert out["data"]["code"] == "DEPENDENCY_ERROR"
    assert "CF_COMPUTER_BASE_URL" in out["data"]["error"]


# ---------------------------------------------------------------------------
# Read / write / path
# ---------------------------------------------------------------------------


def test_read_happy_path(monkeypatch):
    monkeypatch.setattr(cc, "_safe_get", lambda url, timeout=None: _Resp(200, b"hello world"))
    out = _call(_register(), "cf_read_workspace_file", {"path": "workspace/notes/todo.md"})
    d = out["data"]
    assert d["ok"] is True
    assert d["content"] == "hello world"
    assert d["size"] == 11
    assert d["truncated"] is False


def test_read_404(monkeypatch):
    monkeypatch.setattr(cc, "_safe_get", lambda url, timeout=None: _Resp(404, b"missing"))
    out = _call(_register(), "cf_read_workspace_file", {"path": "workspace/nope.md"})
    assert not out["data"]["ok"]
    assert out["data"]["code"] == "ENOENT"


def test_read_binary_returns_base64(monkeypatch):
    raw = bytes([0, 1, 2, 255])
    monkeypatch.setattr(cc, "_safe_get", lambda url, timeout=None: _Resp(200, raw))
    out = _call(_register(), "cf_read_workspace_file", {"path": "bin.dat", "binary": True})
    assert out["data"]["encoding"] == "base64"
    assert out["data"]["content"] == base64.b64encode(raw).decode("ascii")


def test_read_truncated(monkeypatch):
    cc._CONFIG["max_read_bytes"] = 5
    monkeypatch.setattr(cc, "_safe_get", lambda url, timeout=None: _Resp(200, b"1234567890"))
    out = _call(_register(), "cf_read_workspace_file", {"path": "big.txt", "binary": True})
    assert out["data"]["truncated"] is True
    assert len(base64.b64decode(out["data"]["content"])) == 5


def test_write_happy_path(monkeypatch):
    captured = {}

    def put(url, body=None, timeout=None):
        captured["body"] = body
        return _Resp(204, b"")

    monkeypatch.setattr(cc, "_safe_put", put)
    out = _call(_register(), "cf_write_workspace_file", {"path": "workspace/out.txt", "content": "abc"})
    assert out["data"]["ok"] is True
    assert out["data"]["bytes"] == 3
    assert captured["body"] == b"abc"


def test_write_requires_exactly_one_content_source(monkeypatch):
    out = _call(_register(), "cf_write_workspace_file", {"path": "x.txt", "content": "a", "content_b64": "Yg=="})
    assert not out["data"]["ok"]
    assert out["data"]["code"] == "VALIDATION_ERROR"


def test_write_accepts_base64(monkeypatch):
    captured = {}

    def put(url, body=None, timeout=None):
        captured["body"] = body
        return _Resp(204, b"")

    monkeypatch.setattr(cc, "_safe_put", put)
    out = _call(_register(), "cf_write_workspace_file", {"path": "bin.dat", "content_b64": "AAEC/w=="})
    assert out["data"]["bytes"] == 4
    assert captured["body"] == bytes([0, 1, 2, 255])


def test_write_audits(monkeypatch):
    calls = {}

    def audit(op, client_id, arguments, result=None, error=None):
        calls["op"] = op
        calls["args"] = arguments

    monkeypatch.setattr(cc, "audit_log", audit)
    monkeypatch.setattr(cc, "_safe_put", lambda url, body=None, timeout=None: _Resp(204, b""))
    _call(_register(), "cf_write_workspace_file", {"path": "a.txt", "content": "hi"})
    assert calls["op"] == "cf_write_workspace_file"
    assert calls["args"]["path"] == "a.txt"


def test_path_traversal_rejected():
    out = _call(_register(), "cf_read_workspace_file", {"path": "../etc/passwd"})
    assert not out["data"]["ok"]
    assert out["data"]["code"] == "VALIDATION_ERROR"


def test_leading_slash_normalized(monkeypatch):
    seen = {}

    def get(url, timeout=None):
        seen["url"] = url
        return _Resp(200, b"x")

    monkeypatch.setattr(cc, "_safe_get", get)
    _call(_register(), "cf_read_workspace_file", {"path": "/workspace/a/b.txt"})
    assert "/a/b.txt" in seen["url"]


# ---------------------------------------------------------------------------
# Exec / git
# ---------------------------------------------------------------------------


def test_exec_flattens_result(monkeypatch):
    payload = {"status": "completed", "exitCode": 0, "stdout": "ok", "stderr": "",
               "pushed": 0, "pulled": 0, "sync": {"status": "complete", "applied": 0, "skipped": []}}
    monkeypatch.setattr(cc, "_safe_post", lambda url, json_body=None, timeout=None: _Resp(200, text=json.dumps(payload)))
    out = _call(_register(), "cf_exec_workspace", {"command": "pwd", "cwd": "/workspace"})
    d = out["data"]
    assert d["ok"] is True
    assert d["exitCode"] == 0
    assert d["stdout"] == "ok"
    assert d["pushed"] == 0


def test_exec_argv_quotes_safely(monkeypatch):
    payload = {"status": "completed", "exitCode": 0, "stdout": "", "stderr": ""}
    seen = {}
    monkeypatch.setattr(
        cc, "_safe_post",
        lambda url, json_body=None, timeout=None: (seen.update(payload=json_body) or _Resp(200, text=json.dumps(payload))),
    )
    _call(_register(), "cf_exec_workspace", {"argv": ["echo", "$BAD && rm -rf"]})
    assert seen["payload"]["command"] == "echo '$BAD && rm -rf'"


def test_exec_requires_command_or_argv():
    out = _call(_register(), "cf_exec_workspace", {})
    assert not out["data"]["ok"]
    assert out["data"]["code"] == "VALIDATION_ERROR"


def test_exec_caps_output(monkeypatch):
    cc._CONFIG["max_exec_output_bytes"] = 8
    payload = {"status": "completed", "exitCode": 0, "stdout": "x" * 100, "stderr": ""}
    monkeypatch.setattr(cc, "_safe_post", lambda url, json_body=None, timeout=None: _Resp(200, text=json.dumps(payload)))
    out = _call(_register(), "cf_exec_workspace", {"command": "yes"})
    assert out["data"]["stdout_truncated"] is True
    assert len(out["data"]["stdout"]) == 8


def test_git_dispatches_supported_subcommand(monkeypatch):
    payload = {"status": "completed", "exitCode": 0, "stdout": "main", "stderr": ""}
    seen = {}
    monkeypatch.setattr(
        cc, "_safe_post",
        lambda url, json_body=None, timeout=None: (seen.update(payload=json_body) or _Resp(200, text=json.dumps(payload))),
    )
    out = _call(_register(), "cf_git_workspace", {"args": "branch --show-current"})
    assert out["data"]["ok"] is True
    assert seen["payload"]["command"] == "git branch --show-current"


def test_git_unsupported_subcommand_rejected():
    out = _call(_register(), "cf_git_workspace", {"args": "filter-branch --all"})
    assert not out["data"]["ok"]
    assert out["data"]["code"] == "VALIDATION_ERROR"


def test_git_shell_injection_rejected():
    for evil in ("status; rm -rf /", "push origin main && whoami", "log | head"):
        out = _call(_register(), "cf_git_workspace", {"args": evil})
        assert not out["data"]["ok"], f"should reject {evil!r}"
        assert out["data"]["code"] == "VALIDATION_ERROR"


def test_git_mutating_subcommand_audited(monkeypatch):
    calls = {}
    monkeypatch.setattr(cc, "audit_log", lambda op, cid, args, result=None, error=None: calls.update(op=op, args=args))
    payload = {"status": "completed", "exitCode": 0, "stdout": "ok", "stderr": ""}
    monkeypatch.setattr(cc, "_safe_post", lambda url, json_body=None, timeout=None: _Resp(200, text=json.dumps(payload)))
    _call(_register(), "cf_git_workspace", {"args": "commit -m x"})
    assert calls["op"] == "cf_git_workspace"


# ---------------------------------------------------------------------------
# Retry / circuit breaker
# ---------------------------------------------------------------------------


def test_retries_on_5xx(monkeypatch):
    cc._CONFIG["max_retries"] = 3
    calls = {"n": 0}

    def flaky(url, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            return _Resp(503, b"unavailable")
        return _Resp(200, b"ok")

    monkeypatch.setattr(cc, "_safe_get", flaky)
    out = _call(_register(), "cf_workspace_status", {})
    assert out["data"]["ok"] is True
    assert calls["n"] == 3


def test_circuit_breaker_open_returns_error(monkeypatch):
    # Trip the breaker by making the endpoint unreachable (transport errors),
    # then assert a subsequent call is rejected without touching the transport.
    def dead(url, timeout=None):
        raise cc.requests.ConnectionError("refused")

    monkeypatch.setattr(cc, "_safe_get", dead)
    for _ in range(cc._BREAKER.failure_threshold):
        _call(_register(), "cf_workspace_status", {})

    def boom(url, timeout=None):
        raise AssertionError("should not reach transport while circuit is open")

    monkeypatch.setattr(cc, "_safe_get", boom)
    out = _call(_register(), "cf_workspace_status", {})
    assert not out["data"]["ok"]
    assert out["data"]["code"] == "DEPENDENCY_ERROR"
    assert "Circuit breaker" in out["data"]["error"]

"""Tests for the patch / diff tools."""

import asyncio
import types
from pathlib import Path

import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ollamadev_mcp_server.tools import patch

UNIFIED_PATCH = """\
--- a/app/src/main/java/com/example/Foo.kt
+++ b/app/src/main/java/com/example/Foo.kt
@@ -1,4 +1,5 @@
 package com.example
+
 class Foo
-// old comment
+// new comment
 class Bar
"""


def _make_server(tmp_workspace: Path) -> MCPServer:
    import ollamadev_mcp_server.tools.patch as patch_mod
    import ollamadev_mcp_server.tools.filesystem as fs_mod
    patch_mod.WORKSPACE_ROOT = tmp_workspace
    fs_mod.WORKSPACE_ROOT = tmp_workspace
    mcp = MCPServer("Test Patch")
    patch.register(mcp)
    return mcp


def _disable_system_patch(monkeypatch):
    """Force the pure-Python hunk applier by hiding the system `patch` binary."""
    real_run = patch.subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if list(cmd) == ["which", "patch"]:
            return types.SimpleNamespace(returncode=1, stdout="", stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(patch.subprocess, "run", fake_run)


def test_parse_patch_parses_hunks():
    hunks = patch._parse_patch(UNIFIED_PATCH)
    assert len(hunks) == 1
    hunk = hunks[0]
    assert hunk.start_line == 0
    assert hunk.old_lines == ["package com.example", "class Foo", "// old comment", "class Bar"]
    assert hunk.new_lines == ["package com.example", "", "class Foo", "// new comment", "class Bar"]


def test_apply_file_patch_manual_path(tmp_path, monkeypatch):
    _disable_system_patch(monkeypatch)
    target = tmp_path / "app/src/main/java/com/example/Foo.kt"
    target.parent.mkdir(parents=True)
    target.write_text("package com.example\nclass Foo\n// old comment\nclass Bar\n", encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(
        mcp.call_tool(
            "apply_file_patch",
            {"path": "app/src/main/java/com/example/Foo.kt", "patch": UNIFIED_PATCH},
        )
    )
    assert "1 hunk(s)" in result.content[0].text
    assert target.read_text(encoding="utf-8") == "package com.example\n\nclass Foo\n// new comment\nclass Bar\n"


def test_apply_file_patch_reverse(tmp_path, monkeypatch):
    _disable_system_patch(monkeypatch)
    target = tmp_path / "Foo.kt"
    target.write_text("package com.example\n\nclass Foo\n// new comment\nclass Bar\n", encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(
        mcp.call_tool("apply_file_patch", {"path": "Foo.kt", "patch": UNIFIED_PATCH, "reverse": True})
    )
    assert "1 hunk(s)" in result.content[0].text
    assert target.read_text(encoding="utf-8") == "package com.example\nclass Foo\n// old comment\nclass Bar\n"


def test_apply_file_patch_context_mismatch(tmp_path, monkeypatch):
    _disable_system_patch(monkeypatch)
    target = tmp_path / "Foo.kt"
    target.write_text("package com.example\nclass Foo\n// different\nclass Bar\n", encoding="utf-8")
    mcp = _make_server(tmp_path)
    with pytest.raises(ToolError, match="does not match"):
        asyncio.run(mcp.call_tool("apply_file_patch", {"path": "Foo.kt", "patch": UNIFIED_PATCH}))


def test_apply_file_patch_missing_file(tmp_path, monkeypatch):
    _disable_system_patch(monkeypatch)
    mcp = _make_server(tmp_path)
    with pytest.raises(ToolError, match="File not found"):
        asyncio.run(mcp.call_tool("apply_file_patch", {"path": "nope.kt", "patch": UNIFIED_PATCH}))

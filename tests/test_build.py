"""Tests for the build / verification tools."""

import asyncio
import json
from pathlib import Path

from mcp.server import MCPServer

from ollamadev_mcp_server.tools import build


def _make_server(tmp_workspace: Path) -> MCPServer:
    import ollamadev_mcp_server.tools.build as build_mod
    build_mod.WORKSPACE_ROOT = tmp_workspace
    mcp = MCPServer("Test Build")
    build.register(mcp)
    return mcp


def test_parse_test_results_counts():
    mcp = MCPServer("Test Build")
    build.register(mcp)
    output = "123 tests completed, 5 failed\nFAILED: com.example.FooTest.bar\n"
    result = asyncio.run(mcp.call_tool("parse_test_results", {"gradle_output": output}))
    data = json.loads(result.content[0].text)
    assert data["total"] == 123
    assert data["failed"] == 5
    assert data["passed"] == 118
    assert any("FooTest.bar" in line for line in data["unresolved"])
    assert data["summary"] == "118/123 tests passed, 5 failed"


def test_parse_test_results_build_successful_fallback():
    mcp = MCPServer("Test Build")
    build.register(mcp)
    result = asyncio.run(mcp.call_tool("parse_test_results", {"gradle_output": "BUILD SUCCESSFUL"}))
    data = json.loads(result.content[0].text)
    assert data["total"] == 1
    assert data["failed"] == 0
    assert data["passed"] == 1


def test_parse_test_results_build_failed_fallback():
    mcp = MCPServer("Test Build")
    build.register(mcp)
    result = asyncio.run(mcp.call_tool("parse_test_results", {"gradle_output": "BUILD FAILED"}))
    data = json.loads(result.content[0].text)
    assert data["failed"] == 1
    assert data["passed"] == 0


def test_parse_test_results_empty():
    mcp = MCPServer("Test Build")
    build.register(mcp)
    result = asyncio.run(mcp.call_tool("parse_test_results", {"gradle_output": ""}))
    data = json.loads(result.content[0].text)
    assert data["total"] == 0
    assert data["failed"] == 0


def test_run_gradle_tests_missing_gradlew(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("run_gradle_tests", {}))
    assert "gradlew not found" in result.content[0].text


def test_run_gradle_build_missing_gradlew(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("run_gradle_build", {}))
    assert "gradlew not found" in result.content[0].text


def test_run_lint_missing_gradlew(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("run_lint", {}))
    assert "gradlew not found" in result.content[0].text


def test_get_build_config_reads_files(tmp_path):
    (tmp_path / "gradle").mkdir(parents=True)
    (tmp_path / "gradle" / "libs.versions.toml").write_text('[versions]\nagp = "9.1.1"\n', encoding="utf-8")
    (tmp_path / "build.gradle.kts").write_text("plugins {}\n", encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "build.gradle.kts").write_text("android {}\n", encoding="utf-8")
    (tmp_path / "settings.gradle.kts").write_text('rootProject.name = "x"\n', encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("get_build_config", {}))
    text = result.content[0].text
    assert "libs.versions.toml" in text
    assert 'agp = "9.1.1"' in text
    assert "android {}" in text


def test_get_build_config_missing_files(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("get_build_config", {}))
    assert "not found" in result.content[0].text

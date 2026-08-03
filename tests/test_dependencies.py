"""Tests for the Gradle dependency tools."""

import asyncio
import json
from pathlib import Path

import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ollamadev_mcp_server.tools import dependencies


def _make_server(tmp_workspace: Path) -> MCPServer:
    import ollamadev_mcp_server.tools.dependencies as dep_mod
    import ollamadev_mcp_server.tools.filesystem as fs_mod
    dep_mod.WORKSPACE_ROOT = tmp_workspace
    fs_mod.WORKSPACE_ROOT = tmp_workspace
    mcp = MCPServer("Test Dependencies")
    dependencies.register(mcp)
    return mcp


def _seed_project(tmp_workspace: Path) -> None:
    (tmp_workspace / "gradle").mkdir(parents=True)
    (tmp_workspace / "gradle" / "libs.versions.toml").write_text(
        '[versions]\nagp = "9.1.1"\n\n[libraries]\n', encoding="utf-8"
    )
    (tmp_workspace / "app").mkdir()
    (tmp_workspace / "app" / "build.gradle.kts").write_text(
        'plugins {}\n\ndependencies {\n  implementation("androidx.core:core-ktx:1.13.1")\n}\n',
        encoding="utf-8",
    )


def test_to_camel_alias():
    assert dependencies._to_camel_alias("retrofit") == "retrofit"
    assert dependencies._to_camel_alias("ok-http") == "okHttp"
    assert dependencies._to_camel_alias("androidx.core") == "androidxCore"


def test_to_kebab_key():
    assert dependencies._to_kebab_key("ok_http") == "ok-http"
    assert dependencies._to_kebab_key("androidx.core") == "androidx-core"


def test_add_version_to_catalog():
    text = '[versions]\nagp = "1"\n\n[libraries]\n'
    out = dependencies._add_version_to_catalog(text, "retrofit", "2.11.0")
    assert 'retrofit = "2.11.0"' in out
    assert out.index("retrofit") < out.index("[libraries]")


def test_add_library_to_catalog():
    text = "[versions]\n\n[libraries]\n"
    out = dependencies._add_library_to_catalog(text, "retrofit", "com.squareup.retrofit2", "retrofit", "retrofit")
    assert 'retrofit = { group = "com.squareup.retrofit2", name = "retrofit", version.ref = "retrofit" }' in out


def test_add_dependency_to_build_gradle():
    text = 'plugins {}\n\ndependencies {\n  implementation("androidx.core:core-ktx:1.13.1")\n}\n'
    out = dependencies._add_dependency_to_build_gradle(text, "implementation", "libs.retrofit")
    assert "implementation(libs.retrofit)" in out
    assert out.index("implementation(libs.retrofit)") < out.index('implementation("androidx.core')


def test_add_gradle_dependency_catalog_mode(tmp_path):
    _seed_project(tmp_path)
    mcp = _make_server(tmp_path)
    result = asyncio.run(
        mcp.call_tool(
            "add_gradle_dependency",
            {
                "alias": "retrofit",
                "group": "com.squareup.retrofit2",
                "name": "retrofit",
                "version": "2.11.0",
            },
        )
    )
    assert "libs.versions.toml" in result.content[0].text
    catalog = (tmp_path / "gradle" / "libs.versions.toml").read_text(encoding="utf-8")
    assert 'retrofit = "2.11.0"' in catalog
    assert 'version.ref = "retrofit"' in catalog
    gradle = (tmp_path / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert "implementation(libs.retrofit)" in gradle


def test_add_gradle_dependency_inline_mode(tmp_path):
    _seed_project(tmp_path)
    mcp = _make_server(tmp_path)
    asyncio.run(
        mcp.call_tool(
            "add_gradle_dependency",
            {
                "alias": "gson",
                "group": "com.google.code.gson",
                "name": "gson",
                "version": "2.10.1",
                "add_to_catalog": False,
            },
        )
    )
    gradle = (tmp_path / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert 'implementation("com.google.code.gson:gson:2.10.1")' in gradle


def test_add_gradle_dependency_missing_module(tmp_path):
    _seed_project(tmp_path)
    mcp = _make_server(tmp_path)
    result = asyncio.run(
        mcp.call_tool(
            "add_gradle_dependency",
            {"alias": "x", "group": "g", "name": "n", "version": "1.0", "module": "lib"},
        )
    )
    response = json.loads(result.content[0].text)
    assert response["success"] is False
    assert "Module build file not found" in response["error"]["message"]

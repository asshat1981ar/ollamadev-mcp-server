"""Tests for the sprint workflow tools."""

import asyncio
import json
from pathlib import Path

import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ollamadev_mcp_server.tools import sprint


def _make_server(tmp_workspace: Path) -> MCPServer:
    import ollamadev_mcp_server.tools.sprint as sprint_mod
    import ollamadev_mcp_server.tools.filesystem as fs_mod
    sprint_mod.WORKSPACE_ROOT = tmp_workspace
    fs_mod.WORKSPACE_ROOT = tmp_workspace
    mcp = MCPServer("Test Sprint")
    sprint.register(mcp)
    return mcp


def _seed_backlog(tmp_workspace: Path) -> Path:
    backlog = tmp_workspace / "agent-os" / "backlog.md"
    backlog.parent.mkdir(parents=True, exist_ok=True)
    backlog.write_text("# Backlog\n\n## Tier 1 — Done\n", encoding="utf-8")
    return backlog


def test_create_sprint_task_appends(tmp_path):
    backlog = _seed_backlog(tmp_path)
    mcp = _make_server(tmp_path)
    result = asyncio.run(
        mcp.call_tool(
            "create_sprint_task",
            {"title": "Fix auth timeout", "description": "Increase timeout.", "tier": "4", "priority": "high"},
        )
    )
    assert "Tier 4 — Fix auth timeout" in result.content[0].text
    content = backlog.read_text(encoding="utf-8")
    assert "### Tier 4 — Fix auth timeout" in content
    assert "**Priority:** high" in content


def test_create_sprint_task_rejects_bad_tier(tmp_path):
    _seed_backlog(tmp_path)
    mcp = _make_server(tmp_path)
    with pytest.raises(ToolError, match="Invalid tier"):
        asyncio.run(mcp.call_tool("create_sprint_task", {"title": "x", "description": "y", "tier": "abc"}))


def test_create_sprint_task_rejects_bad_priority(tmp_path):
    _seed_backlog(tmp_path)
    mcp = _make_server(tmp_path)
    with pytest.raises(ToolError, match="Invalid priority"):
        asyncio.run(
            mcp.call_tool("create_sprint_task", {"title": "x", "description": "y", "priority": "urgent"})
        )


def test_create_sprint_task_missing_backlog(tmp_path):
    mcp = _make_server(tmp_path)
    with pytest.raises(ToolError, match="Backlog not found"):
        asyncio.run(mcp.call_tool("create_sprint_task", {"title": "x", "description": "y"}))


def test_list_phase_artifacts(tmp_path):
    (tmp_path / "sprint-1-discovery.md").write_text("discovery notes", encoding="utf-8")
    (tmp_path / "sprint-1-verification.md").write_text("verification notes", encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("list_phase_artifacts", {"cycle_id": 1}))
    text = result.content[0].text
    assert "discovery" in text
    assert "verification" in text


def test_list_phase_artifacts_empty(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("list_phase_artifacts", {"cycle_id": 99}))
    assert "No artifacts found for cycle 99." in result.content[0].text


def test_read_phase_artifact(tmp_path):
    (tmp_path / "sprint-1-design.md").write_text("design notes", encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("read_phase_artifact", {"cycle_id": 1, "phase": "design"}))
    assert result.content[0].text == "design notes"


def test_read_phase_artifact_missing(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("read_phase_artifact", {"cycle_id": 1, "phase": "design"}))
    assert "not found" in result.content[0].text


def test_update_phase_artifact_writes(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(
        mcp.call_tool(
            "update_phase_artifact",
            {"cycle_id": 1, "phase": "retrospective", "content": "retro notes"},
        )
    )
    assert "Updated sprint-1-retrospective.md" in result.content[0].text
    assert (tmp_path / "sprint-1-retrospective.md").read_text(encoding="utf-8") == "retro notes"


def test_evaluate_sprint_outcome_no_artifact(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("evaluate_sprint_outcome", {"cycle_id": 1, "phase": "verification"}))
    data = json.loads(result.content[0].text)
    assert data["goalMet"] is False
    assert data["reqCount"] == 0
    assert data["recommendedNextTool"] == "read_phase_artifact"


def test_evaluate_sprint_outcome_counts(tmp_path):
    (tmp_path / "sprint-1-verification.md").write_text(
        "REQ-1 PASS\nREQ-2 FAIL\n[UNRESOLVED] blocker\n", encoding="utf-8"
    )
    mcp = _make_server(tmp_path)
    result = asyncio.run(
        mcp.call_tool(
            "evaluate_sprint_outcome",
            {"cycle_id": 1, "phase": "verification", "goal": "shipping quality"},
        )
    )
    data = json.loads(result.content[0].text)
    assert data["reqCount"] == 2
    assert data["passedCount"] == 1
    assert data["failedCount"] == 1
    assert data["unresolvedCount"] == 1
    assert data["goalMet"] is False
    assert data["recommendedNextTool"] == "run_gradle_tests"

"""Tests for the sprint workflow tools."""

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Callable, NamedTuple

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
    result = asyncio.run(mcp.call_tool("create_sprint_task", {"title": "x", "description": "y", "tier": "abc"}))
    response = json.loads(result.content[0].text)
    assert response["success"] is False
    assert "Invalid tier" in response["error"]["message"]


def test_create_sprint_task_rejects_bad_priority(tmp_path):
    _seed_backlog(tmp_path)
    mcp = _make_server(tmp_path)
    result = asyncio.run(
        mcp.call_tool("create_sprint_task", {"title": "x", "description": "y", "priority": "urgent"})
    )
    response = json.loads(result.content[0].text)
    assert response["success"] is False
    assert "Invalid priority" in response["error"]["message"]


def test_create_sprint_task_missing_backlog(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("create_sprint_task", {"title": "x", "description": "y"}))
    response = json.loads(result.content[0].text)
    assert response["success"] is False
    assert "Backlog not found" in response["error"]["message"]


def test_list_phase_artifacts(tmp_path):
    (tmp_path / "sprint-1-discovery.md").write_text("discovery notes", encoding="utf-8")
    (tmp_path / "sprint-1-verification.md").write_text("verification notes", encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("list_phase_artifacts", {"cycle_id": 1}))
    response = json.loads(result.content[0].text)
    assert response["success"] is True
    text = response["data"]
    assert "discovery" in text
    assert "verification" in text


def test_list_phase_artifacts_empty(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("list_phase_artifacts", {"cycle_id": 99}))
    response = json.loads(result.content[0].text)
    assert response["success"] is True
    assert "No artifacts found for cycle 99." in response["data"]


def test_read_phase_artifact(tmp_path):
    (tmp_path / "sprint-1-design.md").write_text("design notes", encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("read_phase_artifact", {"cycle_id": 1, "phase": "design"}))
    response = json.loads(result.content[0].text)
    assert response["success"] is True
    assert response["data"] == "design notes"


def test_read_phase_artifact_missing(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("read_phase_artifact", {"cycle_id": 1, "phase": "design"}))
    response = json.loads(result.content[0].text)
    assert response["success"] is True
    assert "not found" in response["data"]


def test_update_phase_artifact_writes(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(
        mcp.call_tool(
            "update_phase_artifact",
            {"cycle_id": 1, "phase": "retrospective", "content": "retro notes"},
        )
    )
    response = json.loads(result.content[0].text)
    assert response["success"] is True
    assert "Updated sprint-1-retrospective.md" in response["data"]
    assert (tmp_path / "sprint-1-retrospective.md").read_text(encoding="utf-8") == "retro notes"


def test_evaluate_sprint_outcome_no_artifact(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("evaluate_sprint_outcome", {"cycle_id": 1, "phase": "verification"}))
    response = json.loads(result.content[0].text)
    assert response["success"] is True
    data = response["data"]
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
    response = json.loads(result.content[0].text)
    assert response["success"] is True
    data = response["data"]
    assert data["reqCount"] == 2
    assert data["passedCount"] == 1
    assert data["failedCount"] == 1
    assert data["unresolvedCount"] == 1
    assert data["goalMet"] is False
    assert data["recommendedNextTool"] == "run_gradle_tests"


class _FakeTextContent(NamedTuple):
    text: str


class _FakeToolResult:
    def __init__(self, text: str):
        self.content = [_FakeTextContent(text=text)]


class FakeMCPServer:
    """Lightweight MCPServer stand-in for testing the autonomous sprint loop."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.tools: dict[str, Any] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def tool(self) -> Callable[[Callable], Callable]:
        def decorator(fn: Callable) -> Callable:
            self.tools[fn.__name__] = fn
            return fn
        return decorator

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> _FakeToolResult:
        self.calls.append((name, arguments))
        if name == "suggest_next_action":
            return _deterministic_recommendation(arguments.get("phase", "").lower())
        if name == "create_sprint_task":
            backlog = self.workspace_root / "agent-os" / "backlog.md"
            backlog.parent.mkdir(parents=True, exist_ok=True)
            backlog.write_text("# Backlog\n", encoding="utf-8")
            fn = self.tools.get(name)
            if fn:
                return _FakeToolResult(fn(**arguments))
            return _FakeToolResult("Created task")
        if name == "update_phase_artifact":
            path = self.workspace_root / f"sprint-{arguments['cycle_id']}-{arguments['phase'].lower()}.md"
            path.write_text(arguments["content"], encoding="utf-8")
            return _FakeToolResult(f"Updated {path.name}")
        if name == "evaluate_sprint_outcome":
            artifact = self.workspace_root / f"sprint-{arguments['cycle_id']}-{arguments['phase'].lower()}.md"
            text = artifact.read_text(encoding="utf-8") if artifact.exists() else ""
            req_count = len(re.findall(r"REQ-\d+", text))
            goal_met = req_count > 0 and "FAIL" not in text.upper() and "[UNRESOLVED" not in text.upper()
            return _FakeToolResult(
                json.dumps({
                    "goalMet": goal_met,
                    "reqCount": req_count,
                    "passedCount": req_count,
                    "failedCount": 0,
                    "unresolvedCount": 0,
                    "gaps": [] if goal_met else ["No requirements satisfied."],
                    "recommendedNextTool": "create_sprint_task",
                })
            )
        fn = self.tools.get(name)
        if fn is None:
            raise ToolError(f"Unknown tool: {name}")
        maybe_coro = fn(**arguments)
        if asyncio.iscoroutine(maybe_coro):
            maybe_coro = await maybe_coro
        return _FakeToolResult(maybe_coro)


def _deterministic_recommendation(phase: str) -> _FakeToolResult:
    mapping = {
        "discovery": "list_workspace_files",
        "design": "get_file_outline",
        "implementation": "read_workspace_file",
        "verification": "run_gradle_build",
        "integration": "git_status_diff",
        "retrospective": "git_log",
    }
    return _FakeToolResult(
        json.dumps({
            "tool_name": mapping.get(phase, "list_workspace_files"),
            "arguments": {},
            "reasoning": "deterministic test recommendation",
            "confidence": 0.9,
        })
    )


def _make_autonomous_server(tmp_path: Path) -> FakeMCPServer:
    import ollamadev_mcp_server.tools.sprint as sprint_mod
    sprint_mod.WORKSPACE_ROOT = tmp_path
    mcp = FakeMCPServer(tmp_path)
    sprint.register(mcp)
    return mcp


def test_run_autonomous_sprint_creates_artifacts_and_tasks(tmp_path):
    _seed_backlog(tmp_path)
    mcp = _make_autonomous_server(tmp_path)
    result = asyncio.run(
        mcp.call_tool("run_autonomous_sprint", {"goal": "Explore the codebase", "model": "llama3"})
    )
    response = json.loads(result.content[0].text)
    assert response["success"] is True
    data = response["data"]
    assert data["cycle_id"] == 1
    assert len(data["phase_results"]) == 6
    assert all(pr["actions"] for pr in data["phase_results"])
    update_calls = [c for c in mcp.calls if c[0] == "update_phase_artifact"]
    assert len(update_calls) == 6
    eval_calls = [c for c in mcp.calls if c[0] == "evaluate_sprint_outcome"]
    assert len(eval_calls) == 6


def test_run_autonomous_sprint_blocks_destructive_tools(tmp_path):
    _seed_backlog(tmp_path)
    mcp = _make_autonomous_server(tmp_path)

    original = _deterministic_recommendation
    def blocked_recommendation(phase: str) -> _FakeToolResult:
        return _FakeToolResult(
            json.dumps({
                "tool_name": "delete_workspace_file",
                "arguments": {"path": "app/src/main/java/com/example/MainActivity.kt"},
                "reasoning": "should be blocked",
                "confidence": 0.9,
            })
        )

    import sys
    test_module = sys.modules[__name__]
    test_module._deterministic_recommendation = blocked_recommendation  # type: ignore[attr-defined]
    try:
        result = asyncio.run(
            mcp.call_tool("run_autonomous_sprint", {"goal": "Try destructive action", "model": "llama3"})
        )
        response = json.loads(result.content[0].text)
        assert response["success"] is True
        data = response["data"]
        assert data["cycle_id"] == 1
        blocked_actions = [
            a for pr in data["phase_results"] for a in pr["actions"] if a.get("blocked")
        ]
        assert any(a["tool_name"] == "delete_workspace_file" for a in blocked_actions)
        dispatch_calls = [c for c in mcp.calls if c[0] == "delete_workspace_file"]
        assert not dispatch_calls
    finally:
        test_module._deterministic_recommendation = original  # type: ignore[attr-defined]


def test_run_autonomous_sprint_handles_suggest_failure(tmp_path):
    _seed_backlog(tmp_path)
    mcp = _make_autonomous_server(tmp_path)

    class FailingSuggestServer(FakeMCPServer):
        async def call_tool(self, name: str, arguments: dict[str, Any]) -> _FakeToolResult:
            if name == "suggest_next_action":
                return _FakeToolResult(json.dumps({"tool_name": None, "confidence": 0.0}))
            return await super().call_tool(name, arguments)

    failing = FailingSuggestServer(tmp_path)
    sprint_mod = __import__("ollamadev_mcp_server.tools.sprint", fromlist=["sprint"])
    sprint_mod.WORKSPACE_ROOT = tmp_path
    sprint.register(failing)
    result = asyncio.run(
        failing.call_tool("run_autonomous_sprint", {"goal": "No suggestions", "model": "llama3"})
    )
    response = json.loads(result.content[0].text)
    assert response["success"] is True
    data = response["data"]
    assert data["cycle_id"] == 1
    assert len(data["phase_results"]) == 6
    assert all(not pr["actions"] for pr in data["phase_results"])
    assert all(not pr["evaluation"].get("goalMet", False) for pr in data["phase_results"])

"""Sprint workflow tools for managing OllamaDev artifacts and backlog."""

import json
import re
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from ollamadev_mcp_server.constants import SPRINT_PHASES, WORKSPACE_ROOT
from ollamadev_mcp_server.tool_decorator import tool_runtime
from ollamadev_mcp_server.tool_runtime import ToolContext
from ollamadev_mcp_server.tools.filesystem import _safe_path

_BACKLOG_PATH = "agent-os/backlog.md"

# Tools the autonomous sprint loop is not allowed to dispatch to. This prevents
# self-recursion, no-op meta calls, and destructive actions that should remain
# under explicit human approval (data deletion, arbitrary shell, settings reset).
_AUTONOMOUS_BLOCKED_TOOLS: frozenset[str] = frozenset({
    "run_autonomous_sprint",
    "suggest_next_action",
    "describe_tools",
    "ping",
    "delete_workspace_file",
    "run_shell_command",
    "git_commit_checkpoint",
    "reset_server_settings",
    "update_server_settings",
})

_MAX_CONTEXT_CHARS = 3_000


def _artifact_path(cycle_id: int, phase: str) -> Path:
    return WORKSPACE_ROOT / f"sprint-{cycle_id}-{phase.lower()}.md"


def _derive_cycle_id() -> int:
    """Return the next free cycle id based on existing sprint artifacts."""
    max_id = 0
    for path in WORKSPACE_ROOT.glob("sprint-*-discovery.md"):
        try:
            cid = int(path.stem.split("-")[1])
        except (IndexError, ValueError):
            continue
        if cid > max_id:
            max_id = cid
    return max_id + 1


def _extract_result_text(result: Any) -> str:
    """Best-effort extraction of text from an MCP tool result object."""
    if isinstance(result, str):
        return result
    if hasattr(result, "content") and result.content:
        first = result.content[0]
        if isinstance(first, str):
            return first
        if hasattr(first, "text"):
            return first.text
    return str(result)


def _truncate_context(context: str, max_chars: int = _MAX_CONTEXT_CHARS) -> str:
    if len(context) <= max_chars:
        return context
    return "..." + context[-(max_chars - 3):]


def _build_phase_artifact(
    cycle_id: int,
    phase: str,
    goal: str,
    actions: list[dict[str, Any]],
) -> str:
    lines = [
        f"# Sprint {cycle_id} — {phase.capitalize()}",
        "",
        f"**Goal:** {goal}",
        "",
        f"**Actions taken:** {len(actions)}",
        "",
    ]
    for action in actions:
        lines.append(f"## {action['tool_name']}")
        lines.append(f"- Arguments: `{json.dumps(action.get('arguments', {}), ensure_ascii=False)}`")
        summary = action.get("result_summary", "")
        lines.append(f"- Result summary: {summary[:500]}")
        if action.get("error"):
            lines.append(f"- Error: {action['error']}")
        lines.append("")
    return "\n".join(lines)


async def _safe_call_tool(
    mcp: MCPServer,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch a tool call and return a structured dict with text or error."""
    try:
        result = await mcp.call_tool(tool_name, arguments)
        text = _extract_result_text(result)
        return {"tool_name": tool_name, "arguments": arguments, "text": text, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"tool_name": tool_name, "arguments": arguments, "text": "", "error": str(exc)}


async def _run_autonomous_sprint(
    mcp: MCPServer,
    goal: str,
    cycle_id: int,
    max_phase_iterations: int,
    auto_create_backlog_tasks: bool,
    model: str,
) -> str:
    if not cycle_id:
        cycle_id = _derive_cycle_id()

    phase_results: list[dict[str, Any]] = []
    top_level_errors: list[str] = []
    tasks_created = 0

    for phase in SPRINT_PHASES:
        actions: list[dict[str, Any]] = []
        phase_error: str | None = None

        try:
            for iteration in range(max_phase_iterations):
                context = _truncate_context(
                    "Goal: " + goal + "\n\n"
                    + "\n".join(
                        f"{a['tool_name']}: {a.get('result_summary', '')}"
                        for a in actions[-6:]
                    )
                )

                rec_result = await _safe_call_tool(
                    mcp,
                    "suggest_next_action",
                    {"goal": goal, "phase": phase.upper(), "context": context, "model": model},
                )
                if rec_result["error"]:
                    top_level_errors.append(f"{phase} suggest_next_action error: {rec_result['error']}")
                    break

                try:
                    recommendation = json.loads(rec_result["text"])
                except json.JSONDecodeError as exc:
                    top_level_errors.append(f"{phase} suggestion parse error: {exc}")
                    break

                tool_name = recommendation.get("tool_name")
                confidence = recommendation.get("confidence", 0.0)
                if not tool_name or confidence < 0.3:
                    break

                if tool_name in _AUTONOMOUS_BLOCKED_TOOLS:
                    actions.append({
                        "tool_name": tool_name,
                        "arguments": recommendation.get("arguments", {}),
                        "result_summary": "Blocked by autonomous sprint safety policy.",
                        "error": None,
                        "blocked": True,
                    })
                    continue

                exec_result = await _safe_call_tool(
                    mcp,
                    tool_name,
                    recommendation.get("arguments", {}),
                )
                actions.append({
                    "tool_name": tool_name,
                    "arguments": recommendation.get("arguments", {}),
                    "result_summary": _extract_result_text(exec_result["text"])[:500],
                    "error": exec_result["error"],
                    "blocked": False,
                })
                if exec_result["error"]:
                    top_level_errors.append(f"{phase} {tool_name} error: {exec_result['error']}")

        except Exception as exc:  # noqa: BLE001
            phase_error = f"{phase} phase exception: {exc}"
            top_level_errors.append(phase_error)

        artifact_markdown = _build_phase_artifact(cycle_id, phase, goal, actions)
        await _safe_call_tool(
            mcp,
            "update_phase_artifact",
            {"cycle_id": cycle_id, "phase": phase, "content": artifact_markdown},
        )

        eval_result = await _safe_call_tool(
            mcp,
            "evaluate_sprint_outcome",
            {"cycle_id": cycle_id, "phase": phase, "goal": goal},
        )
        evaluation: dict[str, Any] = {}
        try:
            evaluation = json.loads(eval_result["text"])
        except json.JSONDecodeError as exc:
            evaluation = {"goalMet": False, "gaps": [f"Evaluator response was not valid JSON: {exc}"]}

        gaps = evaluation.get("gaps", [])
        if auto_create_backlog_tasks and gaps:
            for gap in gaps:
                await _safe_call_tool(
                    mcp,
                    "create_sprint_task",
                    {
                        "title": f"Gap from {phase.capitalize()}",
                        "description": str(gap),
                        "tier": "5",
                        "priority": "medium",
                    },
                )
                tasks_created += 1

        phase_results.append({
            "phase": phase,
            "iterations": len(actions),
            "actions": actions,
            "artifact_path": str(_artifact_path(cycle_id, phase).relative_to(WORKSPACE_ROOT)),
            "evaluation": evaluation,
            "tasks_created": len(gaps) if auto_create_backlog_tasks else 0,
            "error": phase_error,
        })

    final_goal_met = all(pr["evaluation"].get("goalMet", False) for pr in phase_results)
    status = "completed" if final_goal_met else "partial"
    if top_level_errors and status == "completed":
        status = "completed_with_errors"

    return {
        "cycle_id": cycle_id,
        "goal": goal,
        "status": status,
        "phase_results": phase_results,
        "tasks_created": tasks_created,
        "errors": top_level_errors,
    }



def _read_artifact_internal(workspace: Path, cycle_id: int, phase: str) -> str:
    """Internal helper to read artifact without decorator."""
    path = workspace / f"sprint-{cycle_id}-{phase.lower()}.md"
    if not path.exists():
        return f"Artifact for cycle {cycle_id} phase {phase!r} not found."
    return path.read_text(encoding="utf-8")


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    @tool_runtime(name="create_sprint_task")
    def create_sprint_task(
        ctx: ToolContext = None,
        title: str = "",
        description: str = "",
        tier: str = "5",
        priority: str = "medium",
    ) -> str:
        """Append a new task stub to the OllamaDev sprint backlog (agent-os/backlog.md).

        Args:
            title:       Short task title (used as the markdown heading).
            description: Implementation notes or acceptance criteria.
            tier:        Backlog tier to place the task under (default: '5').
            priority:    Priority label: low | medium | high (default: 'medium').

        Returns:
            Confirmation message with the appended section.
        """
        backlog = _safe_path(_BACKLOG_PATH)
        if not backlog.exists():
            raise FileNotFoundError(f"Backlog not found: {_BACKLOG_PATH}")

        if not re.match(r"^[1-9][0-9]?$", tier):
            raise ValueError(f"Invalid tier: {tier!r} — must be a positive integer string")
        if priority not in ("low", "medium", "high"):
            raise ValueError(f"Invalid priority: {priority!r}")

        stub = (
            f"\n\n### Tier {tier} — {title}\n"
            f"**Priority:** {priority}\n\n"
            f"{description.strip()}\n"
        )
        with backlog.open("a", encoding="utf-8") as f:
            f.write(stub)

        return f"Appended to {_BACKLOG_PATH}:\n{stub}"

    @mcp.tool()
    @tool_runtime(name="list_phase_artifacts")
    def list_phase_artifacts(ctx: ToolContext = None, cycle_id: int = 0) -> str:
        """List the sprint phase artifact files for a given cycle.

        Args:
            cycle_id: Sprint cycle identifier.

        Returns:
            Markdown list of existing sprint artifact paths, ordered by phase.
        """
        workspace = ctx.workspace_root if ctx else WORKSPACE_ROOT
        found: dict[str, str] = {}
        for phase in SPRINT_PHASES:
            path = workspace / f"sprint-{cycle_id}-{phase.lower()}.md"
            if path.exists():
                found[phase] = str(path.relative_to(workspace))
        if not found:
            return f"No artifacts found for cycle {cycle_id}."
        lines = [f"Artifacts for cycle {cycle_id}:"]
        for phase in SPRINT_PHASES:
            if phase in found:
                lines.append(f"- {phase}: {found[phase]}")
        return "\n".join(lines)

    @mcp.tool()
    @tool_runtime(name="read_phase_artifact")
    def read_phase_artifact(ctx: ToolContext = None, cycle_id: int = 0, phase: str = "") -> str:
        """Read a specific sprint phase artifact.

        Args:
            cycle_id: Sprint cycle identifier.
            phase:    Phase name, e.g. 'discovery', 'verification'.

        Returns:
            Artifact content, or a 'not found' message.
        """
        workspace = ctx.workspace_root if ctx else WORKSPACE_ROOT
        return _read_artifact_internal(workspace, cycle_id, phase)

    @mcp.tool()
    @tool_runtime(name="update_phase_artifact")
    def update_phase_artifact(ctx: ToolContext = None, cycle_id: int = 0, phase: str = "", content: str = "") -> str:
        """Write (or overwrite) a sprint phase artifact.

        Args:
            cycle_id: Sprint cycle identifier.
            phase:    Phase name, e.g. 'retrospective'.
            content:  Full markdown content to write.

        Returns:
            Confirmation message.
        """
        workspace = ctx.workspace_root if ctx else WORKSPACE_ROOT
        path = workspace / f"sprint-{cycle_id}-{phase.lower()}.md"
        path.write_text(content, encoding="utf-8")
        rel = path.relative_to(workspace)
        return f"Updated {rel} ({len(content.encode())} bytes)"

    @mcp.tool()
    @tool_runtime(name="evaluate_sprint_outcome")
    def evaluate_sprint_outcome(ctx: ToolContext = None, cycle_id: int = 0, phase: str = "", goal: str = "") -> str:
        """Compare a phase artifact against the sprint goal and return a structured critique.

        This is a lightweight, deterministic evaluator for RETROSPECTIVE agents. It reads the
        requested artifact, scans for requirement lines (REQ-N), PASS/FAIL/UNRESOLVED markers,
        and cross-checks them against the provided goal.

        Args:
            cycle_id: Sprint cycle identifier.
            phase:    Phase name to evaluate, e.g. 'verification'.
            goal:     Sprint goal string. If empty, the evaluator reads the discovery artifact
                      or the current artifact for context.

        Returns:
            JSON string: {goalMet, reqCount, passedCount, failedCount, unresolvedCount, gaps, recommendedNextTool}.
        """
        workspace = ctx.workspace_root if ctx else WORKSPACE_ROOT
        artifact_text = _read_artifact_internal(workspace, cycle_id, phase)
        if artifact_text.startswith("Artifact for cycle"):
            return {
                "goalMet": False,
                "reqCount": 0,
                "passedCount": 0,
                "failedCount": 0,
                "unresolvedCount": 0,
                "gaps": ["Artifact not found."],
                "recommendedNextTool": "read_phase_artifact",
            }

        if not goal:
            # Try to read discovery artifact for the goal context
            discovery = _read_artifact_internal(workspace, cycle_id, "discovery")
            if not discovery.startswith("Artifact for cycle"):
                goal = " ".join(discovery.splitlines()[:10])
            else:
                goal = "(no goal provided)"

        req_count = len(re.findall(r"REQ-\d+", artifact_text))
        passed = len(re.findall(r"\bPASS\b", artifact_text, re.IGNORECASE))
        failed = len(re.findall(r"\bFAIL\b", artifact_text, re.IGNORECASE))
        unresolved = len(re.findall(r"\[UNRESOLVED", artifact_text, re.IGNORECASE))

        gaps: list[str] = []
        if req_count == 0:
            gaps.append("No REQ-N markers found; cannot verify goal coverage.")
        if failed > 0:
            gaps.append(f"{failed} requirement(s) marked FAIL.")
        if unresolved > 0:
            gaps.append(f"{unresolved} unresolved blocker(s) recorded.")
        goal_words = set(re.findall(r"\w+", goal.lower()))
        artifact_words = set(re.findall(r"\w+", artifact_text.lower()))
        overlap = goal_words & artifact_words
        if goal_words and len(overlap) < max(1, len(goal_words) // 4):
            gaps.append("Artifact vocabulary shows weak overlap with sprint goal.")

        goal_met = failed == 0 and unresolved == 0 and req_count > 0 and len(gaps) <= 1

        recommended = "create_sprint_task"
        if failed > 0 or unresolved > 0:
            recommended = "run_gradle_tests"
        elif phase.lower() in ("discovery", "design"):
            recommended = "search_workspace"
        elif phase.lower() == "retrospective":
            recommended = "store_memory"

        return {
            "goalMet": goal_met,
            "reqCount": req_count,
            "passedCount": passed,
            "failedCount": failed,
            "unresolvedCount": unresolved,
            "gaps": gaps,
            "recommendedNextTool": recommended,
        }

    @mcp.tool()
    @tool_runtime(name="run_autonomous_sprint")
    async def run_autonomous_sprint(
        ctx: ToolContext = None,
        goal: str = "",
        cycle_id: int = 0,
        max_phase_iterations: int = 3,
        auto_create_backlog_tasks: bool = True,
        model: str = "llama3",
    ) -> dict:
        """Run a full autonomous six-phase sprint loop through the companion server.

        The loop iterates through discovery → design → implementation → verification →
        integration → retrospective. For each phase it asks `suggest_next_action` which
        workspace tool to run, executes the recommended tool (skipping blocked or
        destructive tools), accumulates a short context, writes a phase artifact, and
        evaluates the outcome. Gaps found by the evaluator become backlog tasks when
        `auto_create_backlog_tasks` is true.

        Args:
            goal: Sprint objective.
            cycle_id: Optional cycle id; if 0 the next free id is derived from existing
                      sprint artifacts.
            max_phase_iterations: Maximum `suggest_next_action` rounds per phase.
            auto_create_backlog_tasks: Whether to call `create_sprint_task` for each gap.
            model: Model tag passed to `suggest_next_action`.

        Returns:
            JSON string summarizing the cycle, per-phase results, and any errors.
        """
        return await _run_autonomous_sprint(
            mcp=mcp,
            goal=goal,
            cycle_id=cycle_id,
            max_phase_iterations=max_phase_iterations,
            auto_create_backlog_tasks=auto_create_backlog_tasks,
            model=model,
        )

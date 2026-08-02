"""Sprint workflow tools for managing OllamaDev artifacts and backlog."""

import re
from pathlib import Path

from mcp.server import MCPServer

from ollamadev_mcp_server.constants import SPRINT_PHASES, WORKSPACE_ROOT
from ollamadev_mcp_server.tools.filesystem import _safe_path

_BACKLOG_PATH = "agent-os/backlog.md"


def _artifact_path(cycle_id: int, phase: str) -> Path:
    return WORKSPACE_ROOT / f"sprint-{cycle_id}-{phase.lower()}.md"


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def create_sprint_task(
        title: str,
        description: str,
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
    def list_phase_artifacts(cycle_id: int) -> str:
        """List the sprint phase artifact files for a given cycle.

        Args:
            cycle_id: Sprint cycle identifier.

        Returns:
            Markdown list of existing sprint artifact paths, ordered by phase.
        """
        found: dict[str, str] = {}
        for phase in SPRINT_PHASES:
            path = _artifact_path(cycle_id, phase)
            if path.exists():
                found[phase] = str(path.relative_to(WORKSPACE_ROOT))
        if not found:
            return f"No artifacts found for cycle {cycle_id}."
        lines = [f"Artifacts for cycle {cycle_id}:"]
        for phase in SPRINT_PHASES:
            if phase in found:
                lines.append(f"- {phase}: {found[phase]}")
        return "\n".join(lines)

    @mcp.tool()
    def read_phase_artifact(cycle_id: int, phase: str) -> str:
        """Read a specific sprint phase artifact.

        Args:
            cycle_id: Sprint cycle identifier.
            phase:    Phase name, e.g. 'discovery', 'verification'.

        Returns:
            Artifact content, or a 'not found' message.
        """
        path = _artifact_path(cycle_id, phase)
        if not path.exists():
            return f"Artifact for cycle {cycle_id} phase {phase!r} not found."
        return path.read_text(encoding="utf-8")

    @mcp.tool()
    def update_phase_artifact(cycle_id: int, phase: str, content: str) -> str:
        """Write (or overwrite) a sprint phase artifact.

        Args:
            cycle_id: Sprint cycle identifier.
            phase:    Phase name, e.g. 'retrospective'.
            content:  Full markdown content to write.

        Returns:
            Confirmation message.
        """
        path = _artifact_path(cycle_id, phase)
        path.write_text(content, encoding="utf-8")
        rel = path.relative_to(WORKSPACE_ROOT)
        return f"Updated {rel} ({len(content.encode())} bytes)"

    @mcp.tool()
    def evaluate_sprint_outcome(cycle_id: int, phase: str, goal: str = "") -> str:
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
        import json

        artifact_text = read_phase_artifact(cycle_id, phase)
        if artifact_text.startswith("Artifact for cycle"):
            return json.dumps({
                "goalMet": False,
                "reqCount": 0,
                "passedCount": 0,
                "failedCount": 0,
                "unresolvedCount": 0,
                "gaps": ["Artifact not found."],
                "recommendedNextTool": "read_phase_artifact",
            }, indent=2)

        if not goal:
            # Try to read discovery artifact for the goal context
            discovery = read_phase_artifact(cycle_id, "discovery")
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

        return json.dumps({
            "goalMet": goal_met,
            "reqCount": req_count,
            "passedCount": passed,
            "failedCount": failed,
            "unresolvedCount": unresolved,
            "gaps": gaps,
            "recommendedNextTool": recommended,
        }, indent=2)

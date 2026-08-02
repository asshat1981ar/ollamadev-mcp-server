"""Observability / debugging tools for the OllamaDev agent loop."""

import json
from pathlib import Path

from mcp.server import MCPServer

from ollamadev_mcp_server.constants import WORKSPACE_ROOT
from ollamadev_mcp_server.tools.filesystem import _safe_path


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def get_task_transcript(task_id: int, format: str = "markdown") -> str:
        """Read a previously exported task transcript for debugging a sprint phase.

        The Android app does not expose its Room database directly to the MCP server, so this
        tool reads transcript files exported by the app to the workspace:
          - store/task_transcript_{task_id}.json
          - store/task_transcript_{task_id}.md

        Args:
            task_id: SwarmTask identifier.
            format:  Output format: 'markdown' or 'json' (default: 'markdown').

        Returns:
            Markdown or JSON transcript, or instructions on how to export one.
        """
        candidates = [
            WORKSPACE_ROOT / "store" / f"task_transcript_{task_id}.json",
            WORKSPACE_ROOT / "store" / f"task_transcript_{task_id}.md",
        ]

        transcript_path: Path | None = None
        for p in candidates:
            if p.exists() and p.is_file():
                transcript_path = p
                break

        if transcript_path is None:
            return (
                f"No transcript export found for task {task_id}.\n\n"
                "To use this tool, export the TaskStep rows from the Android app to:\n"
                f"  store/task_transcript_{task_id}.json\n"
                f"  store/task_transcript_{task_id}.md\n\n"
                "Each line/object should contain: agentName, agentRole, actionType, content, timestamp."
            )

        text = transcript_path.read_text(encoding="utf-8")
        suffix = transcript_path.suffix.lower()

        if suffix == ".json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                return f"Transcript file is not valid JSON: {exc}"
            if format == "json":
                return json.dumps(data, indent=2)
            # Render as markdown
            if isinstance(data, list):
                lines = [f"# Task {task_id} Transcript"]
                for step in data:
                    if isinstance(step, dict):
                        lines.append(
                            f"\n## {step.get('agentName', '?')} ({step.get('agentRole', '?')}) — {step.get('actionType', '?')}\n"
                            f"{step.get('content', '')}"
                        )
                return "\n".join(lines)
            return text

        # Markdown file
        if format == "json":
            return json.dumps({"markdown": text}, indent=2)
        return text

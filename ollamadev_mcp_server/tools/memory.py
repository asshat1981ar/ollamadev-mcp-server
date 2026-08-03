"""Agent memory / key-value store tools.

Memories are persisted as JSON in the workspace under `store/agent_memory.json` so they
survive server restarts and can be inspected by other tools.
"""

import json
from pathlib import Path

from mcp.server import MCPServer

from ollamadev_mcp_server.constants import STORE_DIR, WORKSPACE_ROOT
from ollamadev_mcp_server.tool_decorator import tool_runtime
from ollamadev_mcp_server.tool_runtime import ToolContext

_MEMORY_FILE = STORE_DIR / "agent_memory.json"


def _load_memory() -> dict[str, str]:
    if not _MEMORY_FILE.exists():
        return {}
    try:
        data = json.loads(_MEMORY_FILE.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()}
    except (json.JSONDecodeError, TypeError):
        return {}


def _save_memory(data: dict[str, str]) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    _MEMORY_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    @tool_runtime(name="store_memory")
    def store_memory(ctx: ToolContext = None, key: str = "", value: str = "") -> str:
        """Store a short memory / fact for the agent swarm.

        Args:
            key:   Short unique identifier for this memory.
            value: The value to remember.

        Returns:
            Confirmation message.
        """
        data = _load_memory()
        data[key] = value
        _save_memory(data)
        return f"Stored memory '{key}' ({len(value)} chars)."

    @mcp.tool()
    @tool_runtime(name="recall_memory")
    def recall_memory(ctx: ToolContext = None, key: str = "") -> str:
        """Recall a previously stored memory.

        Args:
            key: The memory key to retrieve.

        Returns:
            The stored value, or 'Memory not found.'
        """
        data = _load_memory()
        return data.get(key, "Memory not found.")

    @mcp.tool()
    @tool_runtime(name="list_memories")
    def list_memories(ctx: ToolContext = None) -> str:
        """List all stored memory keys and short previews.

        Returns:
            Markdown list of keys with value previews.
        """
        data = _load_memory()
        if not data:
            return "No memories stored."
        lines = ["| Key | Preview |", "|---|---|"]
        for k, v in sorted(data.items()):
            preview = v.replace("|", "\\|").replace("\n", " ")
            if len(preview) > 80:
                preview = preview[:77] + "..."
            lines.append(f"| {k} | {preview} |")
        return "\n".join(lines)

    @mcp.tool()
    @tool_runtime(name="clear_memory")
    def clear_memory(ctx: ToolContext = None, key: str = "") -> str:
        """Delete a single stored memory entry.

        Args:
            key: The memory key to delete.

        Returns:
            Confirmation or 'Memory not found.'
        """
        data = _load_memory()
        if key not in data:
            return "Memory not found."
        del data[key]
        _save_memory(data)
        return f"Cleared memory '{key}'."

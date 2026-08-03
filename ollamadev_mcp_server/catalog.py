"""Dynamic tool catalog generation.

Replaces the hardcoded ``_TOOL_CATALOG`` in ``meta.py`` with a dynamically
generated catalog that introspects registered MCP tools.  Prevents drift
between the catalog and actual registered tools.

Usage::

    from ollamadev_mcp_server.catalog import build_tool_catalog

    catalog = build_tool_catalog(mcp)
    for tool in catalog:
        print(tool["name"], tool["phase"])
"""

from typing import Any

from mcp.server import MCPServer

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Phase tags for known tools
# ---------------------------------------------------------------------------

# Tools not listed here get phase="GENERAL".
_TOOL_PHASES: dict[str, str] = {
    # Filesystem
    "list_workspace_files": "DISCOVERY",
    "read_workspace_file": "DISCOVERY/DESIGN/IMPLEMENTATION/VERIFICATION",
    "write_workspace_file": "IMPLEMENTATION",
    "delete_workspace_file": "IMPLEMENTATION",
    "move_workspace_file": "IMPLEMENTATION",
    # Code intelligence
    "search_workspace": "DISCOVERY/VERIFICATION",
    "get_file_outline": "DESIGN",
    "find_symbol": "DESIGN/INTEGRATION",
    "get_todos": "INTEGRATION/RETROSPECTIVE",
    # Surgical edits & dependencies
    "apply_file_patch": "IMPLEMENTATION",
    "add_gradle_dependency": "IMPLEMENTATION",
    # Build & verification
    "run_gradle_tests": "VERIFICATION",
    "run_gradle_test_command": "VERIFICATION",
    "run_gradle_build": "VERIFICATION",
    "parse_test_results": "VERIFICATION",
    "parse_test_results_xml": "VERIFICATION",
    "parse_coverage_xml": "VERIFICATION",
    "run_lint": "VERIFICATION",
    "run_detekt": "VERIFICATION",
    "run_ktlint": "VERIFICATION",
    "get_build_config": "INTEGRATION",
    "run_instrumented_tests": "VERIFICATION",
    "run_screenshot_tests": "VERIFICATION",
    # Sprint workflow
    "create_sprint_task": "all",
    "list_phase_artifacts": "all",
    "read_phase_artifact": "all",
    "update_phase_artifact": "all",
    "evaluate_sprint_outcome": "RETROSPECTIVE",
    "run_autonomous_sprint": "all",
    # Agent memory
    "store_memory": "RETROSPECTIVE",
    "recall_memory": "all",
    "list_memories": "all",
    "clear_memory": "RETROSPECTIVE",
    # Meta
    "describe_tools": "all",
    "suggest_next_action": "all",
    "ping": "all",
    # Git
    "git_status_diff": "INTEGRATION/RETROSPECTIVE",
    "git_commit_checkpoint": "INTEGRATION/RETROSPECTIVE",
    "git_log": "INTEGRATION/RETROSPECTIVE",
    # Sandbox
    "run_pytest": "VERIFICATION",
    "run_shell_command": "VERIFICATION",
    "get_sandbox_status": "all",
    # Settings
    "get_server_settings": "all",
    "update_server_settings": "all",
    "reset_server_settings": "all",
    # Observability
    "get_task_transcript": "VERIFICATION",
    # Phase 1: Observability
    "get_server_health": "all",
    "get_server_diagnostics": "all",
    # Phase 2: Security
    "get_audit_log": "all",
}


# ---------------------------------------------------------------------------
# Catalog building
# ---------------------------------------------------------------------------


def build_tool_catalog(mcp: MCPServer) -> list[dict[str, Any]]:
    """Build a tool catalog from the registered tools on the MCP server.

    Introspects the MCP server's tool manager to extract tool names,
    descriptions, and parameters.  Falls back to the static ``_TOOL_PHASES``
    mapping for phase tags.

    Args:
        mcp: The MCP server instance with registered tools.

    Returns:
        List of tool dicts with ``name``, ``phase``, ``description``, and
        optionally ``params``.
    """
    catalog: list[dict[str, Any]] = []

    # Access the tool manager's internal tool registry
    # The MCP SDK stores tools in _tool_manager._tools (dict[str, Tool])
    try:
        tools = mcp._tool_manager._tools if hasattr(mcp, "_tool_manager") else {}
    except AttributeError:
        tools = {}

    for name, tool in tools.items():
        entry: dict[str, Any] = {
            "name": name,
            "phase": _TOOL_PHASES.get(name, "GENERAL"),
        }

        # Extract description if available
        if hasattr(tool, "description") and tool.description:
            entry["description"] = tool.description

        # Extract parameter info if available
        if hasattr(tool, "parameters") and tool.parameters:
            params = {}
            for param_name, param_info in tool.parameters.items():
                if isinstance(param_info, dict):
                    param_type = param_info.get("type", "string")
                    params[param_name] = param_type
                else:
                    params[param_name] = "string"
            if params:
                entry["params"] = params

        catalog.append(entry)

    # Sort by name for consistent output
    catalog.sort(key=lambda x: x["name"])

    logger.info("Built dynamic tool catalog with %d tools", len(catalog))
    return catalog


def get_tools_by_phase(catalog: list[dict[str, Any]], phase: str) -> list[dict[str, Any]]:
    """Filter catalog entries by phase.

    Args:
        catalog: The tool catalog from ``build_tool_catalog``.
        phase: Phase name (e.g. "DISCOVERY", "IMPLEMENTATION").

    Returns:
        Filtered list of tools that match the phase or have phase="all".
    """
    phase_upper = phase.upper()
    return [
        entry
        for entry in catalog
        if phase_upper in entry.get("phase", "").upper() or entry.get("phase", "").lower() == "all"
    ]


def get_tool_by_name(catalog: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Find a tool in the catalog by name.

    Args:
        catalog: The tool catalog from ``build_tool_catalog``.
        name: Tool name to find.

    Returns:
        Tool dict if found, else ``None``.
    """
    for entry in catalog:
        if entry["name"] == name:
            return entry
    return None


def validate_catalog(mcp: MCPServer) -> list[str]:
    """Validate that the catalog matches registered tools.

    Checks for:
    - Tools in ``_TOOL_PHASES`` that aren't registered
    - Registered tools without phase tags (not in ``_TOOL_PHASES``)

    Args:
        mcp: The MCP server instance.

    Returns:
        List of issue descriptions.  Empty list means catalog is consistent.
    """
    issues: list[str] = []

    # Get registered tools
    try:
        tools = mcp._tool_manager._tools if hasattr(mcp, "_tool_manager") else {}
    except AttributeError:
        tools = {}
    registered_names = set(tools.keys())

    # Check for tools in _TOOL_PHASES that aren't registered
    catalog_names = set(_TOOL_PHASES.keys())
    missing_from_registry = catalog_names - registered_names
    if missing_from_registry:
        issues.append(f"Tools in catalog but not registered: {sorted(missing_from_registry)}")

    # Check for registered tools without phase tags
    untagged = registered_names - catalog_names
    if untagged:
        issues.append(f"Registered tools without phase tags: {sorted(untagged)}")

    return issues

"""Timeout configuration and enforcement for the OllamaDev MCP server.

Provides per-tool timeout defaults that can be overridden via environment
variables.  The ``get_timeout`` function is the single entry point for
tool modules that need to know their deadline.

Usage::

    from ollamadev_mcp_server.timeouts import get_timeout

    timeout = get_timeout("run_gradle_tests")  # 600
"""

import os

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Default timeouts (seconds)
# ---------------------------------------------------------------------------

DEFAULT_TOOL_TIMEOUT = int(os.environ.get("DEFAULT_TOOL_TIMEOUT", "60"))
DEFAULT_LLM_TIMEOUT = int(os.environ.get("DEFAULT_LLM_TIMEOUT", "120"))
DEFAULT_SHELL_TIMEOUT = int(os.environ.get("DEFAULT_SHELL_TIMEOUT", "300"))
DEFAULT_GRADLE_TIMEOUT = int(os.environ.get("DEFAULT_GRADLE_TIMEOUT", "600"))
DEFAULT_AUTONOMOUS_TIMEOUT = int(os.environ.get("DEFAULT_AUTONOMOUS_TIMEOUT", "3600"))

# ---------------------------------------------------------------------------
# Per-tool timeout overrides
# ---------------------------------------------------------------------------

TOOL_TIMEOUTS: dict[str, int] = {
    # Code intelligence (fast, grep-based)
    "search_workspace": 30,
    "get_file_outline": 30,
    "find_symbol": 30,
    "get_todos": 30,
    # Filesystem (fast, local I/O)
    "list_workspace_files": 30,
    "read_workspace_file": 30,
    "write_workspace_file": 30,
    "delete_workspace_file": 10,
    "move_workspace_file": 10,
    # Build / verification (slow, Gradle)
    "run_gradle_tests": DEFAULT_GRADLE_TIMEOUT,
    "run_gradle_test_command": DEFAULT_GRADLE_TIMEOUT,
    "run_gradle_build": DEFAULT_GRADLE_TIMEOUT,
    "run_lint": 120,
    "run_detekt": 120,
    "run_ktlint": 120,
    "run_instrumented_tests": 900,
    "run_screenshot_tests": 900,
    "parse_test_results": 60,
    "parse_test_results_xml": 60,
    "parse_coverage_xml": 60,
    # Sandbox
    "run_pytest": DEFAULT_SHELL_TIMEOUT,
    "run_shell_command": DEFAULT_SHELL_TIMEOUT,
    # LLM
    "suggest_next_action": DEFAULT_LLM_TIMEOUT,
    # Autonomous
    "run_autonomous_sprint": DEFAULT_AUTONOMOUS_TIMEOUT,
}


def get_timeout(tool_name: str) -> int:
    """Get the timeout in seconds for a specific tool.

    Falls back to ``DEFAULT_TOOL_TIMEOUT`` if the tool is not in the
    override table.
    """
    return TOOL_TIMEOUTS.get(tool_name, DEFAULT_TOOL_TIMEOUT)


def get_all_timeouts() -> dict[str, int]:
    """Return a copy of the full timeout table (for diagnostics)."""
    return dict(TOOL_TIMEOUTS)

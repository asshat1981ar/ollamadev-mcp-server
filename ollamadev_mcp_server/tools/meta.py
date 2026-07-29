"""Meta / agentic tools for the OllamaDev MCP toolbox.

Includes:
- `describe_tools`: returns a hardcoded, phase-tagged catalog for agent consumption.
- `suggest_next_action`: asks a local Ollama model which tool to call next.
- `ping`: connectivity / sanity check.
"""

import json
import time
from typing import Any

import requests
from mcp.server import MCPServer

from ollamadev_mcp_server.constants import OLLAMA_URL

_START = time.time()

# Hardcoded tool catalog. This is intentionally static so `suggest_next_action` cannot
# recurse into calling itself to describe itself.
_TOOL_CATALOG: list[dict[str, Any]] = [
    {
        "name": "list_workspace_files",
        "phase": "DISCOVERY",
        "params": {"root": "subdirectory to list (optional)"},
        "example": "MCP_CALL: list_workspace_files | {\"root\": \"app/src/main/java/com/example\"}",
    },
    {
        "name": "read_workspace_file",
        "phase": "DISCOVERY/DESIGN/IMPLEMENTATION/VERIFICATION",
        "params": {"path": "relative workspace path"},
        "example": "MCP_CALL: read_workspace_file | {\"path\": \"app/src/main/java/com/example/data/SprintOrchestrator.kt\"}",
    },
    {
        "name": "search_workspace",
        "phase": "DISCOVERY/VERIFICATION",
        "params": {"pattern": "regex", "file_glob": "*.kt", "ignore_case": False, "context_lines": 2},
        "example": "MCP_CALL: search_workspace | {\"pattern\": \"class SprintOrchestrator\", \"context_lines\": 0}",
    },
    {
        "name": "get_file_outline",
        "phase": "DESIGN",
        "params": {"path": "relative workspace path"},
        "example": "MCP_CALL: get_file_outline | {\"path\": \"app/src/main/java/com/example/data/SprintOrchestrator.kt\"}",
    },
    {
        "name": "find_symbol",
        "phase": "DESIGN/INTEGRATION",
        "params": {"name": "symbol name", "symbol_type": "any|class|function|property", "file_glob": "*.kt"},
        "example": "MCP_CALL: find_symbol | {\"name\": \"SprintPhase\", \"symbol_type\": \"class\"}",
    },
    {
        "name": "get_todos",
        "phase": "INTEGRATION/RETROSPECTIVE",
        "params": {"file_glob": "*.kt", "patterns": ["TODO", "FIXME"]},
        "example": "MCP_CALL: get_todos | {}",
    },
    {
        "name": "write_workspace_file",
        "phase": "IMPLEMENTATION",
        "params": {"path": "relative workspace path", "content": "full file content"},
        "example": "MCP_CALL: write_workspace_file | {\"path\": \"app/src/main/java/com/example/Foo.kt\", \"content\": \"package...\"}",
    },
    {
        "name": "delete_workspace_file",
        "phase": "IMPLEMENTATION",
        "params": {"path": "relative workspace path"},
        "example": "MCP_CALL: delete_workspace_file | {\"path\": \"app/src/main/java/com/example/Temp.kt\"}",
    },
    {
        "name": "move_workspace_file",
        "phase": "IMPLEMENTATION",
        "params": {"src": "relative source", "dst": "relative destination"},
        "example": "MCP_CALL: move_workspace_file | {\"src\": \"Old.kt\", \"dst\": \"New.kt\"}",
    },
    {
        "name": "apply_file_patch",
        "phase": "IMPLEMENTATION",
        "params": {"path": "relative path", "patch": "unified diff", "reverse": False},
        "example": "MCP_CALL: apply_file_patch | {\"path\": \"app/src/main/java/com/example/Foo.kt\", \"patch\": \"--- a/...\"}",
    },
    {
        "name": "add_gradle_dependency",
        "phase": "IMPLEMENTATION",
        "params": {"alias": "", "group": "", "name": "", "version": "", "module": "app", "configuration": "implementation"},
        "example": "MCP_CALL: add_gradle_dependency | {\"alias\": \"retrofit\", \"group\": \"com.squareup.retrofit2\", \"name\": \"retrofit\", \"version\": \"2.11.0\"}",
    },
    {
        "name": "run_gradle_tests",
        "phase": "VERIFICATION",
        "params": {"module": "app", "test_filter": ""},
        "example": "MCP_CALL: run_gradle_tests | {\"module\": \"app\", \"test_filter\": \"com.example.SprintOrchestratorTest\"}",
    },
    {
        "name": "run_gradle_build",
        "phase": "VERIFICATION",
        "params": {"module": "app", "variant": "Debug"},
        "example": "MCP_CALL: run_gradle_build | {\"module\": \"app\", \"variant\": \"Debug\"}",
    },
    {
        "name": "parse_test_results",
        "phase": "VERIFICATION",
        "params": {"gradle_output": "raw output from run_gradle_tests"},
        "example": "MCP_CALL: parse_test_results | {\"gradle_output\": \"...\"}",
    },
    {
        "name": "run_lint",
        "phase": "VERIFICATION",
        "params": {"module": "app"},
        "example": "MCP_CALL: run_lint | {\"module\": \"app\"}",
    },
    {
        "name": "run_ktlint_detekt",
        "phase": "VERIFICATION",
        "params": {"command": "ktlint", "args": ["app/src/main/java"]},
        "example": "MCP_CALL: run_ktlint_detekt | {\"command\": \"ktlint\"}",
    },
    {
        "name": "get_build_config",
        "phase": "INTEGRATION",
        "params": {},
        "example": "MCP_CALL: get_build_config | {}",
    },
    {
        "name": "git_status_diff",
        "phase": "INTEGRATION/RETROSPECTIVE",
        "params": {"path": "", "staged": False},
        "example": "MCP_CALL: git_status_diff | {}",
    },
    {
        "name": "git_commit_checkpoint",
        "phase": "RETROSPECTIVE/INTEGRATION",
        "params": {"message": "", "author_name": "OllamaDev Agent", "author_email": ""},
        "example": "MCP_CALL: git_commit_checkpoint | {\"message\": \"checkpoint after sprint 1\"}",
    },
    {
        "name": "git_log",
        "phase": "RETROSPECTIVE/INTEGRATION",
        "params": {"limit": 10},
        "example": "MCP_CALL: git_log | {\"limit\": 5}",
    },
    {
        "name": "create_sprint_task",
        "phase": "RETROSPECTIVE",
        "params": {"title": "", "description": "", "tier": "5", "priority": "low|medium|high"},
        "example": "MCP_CALL: create_sprint_task | {\"title\": \"Fix auth timeout\", \"description\": \"...\", \"tier\": \"4\", \"priority\": \"high\"}",
    },
    {
        "name": "list_phase_artifacts",
        "phase": "RETROSPECTIVE",
        "params": {"cycle_id": 1},
        "example": "MCP_CALL: list_phase_artifacts | {\"cycle_id\": 1}",
    },
    {
        "name": "read_phase_artifact",
        "phase": "RETROSPECTIVE",
        "params": {"cycle_id": 1, "phase": "discovery|design|..."},
        "example": "MCP_CALL: read_phase_artifact | {\"cycle_id\": 1, \"phase\": \"verification\"}",
    },
    {
        "name": "update_phase_artifact",
        "phase": "RETROSPECTIVE",
        "params": {"cycle_id": 1, "phase": "retrospective", "content": ""},
        "example": "MCP_CALL: update_phase_artifact | {\"cycle_id\": 1, \"phase\": \"retrospective\", \"content\": \"...\"}",
    },
    {
        "name": "evaluate_sprint_outcome",
        "phase": "RETROSPECTIVE",
        "params": {"cycle_id": 1, "phase": "verification", "goal": ""},
        "example": "MCP_CALL: evaluate_sprint_outcome | {\"cycle_id\": 1, \"phase\": \"verification\"}",
    },
    {
        "name": "get_task_transcript",
        "phase": "OBSERVABILITY",
        "params": {"task_id": 1, "format": "markdown"},
        "example": "MCP_CALL: get_task_transcript | {\"task_id\": 1}",
    },
    {
        "name": "run_pytest",
        "phase": "VERIFICATION",
        "params": {"path": "", "test_filter": "", "timeout_seconds": 300},
        "example": "MCP_CALL: run_pytest | {\"path\": \"tests\"}",
    },
    {
        "name": "run_gradle_test_command",
        "phase": "VERIFICATION",
        "params": {"test_filter": "", "timeout_seconds": 600},
        "example": "MCP_CALL: run_gradle_test_command | {\"test_filter\": \"com.example.SprintOrchestratorTest\"}",
    },
    {
        "name": "run_shell_command",
        "phase": "VERIFICATION",
        "params": {"command": "", "timeout_seconds": 300},
        "example": "MCP_CALL: run_shell_command | {\"command\": \"make test\"}",
    },
    {
        "name": "get_sandbox_status",
        "phase": "VERIFICATION/META",
        "params": {},
        "example": "MCP_CALL: get_sandbox_status | {}",
    },
    {
        "name": "store_memory",
        "phase": "RETROSPECTIVE",
        "params": {"key": "", "value": ""},
        "example": "MCP_CALL: store_memory | {\"key\": \"auth-timeout-fix\", \"value\": \"...\"}",
    },
    {
        "name": "recall_memory",
        "phase": "RETROSPECTIVE",
        "params": {"key": ""},
        "example": "MCP_CALL: recall_memory | {\"key\": \"auth-timeout-fix\"}",
    },
    {
        "name": "list_memories",
        "phase": "RETROSPECTIVE",
        "params": {},
        "example": "MCP_CALL: list_memories | {}",
    },
    {
        "name": "describe_tools",
        "phase": "META",
        "params": {"category": "all|phase name"},
        "example": "MCP_CALL: describe_tools | {\"category\": \"verification\"}",
    },
    {
        "name": "suggest_next_action",
        "phase": "META",
        "params": {"goal": "", "phase": "", "context": "", "model": "llama3"},
        "example": "MCP_CALL: suggest_next_action | {\"goal\": \"Add a new migration for sprint tables\", \"phase\": \"IMPLEMENTATION\"}",
    },
]


def _build_catalog_markdown(category: str = "all") -> str:
    category = category.lower()
    lines = ["# OllamaDev MCP Tool Catalog"]
    for tool in _TOOL_CATALOG:
        phases = [p.strip().lower() for p in tool["phase"].split("/")]
        if category != "all" and category not in phases:
            continue
        lines.append(f"\n## {tool['name']}")
        lines.append(f"- **Phase(s):** {tool['phase']}")
        params = tool["params"]
        if params:
            lines.append("- **Parameters:**")
            for k, v in params.items():
                lines.append(f"  - `{k}`: {v}")
        lines.append(f"- **Example:** `{tool['example']}`")
    return "\n".join(lines)


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def ping() -> str:
        """Return server version and uptime for connectivity checks.

        Returns:
            Short JSON string with name, version, and uptime seconds.
        """
        return json.dumps({
            "name": "OllamaDev Toolbox",
            "version": "0.4.0",
            "uptime_seconds": round(time.time() - _START, 2),
        })

    @mcp.tool()
    def describe_tools(category: str = "all") -> str:
        """Return a markdown catalog of every available tool with examples.

        Args:
            category: Filter by phase, e.g. 'verification', 'implementation', or 'all' (default).

        Returns:
            Markdown tool catalog.
        """
        return _build_catalog_markdown(category)

    @mcp.tool()
    def suggest_next_action(
        goal: str,
        phase: str,
        context: str = "",
        model: str = "llama3",
        category: str = "all",
    ) -> str:
        """Ask a local Ollama model to recommend the next MCP tool call.

        This is the agentic self-prompt: it sends the tool catalog + current goal + phase
        to Ollama and returns a JSON recommendation with tool_name, arguments, reasoning,
        and confidence.

        Args:
            goal:      The sprint goal or current task.
            phase:     Current sprint phase (DISCOVERY, DESIGN, IMPLEMENTATION,
                       VERIFICATION, INTEGRATION, RETROSPECTIVE, META).
            context:   Optional recent observations / prior tool results.
            model:     Ollama model name (default: 'llama3').
            category:  Tool category to restrict recommendations to (default: 'all').

        Returns:
            JSON string: {"tool_name": "...", "arguments": {...}, "reasoning": "...", "confidence": 0.0}
        """
        catalog = _build_catalog_markdown(category)
        system_prompt = (
            "You are an MCP tool selector for an Android agent swarm. "
            "Choose exactly one tool from the catalog below that best advances the goal. "
            "Respond with valid JSON only in this exact shape:\n"
            '{"tool_name": "...", "arguments": {...}, "reasoning": "...", "confidence": 0.0}\n'
            "confidence must be a float between 0.0 and 1.0. Do not include markdown, prose, or explanation outside the JSON object.\n\n"
            "Phase priorities:\n"
            "- DISCOVERY: prefer list_workspace_files, search_workspace, read_workspace_file\n"
            "- DESIGN: prefer get_file_outline, find_symbol, read_workspace_file\n"
            "- IMPLEMENTATION: prefer apply_file_patch, write_workspace_file, add_gradle_dependency, read_workspace_file\n"
            "- VERIFICATION: prefer run_gradle_build, parse_test_results, run_gradle_tests, run_lint, run_ktlint_detekt, search_workspace, read_workspace_file\n"
            "- INTEGRATION: prefer git_status_diff, get_build_config, search_workspace, find_symbol, get_todos\n"
            "- RETROSPECTIVE: prefer git_commit_checkpoint, evaluate_sprint_outcome, create_sprint_task, update_phase_artifact, store_memory\n"
            "- META: prefer describe_tools, suggest_next_action\n"
            "- OBSERVABILITY: prefer get_task_transcript, git_log\n\n"
            f"Tool catalog:\n{catalog}"
        )
        user_prompt = (
            f"Current phase: {phase}\n"
            f"Goal: {goal}\n"
            f"Recent context: {context or '(none)'}\n"
            "Recommend the next single MCP tool call."
        )

        payload = {
            "model": model,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0},
        }

        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("response", "")
            parsed = json.loads(raw)
            for key in ("tool_name", "arguments", "reasoning", "confidence"):
                if key not in parsed:
                    raise ValueError(f"Missing key: {key}")
            parsed["confidence"] = float(parsed["confidence"])
            return json.dumps(parsed, ensure_ascii=False, indent=2)
        except requests.exceptions.ConnectionError as exc:
            return json.dumps({
                "tool_name": None,
                "arguments": {},
                "reasoning": f"Ollama is not reachable at {OLLAMA_URL}: {exc}",
                "confidence": 0.0,
            }, indent=2)
        except requests.exceptions.Timeout:
            return json.dumps({
                "tool_name": None,
                "arguments": {},
                "reasoning": "Ollama request timed out.",
                "confidence": 0.0,
            }, indent=2)
        except Exception as exc:
            return json.dumps({
                "tool_name": None,
                "arguments": {},
                "reasoning": f"Could not parse Ollama response: {exc}",
                "confidence": 0.0,
            }, indent=2)

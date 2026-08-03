"""Meta / agentic tools for the OllamaDev MCP toolbox.

Includes:
- `describe_tools`: returns a phase-tagged catalog for agent consumption.
- `suggest_next_action`: asks a local Ollama model which tool to call next.
- `ping`: connectivity / sanity check.
"""

import json
import time
from typing import Any

import requests
from mcp.server import MCPServer

from ollamadev_mcp_server.constants import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_AUTH_TOKEN,
    ANTHROPIC_BASE_URL,
    DEFAULT_CLOUD_MODEL,
    OLLAMA_API_KEY,
    OLLAMA_URL,
)
from ollamadev_mcp_server.retry import with_retry, LLM_RETRY
from ollamadev_mcp_server.circuit_breaker import get_ollama_breaker, get_anthropic_breaker
from ollamadev_mcp_server.tool_decorator import tool_runtime
from ollamadev_mcp_server.tool_runtime import ToolContext

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
        "name": "run_ktlint",
        "phase": "VERIFICATION",
        "params": {"args": ["app/src/main/java"]},
        "example": "MCP_CALL: run_ktlint | {}",
    },
    {
        "name": "run_detekt",
        "phase": "VERIFICATION",
        "params": {"args": ["--input", "app/src/main/java"]},
        "example": "MCP_CALL: run_detekt | {}",
    },
    {
        "name": "parse_test_results_xml",
        "phase": "VERIFICATION",
        "params": {"results_dir": "app/build/test-results/testDebugUnitTest", "raw_xml": ""},
        "example": "MCP_CALL: parse_test_results_xml | {}",
    },
    {
        "name": "get_coverage_summary",
        "phase": "VERIFICATION/INTEGRATION",
        "params": {"results_dir": "app/build/reports/jacoco/jacocoTestReport"},
        "example": "MCP_CALL: get_coverage_summary | {}",
    },
    {
        "name": "run_instrumented_tests",
        "phase": "VERIFICATION",
        "params": {"module": "app", "variant": "Debug", "test_filter": ""},
        "example": "MCP_CALL: run_instrumented_tests | {}",
    },
    {
        "name": "run_screenshot_tests",
        "phase": "VERIFICATION",
        "params": {"module": "app", "mode": "record", "test_filter": "com.example.ui.ScreenshotDriverTest"},
        "example": "MCP_CALL: run_screenshot_tests | {\"mode\": \"verify\"}",
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
    {
        "name": "get_server_settings",
        "phase": "META",
        "params": {},
        "example": "MCP_CALL: get_server_settings | {}",
    },
    {
        "name": "update_server_settings",
        "phase": "META",
        "params": {"settings": {"ollama_url": "http://localhost:11434"}},
        "example": "MCP_CALL: update_server_settings | {\"settings\": {\"default_cloud_model\": \"claude-sonnet-5-20251001\"}}",
    },
    {
        "name": "reset_server_settings",
        "phase": "META",
        "params": {},
        "example": "MCP_CALL: reset_server_settings | {}",
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
    @tool_runtime(name="ping")
    def ping(ctx: ToolContext = None) -> dict:
        """Return server version and uptime for connectivity checks.

        Returns:
            Short JSON string with name, version, and uptime seconds.
        """
        return {
            "name": "OllamaDev Toolbox",
            "version": "0.6.0",
            "uptime_seconds": round(time.time() - _START, 2),
        }

    @mcp.tool()
    @tool_runtime(name="describe_tools")
    def describe_tools(ctx: ToolContext = None, category: str = "all") -> str:
        """Return a markdown catalog of every available tool with examples.

        Args:
            category: Filter by phase, e.g. 'verification', 'implementation', or 'all' (default).

        Returns:
            Markdown tool catalog.
        """
        return _build_catalog_markdown(category)

    @mcp.tool()
    @tool_runtime(name="suggest_next_action")
    def suggest_next_action(
        ctx: ToolContext = None,
        goal: str = "",
        phase: str = "",
        context: str = "",
        model: str = "llama3",
        category: str = "all",
        provider: str = "auto",
    ) -> str:
        """Ask a model to recommend the next MCP tool call.

        Supports both a local Ollama instance and Anthropic's cloud API. By default
        `provider='auto'` picks Anthropic when `ANTHROPIC_API_KEY` is present,
        otherwise it falls back to Ollama.

        Args:
            goal:      The sprint goal or current task.
            phase:     Current sprint phase (DISCOVERY, DESIGN, IMPLEMENTATION,
                       VERIFICATION, INTEGRATION, RETROSPECTIVE, META).
            context:   Optional recent observations / prior tool results.
            model:     Model name. For Ollama this is a local model tag (default: 'llama3').
                       For Anthropic this is a model ID; when the default local tag is
                       passed, the configured DEFAULT_CLOUD_MODEL is used instead.
            category:  Tool category to restrict recommendations to (default: 'all').
            provider:  One of 'auto', 'ollama', or 'anthropic'.

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
            "- VERIFICATION: prefer run_gradle_build, parse_test_results, parse_test_results_xml, run_gradle_tests, run_lint, run_ktlint_detekt, run_ktlint, run_detekt, get_coverage_summary, run_instrumented_tests, run_screenshot_tests, search_workspace, read_workspace_file\n"
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

        chosen_provider = provider.lower()
        if chosen_provider == "auto":
            chosen_provider = "anthropic" if ANTHROPIC_API_KEY else "ollama"

        try:
            if chosen_provider == "anthropic":
                raw = _ask_anthropic(system_prompt, user_prompt, model)
            else:
                raw = _ask_ollama(system_prompt, user_prompt, model)
            parsed = _parse_recommendation(raw)
            return json.dumps(parsed, ensure_ascii=False, indent=2)
        except requests.exceptions.ConnectionError as exc:
            return json.dumps({
                "tool_name": None,
                "arguments": {},
                "reasoning": f"Model provider not reachable: {exc}",
                "confidence": 0.0,
            }, indent=2)
        except requests.exceptions.Timeout:
            return json.dumps({
                "tool_name": None,
                "arguments": {},
                "reasoning": "Model request timed out.",
                "confidence": 0.0,
            }, indent=2)
        except Exception as exc:
            return json.dumps({
                "tool_name": None,
                "arguments": {},
                "reasoning": f"Could not parse model response: {exc}",
                "confidence": 0.0,
            }, indent=2)


@with_retry(LLM_RETRY)
def _ask_ollama(system_prompt: str, user_prompt: str, model: str) -> str:
    """Send a request to an Ollama API (local or cloud).

    Ollama Cloud (https://ollama.com) exposes the chat endpoint at /api/chat rather
    than the legacy /api/generate endpoint. Local Ollama supports both, so we use
    /api/chat whenever the remote host looks like the cloud service and fall back to
    /api/generate for other local/self-hosted endpoints.
    """
    breaker = get_ollama_breaker()
    
    def _do_request():
        headers = {}
        if OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

        is_cloud = "ollama.com" in OLLAMA_URL
        if is_cloud and (not model or model == "llama3"):
            # The default local tag is meaningless in Ollama Cloud; substitute the configured
            # cloud model, stripping any provider suffix (e.g. ':cloud') that local proxy configs use.
            model = (DEFAULT_CLOUD_MODEL or "kimi-k2.7-code").split(":")[0]

        if is_cloud:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.0},
            }
            endpoint = f"{OLLAMA_URL}/api/chat"
        else:
            payload = {
                "model": model,
                "system": system_prompt,
                "prompt": user_prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.0},
            }
            endpoint = f"{OLLAMA_URL}/api/generate"

        resp = requests.post(endpoint, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        if is_cloud:
            return data.get("message", {}).get("content", "")
        return data.get("response", "")
    
    return breaker.call(_do_request)


@with_retry(LLM_RETRY)
def _ask_anthropic(system_prompt: str, user_prompt: str, model: str) -> str:
    """Send a messages request to the Anthropic-compatible cloud API."""
    breaker = get_anthropic_breaker()
    
    def _do_request():
        # Prefer the real API key, but fall back to the auth token for proxies that use it.
        api_key = ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN
        if not api_key:
            raise RuntimeError("Neither ANTHROPIC_API_KEY nor ANTHROPIC_AUTH_TOKEN is set; cannot use cloud provider.")

        # If the caller left the Ollama default in place, substitute the configured cloud model.
        model_id = model if model and model != "llama3" else DEFAULT_CLOUD_MODEL

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": model_id,
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": 0.0,
        }
        resp = requests.post(
            f"{ANTHROPIC_BASE_URL}/v1/messages",
            headers=headers,
            json=body,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("content") or []
        text_blocks = [block.get("text", "") for block in content if block.get("type") == "text"]
        if not text_blocks:
            raise ValueError("Anthropic response had no text content")
        return text_blocks[0]
    
    return breaker.call(_do_request)


def _extract_json(raw: str) -> dict[str, Any]:
    """Extract a JSON object from a response that may be wrapped in markdown fences."""
    raw = raw.strip()
    # Strip markdown code fences if present: keep the segment between the first pair.
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) >= 2 else raw
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fall back to the first {...} object in the response.
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in response")
        return json.loads(raw[start:end + 1])


def _parse_recommendation(raw: str) -> dict[str, Any]:
    """Parse and lightly validate the JSON recommendation."""
    parsed = _extract_json(raw)
    for key in ("tool_name", "arguments", "reasoning", "confidence"):
        if key not in parsed:
            raise ValueError(f"Missing key: {key}")
    parsed["confidence"] = float(parsed["confidence"])
    return parsed

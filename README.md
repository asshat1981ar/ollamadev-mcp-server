# ollamadev-mcp-server

Companion MCP server for the **OllamaDev** Android app, written with the **MCP Python SDK v2 beta**.

It exposes a comprehensive toolbox of **46 tools** that OllamaDev agents can invoke via `MCP_CALL:` directives during every SDLC sprint phase. It also includes an **agentic self-prompt** tool (`suggest_next_action`) that asks a local Ollama model which tool to call next.

## Server layout

```
ollamadev-mcp-server/
├── pyproject.toml
├── README.md
├── server.py                       # thin bootstrap
└── ollamadev_mcp_server/
    ├── constants.py
    └── tools/
        ├── filesystem.py           # list/read/write/delete/move files
        ├── code.py                 # search, outline, find symbol, todos
        ├── build.py                # gradle tests, lint, build, test parsing
        ├── sprint.py               # phase artifacts, backlog tasks, outcome eval
        ├── memory.py               # agent key/value memory
        ├── meta.py                 # describe_tools, suggest_next_action, ping
        ├── patch.py                # apply_file_patch
        ├── git_tools.py            # git status/diff/commit/log
        ├── dependencies.py         # add_gradle_dependency
        ├── observability.py        # get_task_transcript
        └── settings.py             # get/update/reset server settings
```

## Requirements

- Python ≥ 3.11
- [`uv`](https://github.com/astral-sh/uv) (recommended) or pip
- Optional: a local Ollama instance for the `suggest_next_action` tool (`OLLAMA_URL`)

## Run

```bash
# with uv
uv sync
uv run serve

# with pip in a venv
python3 -m venv .venv
.venv/bin/pip install -r pyproject.toml
.venv/bin/python3 server.py
```

Server starts on `http://0.0.0.0:5000/mcp`.

Override workspace path: `WORKSPACE_ROOT=/path/to/OllamaDev uv run serve`
Override Ollama URL: `OLLAMA_URL=http://localhost:11434 uv run serve`

## Connect from OllamaDev

1. Open OllamaDev → **MCP Servers** tab → **Add Server**
2. Name: `OllamaDev Tools`
3. Type: `Filesystem`
4. URL: `http://<your-machine-ip>:5000/mcp`
5. Tap **Connect** — status turns **Connected**, toolsCount = 36

## Tool catalog

### Filesystem

| Tool | Description | Phase |
|---|---|---|
| `list_workspace_files(root="")` | List relative file paths under the workspace | DISCOVERY |
| `read_workspace_file(path)` | Read a file by relative path | all |
| `write_workspace_file(path, content)` | Write/overwrite a file | IMPLEMENTATION |
| `delete_workspace_file(path)` | **Destructive**: delete a file | IMPLEMENTATION |
| `move_workspace_file(src, dst)` | Move/rename a file | IMPLEMENTATION |

### Code intelligence

| Tool | Description | Phase |
|---|---|---|
| `search_workspace(pattern, file_glob="*.kt")` | Grep across source files | DISCOVERY / VERIFICATION |
| `get_file_outline(path)` | Extract Kotlin signatures with line numbers | DESIGN |
| `find_symbol(name, symbol_type="any")` | Find a class/function/property declaration | DESIGN / INTEGRATION |
| `get_todos(file_glob="*.kt")` | Extract `TODO` / `FIXME` / `HACK` / `XXX` markers | INTEGRATION / RETROSPECTIVE |

### Surgical edits & dependencies

| Tool | Description | Phase |
|---|---|---|
| `apply_file_patch(path, patch)` | Apply a unified diff patch to an existing file | IMPLEMENTATION |
| `add_gradle_dependency(alias, group, name, version)` | Add a dependency to `libs.versions.toml` + module | IMPLEMENTATION |

### Build & verification

| Tool | Description | Phase |
|---|---|---|
| `run_gradle_tests(module="app", test_filter="")` | Run unit tests and return output | VERIFICATION |
| `run_gradle_build(module="app", variant="Debug")` | Compile-only build (`assembleDebug`) | VERIFICATION |
| `parse_test_results(gradle_output)` | Parse raw Gradle output into structured JSON | VERIFICATION |
| `run_lint(module="app")` | Run Android Lint | VERIFICATION |
| `run_ktlint_detekt(command="ktlint")` | Run ktlint/detekt if installed | VERIFICATION |
| `run_ktlint(args)` | Run ktlint (default: `app/src/main/java`) | VERIFICATION |
| `run_detekt(args)` | Run detekt (tries `detekt-cli`, then `detekt`) | VERIFICATION |
| `parse_test_results_xml(results_dir, raw_xml)` | Parse JUnit XML reports into structured JSON (totals + failure details) | VERIFICATION |
| `get_coverage_summary(results_dir)` | Parse a JaCoCo XML report into LINE/BRANCH/INSTRUCTION coverage | VERIFICATION / INTEGRATION |
| `run_instrumented_tests(module, variant, test_filter)` | Run `connectedAndroidTest` on a device/emulator (checks `adb devices` first) | VERIFICATION |
| `run_screenshot_tests(module, mode, test_filter)` | Roborazzi record/verify screenshot tests on the JVM (no emulator) | VERIFICATION |
| `get_build_config()` | Read `libs.versions.toml` and Gradle build files | INTEGRATION |

### Execution sandbox

| Tool | Description | Phase |
|---|---|---|
| `run_pytest(path="", test_filter="")` | Run pytest in the workspace and return structured pass/fail | VERIFICATION |
| `run_gradle_test_command(test_filter="")` | Run `./gradlew :app:testDebugUnitTest` and return structured pass/fail | VERIFICATION |
| `run_shell_command(command)` | **Destructive**: run arbitrary shell command in workspace root | VERIFICATION |
| `get_sandbox_status()` | Report pytest/gradlew availability and workspace root | VERIFICATION / META |

### Sprint workflow

| Tool | Description | Phase |
|---|---|---|
| `create_sprint_task(title, description, tier, priority)` | Append a task to `agent-os/backlog.md` | RETROSPECTIVE |
| `list_phase_artifacts(cycle_id)` | List `sprint-{id}-*.md` artifacts | RETROSPECTIVE |
| `read_phase_artifact(cycle_id, phase)` | Read a specific phase artifact | RETROSPECTIVE |
| `update_phase_artifact(cycle_id, phase, content)` | Overwrite a phase artifact | RETROSPECTIVE |
| `evaluate_sprint_outcome(cycle_id, phase, goal)` | Compare artifact to goal, return structured critique | RETROSPECTIVE |

### Memory

| Tool | Description | Phase |
|---|---|---|
| `store_memory(key, value)` | Persist a fact to `store/agent_memory.json` | RETROSPECTIVE |
| `recall_memory(key)` | Retrieve a stored fact | RETROSPECTIVE |
| `list_memories()` | List all memory keys | RETROSPECTIVE |
| `clear_memory(key)` | Delete one memory entry | RETROSPECTIVE |

### Git

| Tool | Description | Phase |
|---|---|---|
| `git_status_diff(path="", staged=False)` | Show `git status --short` + unified diff | INTEGRATION / RETROSPECTIVE |
| `git_commit_checkpoint(message, author_name, author_email)` | Stage all changes and commit | RETROSPECTIVE / INTEGRATION |
| `git_log(limit=10)` | Recent commit log | RETROSPECTIVE / INTEGRATION |

### Observability

| Tool | Description | Phase |
|---|---|---|
| `get_task_transcript(task_id, format="markdown")` | Read an exported task transcript | OBSERVABILITY |

### Meta / agentic

| Tool | Description |
|---|---|
| `ping()` | Server version and uptime |
| `describe_tools(category="all")` | Return a markdown catalog of tools |
| `suggest_next_action(goal, phase, context, model)` | Ask Ollama which tool to call next |

### Server settings

| Tool | Description | Phase |
|---|---|---|
| `get_server_settings()` | Read-only JSON snapshot of effective config (secrets masked) | META |
| `update_server_settings(settings)` | Persist config overrides to `store/server_settings.json` | META |
| `reset_server_settings()` | **Destructive**: delete the persisted settings file | META |

## Server settings

Settings are persisted as JSON (default: `<WORKSPACE_ROOT>/store/server_settings.json`,
overridable with the `OLLAMADEV_SETTINGS_FILE` env var) and follow the precedence:

```
environment variable  >  persisted settings file  >  code default
```

Allowed keys: `workspace_root`, `ollama_url`, `ollama_api_key`,
`anthropic_api_key`, `anthropic_auth_token`, `anthropic_base_url`,
`default_cloud_model`. Secret values are never echoed back in full — `get_server_settings`
reports them masked (`***`) with `*_set` flags.

```bash
# Read the effective configuration (env > persisted > default).
curl -s -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' -H 'MCP-Protocol-Version: 2025-06-18' \
  -H 'Mcp-Session-Id: <session-id>' \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_server_settings","arguments":{}}}'

# Persist an override (takes effect on next server restart).
curl -s -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' -H 'MCP-Protocol-Version: 2025-06-18' \
  -H 'Mcp-Session-Id: <session-id>' \
  -d '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"update_server_settings","arguments":{"settings":{"ollama_url":"http://10.0.2.2:11434"}}}}'
```

Constants are resolved once at server startup, so `update_server_settings` reports which
keys require a restart; the file itself is written atomically (temp file + rename).

## Agentic self-prompt (`suggest_next_action`)

If you run a local Ollama instance, agents can ask it to choose the next tool:

```
MCP_CALL: suggest_next_action | {
  "goal": "Add a Room migration for sprint tables",
  "phase": "IMPLEMENTATION",
  "context": "SprintCycle and SprintArtifact entities already exist in Entities.kt",
  "model": "llama3"
}
```

Response shape:
```json
{
  "tool_name": "search_workspace",
  "arguments": {"pattern": "@Database", "file_glob": "*.kt"},
  "reasoning": "Need to find the AppDatabase declaration before adding the migration.",
  "confidence": 0.92
}
```

If Ollama is not reachable, the tool returns a graceful JSON failure with `tool_name: null` and `confidence: 0`.

## Per-phase example directives

### DISCOVERY
```
MCP_CALL: list_workspace_files | {"root": "app/src/main/java/com/example/data"}
MCP_CALL: search_workspace | {"pattern": "class.*Dao", "context_lines": 0}
```

### DESIGN
```
MCP_CALL: get_file_outline | {"path": "app/src/main/java/com/example/data/Entities.kt"}
MCP_CALL: find_symbol | {"name": "AppDatabase", "symbol_type": "class"}
```

### IMPLEMENTATION
```
MCP_CALL: apply_file_patch | {"path": "app/src/main/java/com/example/data/Foo.kt", "patch": "--- a/...\n+++ b/...\n@@ ...\n"}
MCP_CALL: add_gradle_dependency | {"alias": "retrofit", "group": "com.squareup.retrofit2", "name": "retrofit", "version": "2.11.0"}
MCP_CALL: write_workspace_file | {"path": "app/src/main/java/com/example/data/NewRepo.kt", "content": "package..."}
MCP_CALL: move_workspace_file | {"src": "Old.kt", "dst": "New.kt"}
```

### VERIFICATION
```
MCP_CALL: run_gradle_build | {"module": "app", "variant": "Debug"}
MCP_CALL: run_gradle_tests | {"module": "app", "test_filter": "com.example.SprintOrchestratorTest"}
MCP_CALL: parse_test_results | {"gradle_output": "..."}
MCP_CALL: run_lint | {"module": "app"}
MCP_CALL: search_workspace | {"pattern": "TODO|FIXME"}
```

### INTEGRATION
```
MCP_CALL: git_status_diff | {}
MCP_CALL: get_build_config | {}
MCP_CALL: get_todos | {}
MCP_CALL: find_symbol | {"name": "SprintPhase", "symbol_type": "class"}
```

### RETROSPECTIVE
```
MCP_CALL: evaluate_sprint_outcome | {"cycle_id": 1, "phase": "verification"}
MCP_CALL: git_commit_checkpoint | {"message": "Sprint 1 checkpoint"}
MCP_CALL: create_sprint_task | {"title": "Wire SprintOrchestrator into UI", "description": "...", "tier": "4", "priority": "high"}
MCP_CALL: update_phase_artifact | {"cycle_id": 1, "phase": "retrospective", "content": "..."}
MCP_CALL: store_memory | {"key": "lesson-learned", "value": "..."}
```

## Risk gating

`delete_workspace_file` and `run_shell_command` are annotated with `destructiveHint=true` so OllamaDev's `isRiskyMcpCallReason()` gate triggers a user approval before destructive calls execute. The gate now records an `MCP_CALL_GATED` `TaskStep` before showing the approval dialog and surfaces the matched reason (annotation-based `destructiveHint=true` or the matched keyword) in `PendingApproval.detail`, rendered in the dialog as `Reason: ${approval.detail}`. `git_commit_checkpoint` also contains "commit" which may be flagged as a keyword match depending on the app's keyword list; the tool is additive and safe. All other tools are read-only or additive.

## Verify manually

```bash
# 1. Handshake
curl -s -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

# 2. List all 36 tools
curl -s -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  -H 'Mcp-Session-Id: <session-id>' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# 3. Call a tool
curl -s -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  -H 'Mcp-Session-Id: <session-id>' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"ping","arguments":{}}}'
```

## MCP Python SDK v2 — key changes from v1

| v1 | v2 |
|---|---|
| `from mcp import FastMCP` | `from mcp.server import MCPServer` |
| `app = FastMCP("name")` | `mcp = MCPServer("name")` |
| Transport in constructor | `mcp.run(transport="streamable-http", host=..., port=...)` |
| `isError`, `inputSchema` (camelCase) | `is_error`, `input_schema` (snake_case) |
| Sync tools block event loop | Sync tools run on worker threads automatically |
| Server callbacks for missing args | `Elicit` / `InputRequiredResult` pattern |
| Manual JSON Schema | Type hints auto-converted to JSON Schema |
| Add `mcp>=1.27,<2` to your deps | Pin exact: `mcp[cli]==2.0.0rc1` for pre-release |

Full article: https://pydantic.dev/articles/mcp-python-sdk-v2-beta  
Migration guide: https://py.sdk.modelcontextprotocol.io/v2/migration/

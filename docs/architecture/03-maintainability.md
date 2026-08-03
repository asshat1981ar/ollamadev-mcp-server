# Phase 3: Maintainability

> **Status:** DESIGN  
> **Priority:** P1  
> **Estimated Effort:** 3-4 days  
> **Dependencies:** Phase 1 (logging, errors), Phase 2 (auth context)  

---

## 1. Executive Summary

Phase 3 addresses long-term maintainability concerns: the hardcoded tool catalog in `meta.py` that drifts from reality, global constants that make testing fragile, and the lack of type-safe tool definitions. These issues slow development and increase the risk of bugs when adding or modifying tools.

### Deliverables

| Component | Module | Lines (est.) |
|-----------|--------|-------------|
| Dynamic tool catalog | `catalog.py` | ~150 |
| Configuration object | `config.py` | ~120 |
| Config hot-reload | `config_watcher.py` | ~100 |
| Type-safe tool schemas | `schemas.py` | ~200 |
| Plugin-style registration | `registry.py` | ~100 |
| Refactored modules | Various | ~300 |
| Tests | `tests/test_phase3_*.py` | ~400 |
| **Total** | | **~1,370** |

---

## 2. Current State Analysis

### 2.1 Hardcoded Tool Catalog

**Evidence:** `meta.py:29-200` — A 200+ line static `_TOOL_CATALOG` list:

```python
_TOOL_CATALOG: list[dict[str, Any]] = [
    {
        "name": "list_workspace_files",
        "phase": "DISCOVERY",
        "params": {"root": "subdirectory to list (optional)"},
        "example": "MCP_CALL: list_workspace_files | {\"root\": \"app/src/main/java/com/example\"}",
    },
    # ... 45 more entries ...
]
```

**Problems:**
- When a tool is added/removed/renamed, someone must manually update this list
- No automated check that catalog matches actual registered tools
- `describe_tools` returns stale data if catalog is not updated
- `suggest_next_action` uses this catalog — stale data leads to bad suggestions

### 2.2 Global Constants

**Evidence:** `constants.py:17` — Import-time resolution:

```python
_PERSISTED = load_persisted_settings()  # Executed at import time

WORKSPACE_ROOT = Path(_resolve("workspace_root", "/home/userland/OllamaDev")).resolve()
OLLAMA_URL = _resolve("ollama_url", "http://localhost:11434").rstrip("/")
```

**Problems:**
- Tests must monkeypatch module-level variables (see `test_sprint.py:17-23`)
- Settings changes require server restart
- No way to override config per-request
- Circular import risk between `constants.py` and `persistence.py`

### 2.3 No Type Validation

**Evidence:** Tool functions accept raw types with no schema validation:

```python
# sprint.py:66
def create_sprint_task(
    title: str,
    description: str = "",
    tier: str = "3",
    priority: str = "medium",
) -> str:
```

The tier and priority values are validated inside the function body, but there's no schema-level enforcement. Invalid values cause runtime errors instead of clear validation messages.

### 2.4 Tight Coupling

**Evidence:** Modules import directly from `constants`:

```python
# filesystem.py:9
from ollamadev_mcp_server.constants import WORKSPACE_ROOT

# code.py:9
from ollamadev_mcp_server.constants import WORKSPACE_ROOT

# build.py:11
from ollamadev_mcp_server.constants import WORKSPACE_ROOT
```

All 12 tool modules import `WORKSPACE_ROOT` directly. Changing the workspace root requires modifying the global constant.

---

## 3. Proposed Architecture

### 3.1 Dynamic Tool Catalog

**Design:** Auto-generate the tool catalog from registered MCP tools.

```python
# ollamadev_mcp_server/catalog.py
"""Dynamic tool catalog generation from registered MCP tools."""

import json
from typing import Any

from mcp.server import MCPServer

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

# Phase tags for known tools. Tools not listed here get phase="GENERAL".
_TOOL_PHASES: dict[str, str] = {
    "list_workspace_files": "DISCOVERY",
    "read_workspace_file": "DISCOVERY/DESIGN/IMPLEMENTATION/VERIFICATION",
    "write_workspace_file": "IMPLEMENTATION",
    "delete_workspace_file": "IMPLEMENTATION",
    "move_workspace_file": "IMPLEMENTATION",
    "search_workspace": "DISCOVERY/VERIFICATION",
    "get_file_outline": "DESIGN",
    "find_symbol": "DESIGN/INTEGRATION",
    "get_todos": "INTEGRATION/RETROSPECTIVE",
    "apply_file_patch": "IMPLEMENTATION",
    "add_gradle_dependency": "IMPLEMENTATION",
    "run_gradle_tests": "VERIFICATION",
    "run_gradle_build": "VERIFICATION",
    "run_gradle_test_command": "VERIFICATION",
    "parse_test_results": "VERIFICATION",
    "parse_test_results_xml": "VERIFICATION",
    "parse_coverage_xml": "VERIFICATION",
    "run_lint": "VERIFICATION",
    "run_detekt": "VERIFICATION",
    "run_ktlint": "VERIFICATION",
    "get_build_config": "INTEGRATION",
    "run_instrumented_tests": "VERIFICATION",
    "run_screenshot_tests": "VERIFICATION",
    "create_sprint_task": "all",
    "list_phase_artifacts": "all",
    "read_phase_artifact": "all",
    "update_phase_artifact": "all",
    "evaluate_sprint_outcome": "RETROSPECTIVE",
    "run_autonomous_sprint": "all",
    "store_memory": "RETROSPECTIVE",
    "recall_memory": "all",
    "list_memories": "all",
    "clear_memory": "RETROSPECTIVE",
    "describe_tools": "all",
    "suggest_next_action": "all",
    "ping": "all",
    "get_server_health": "all",
    "git_status_diff": "INTEGRATION/RETROSPECTIVE",
    "git_commit_checkpoint": "INTEGRATION/RETROSPECTIVE",
    "git_log": "INTEGRATION/RETROSPECTIVE",
    "run_pytest": "VERIFICATION",
    "run_shell_command": "VERIFICATION",
    "get_sandbox_status": "all",
    "get_server_settings": "all",
    "update_server_settings": "all",
    "reset_server_settings": "all",
    "get_task_transcript": "VERIFICATION",
    "get_audit_log": "all",
}


def build_tool_catalog(mcp: MCPServer) -> list[dict[str, Any]]:
    """Build a tool catalog from the registered tools on the MCP server.
    
    This replaces the hardcoded _TOOL_CATALOG in meta.py.
    """
    catalog = []
    
    # Get all registered tools from the MCP server
    # The MCP SDK stores tools internally; we access them via the server's tool list
    try:
        tools = mcp._tool_manager._tools if hasattr(mcp, '_tool_manager') else {}
    except AttributeError:
        tools = {}
    
    for name, tool in tools.items():
        entry = {
            "name": name,
            "phase": _TOOL_PHASES.get(name, "GENERAL"),
            "description": tool.description if hasattr(tool, 'description') else "",
        }
        
        # Extract parameter info from the tool's input schema
        if hasattr(tool, 'parameters'):
            params = {}
            for param_name, param_info in tool.parameters.items():
                param_type = param_info.get("type", "string") if isinstance(param_info, dict) else "string"
                params[param_name] = param_type
            entry["params"] = params
        
        catalog.append(entry)
    
    # Sort by name for consistent output
    catalog.sort(key=lambda x: x["name"])
    
    logger.info("Built dynamic tool catalog with %d tools", len(catalog))
    return catalog


def get_tools_by_phase(catalog: list[dict[str, Any]], phase: str) -> list[dict[str, Any]]:
    """Filter catalog entries by phase."""
    phase_upper = phase.upper()
    return [
        entry for entry in catalog
        if phase_upper in entry.get("phase", "").upper()
        or entry.get("phase", "").lower() == "all"
    ]


def get_tool_by_name(catalog: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Find a tool in the catalog by name."""
    for entry in catalog:
        if entry["name"] == name:
            return entry
    return None


def validate_catalog(mcp: MCPServer) -> list[str]:
    """Validate that the catalog matches registered tools. Returns list of issues."""
    issues = []
    catalog = build_tool_catalog(mcp)
    catalog_names = {entry["name"] for entry in catalog}
    
    # Check for tools in _TOOL_PHASES that aren't registered
    try:
        tools = mcp._tool_manager._tools if hasattr(mcp, '_tool_manager') else {}
    except AttributeError:
        tools = {}
    registered_names = set(tools.keys())
    
    missing_from_registry = catalog_names - registered_names
    if missing_from_registry:
        issues.append(f"Tools in catalog but not registered: {missing_from_registry}")
    
    untagged = registered_names - catalog_names - set(_TOOL_PHASES.keys())
    if untagged:
        issues.append(f"Registered tools without phase tags: {untagged}")
    
    return issues
```

### 3.2 Configuration Object

**Design:** Replace global constants with a config object that can be injected.

```python
# ollamadev_mcp_server/config.py
"""Server configuration management."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ollamadev_mcp_server.logging_config import get_logger
from ollamadev_mcp_server.persistence import load_persisted_settings, settings_file_path

logger = get_logger(__name__)


@dataclass(frozen=True)
class ServerConfig:
    """Immutable server configuration."""
    
    # Workspace
    workspace_root: Path
    store_dir: Path
    
    # Ollama
    ollama_url: str
    ollama_api_key: str
    
    # Cloud provider
    anthropic_api_key: str
    anthropic_auth_token: str
    anthropic_base_url: str
    default_cloud_model: str
    
    # Sprint
    sprint_phases: list[str] = field(default_factory=lambda: [
        "discovery", "design", "implementation",
        "verification", "integration", "retrospective",
    ])
    
    # Server
    host: str = "0.0.0.0"
    port: int = 5000
    
    # Timeouts
    default_tool_timeout: int = 60
    default_llm_timeout: int = 120
    default_shell_timeout: int = 300
    default_gradle_timeout: int = 600
    default_autonomous_timeout: int = 3600
    
    # Security
    auth_enabled: bool = False
    api_key: str = ""
    api_key_hash: str = ""
    rate_limit_enabled: bool = True
    default_rate_limit: int = 100
    cors_enabled: bool = True
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "json"
    
    @property
    def settings_file(self) -> Path:
        return settings_file_path()


def _resolve(key: str, default: str, persisted: dict[str, str]) -> str:
    """Resolve a config value: env var > persisted > default."""
    env_key = key.upper()
    if env_key in os.environ:
        return os.environ[env_key]
    value = persisted.get(key)
    if value not in (None, ""):
        return str(value)
    return default


def load_config() -> ServerConfig:
    """Load server configuration from environment and persisted settings."""
    persisted = load_persisted_settings()
    
    workspace_root = Path(_resolve("workspace_root", "/home/userland/OllamaDev", persisted)).resolve()
    
    return ServerConfig(
        workspace_root=workspace_root,
        store_dir=workspace_root / "store",
        ollama_url=_resolve("ollama_url", "http://localhost:11434", persisted).rstrip("/"),
        ollama_api_key=_resolve("ollama_api_key", "", persisted),
        anthropic_api_key=_resolve("anthropic_api_key", "", persisted),
        anthropic_auth_token=_resolve("anthropic_auth_token", "", persisted),
        anthropic_base_url=_resolve("anthropic_base_url", "https://api.anthropic.com", persisted).rstrip("/"),
        default_cloud_model=(
            os.environ.get("ANTHROPIC_DEFAULT_MODEL")
            or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
            or persisted.get("default_cloud_model")
            or "claude-sonnet-5-20251001"
        ),
        host=os.environ.get("SERVER_HOST", "0.0.0.0"),
        port=int(os.environ.get("SERVER_PORT", "5000")),
        default_tool_timeout=int(os.environ.get("DEFAULT_TOOL_TIMEOUT", "60")),
        default_llm_timeout=int(os.environ.get("DEFAULT_LLM_TIMEOUT", "120")),
        default_shell_timeout=int(os.environ.get("DEFAULT_SHELL_TIMEOUT", "300")),
        default_gradle_timeout=int(os.environ.get("DEFAULT_GRADLE_TIMEOUT", "600")),
        default_autonomous_timeout=int(os.environ.get("DEFAULT_AUTONOMOUS_TIMEOUT", "3600")),
        auth_enabled=os.environ.get("AUTH_ENABLED", "false").lower() == "true",
        api_key=os.environ.get("API_KEY", ""),
        api_key_hash=os.environ.get("API_KEY_HASH", ""),
        rate_limit_enabled=os.environ.get("RATE_LIMIT_ENABLED", "true").lower() == "true",
        default_rate_limit=int(os.environ.get("DEFAULT_RATE_LIMIT", "100")),
        cors_enabled=os.environ.get("CORS_ENABLED", "true").lower() == "true",
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        log_format=os.environ.get("LOG_FORMAT", "json").lower(),
    )


# Global config instance (replaces constants.py)
_config: ServerConfig | None = None


def get_config() -> ServerConfig:
    """Get the global server config. Loads on first access."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> ServerConfig:
    """Reload configuration from disk/environment."""
    global _config
    _config = load_config()
    logger.info("Configuration reloaded")
    return _config


def override_config(**overrides: Any) -> ServerConfig:
    """Create a config with overrides (for testing)."""
    base = get_config()
    # frozen dataclass — create a new one with overrides
    import dataclasses
    return dataclasses.replace(base, **overrides)
```

### 3.3 Configuration Hot-Reload

**Design:** Watch the settings file for changes and reload automatically.

```python
# ollamadev_mcp_server/config_watcher.py
"""File watcher for configuration hot-reload."""

import os
import threading
import time
from pathlib import Path

from ollamadev_mcp_server.config import reload_config, get_config
from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)


class ConfigWatcher:
    """Watch the settings file for changes and reload config."""

    def __init__(self, poll_interval: float = 5.0):
        self._poll_interval = poll_interval
        self._last_mtime: float = 0
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start watching for config changes."""
        if self._running:
            return
        
        config = get_config()
        settings_file = config.settings_file
        
        if settings_file.exists():
            self._last_mtime = settings_file.stat().st_mtime
        
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        logger.info("Config watcher started (polling every %.1fs)", self._poll_interval)

    def stop(self) -> None:
        """Stop watching for config changes."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("Config watcher stopped")

    def _watch_loop(self) -> None:
        """Background loop that checks for file changes."""
        while self._running:
            try:
                config = get_config()
                settings_file = config.settings_file
                
                if settings_file.exists():
                    mtime = settings_file.stat().st_mtime
                    if mtime > self._last_mtime:
                        logger.info("Settings file changed, reloading config")
                        reload_config()
                        self._last_mtime = mtime
                elif self._last_mtime > 0:
                    # File was deleted
                    logger.info("Settings file deleted, reloading config")
                    reload_config()
                    self._last_mtime = 0
            except Exception:
                logger.exception("Error in config watcher")
            
            time.sleep(self._poll_interval)
```

### 3.4 Type-Safe Tool Schemas

**Design:** Pydantic models for tool input validation.

```python
# ollamadev_mcp_server/schemas.py
"""Type-safe tool input schemas using Pydantic."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# --- Enums ---

class SprintPhase(str, Enum):
    DISCOVERY = "discovery"
    DESIGN = "design"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    INTEGRATION = "integration"
    RETROSPECTIVE = "retrospective"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SymbolType(str, Enum):
    ANY = "any"
    CLASS = "class"
    FUNCTION = "function"
    PROPERTY = "property"


class ScreenshotMode(str, Enum):
    RECORD = "record"
    VERIFY = "verify"


class TranscriptFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


# --- Filesystem Schemas ---

class ListFilesInput(BaseModel):
    root: str = Field(default="", description="Sub-path within workspace to list")

    @field_validator("root")
    @classmethod
    def validate_root(cls, v: str) -> str:
        if ".." in v:
            raise ValueError("Path traversal not allowed")
        return v


class ReadFileInput(BaseModel):
    path: str = Field(description="Relative path to file")

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        if not v:
            raise ValueError("Path cannot be empty")
        if ".." in v:
            raise ValueError("Path traversal not allowed")
        return v


class WriteFileInput(BaseModel):
    path: str = Field(description="Relative path to file")
    content: str = Field(description="File content")
    create_dirs: bool = Field(default=True, description="Create parent directories")

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        if not v:
            raise ValueError("Path cannot be empty")
        if ".." in v:
            raise ValueError("Path traversal not allowed")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 10 * 1024 * 1024:
            raise ValueError("Content exceeds 10MB limit")
        return v


# --- Code Intelligence Schemas ---

class SearchInput(BaseModel):
    pattern: str = Field(description="Regex pattern to search for")
    file_glob: str = Field(default="*.kt", description="File glob pattern")
    ignore_case: bool = Field(default=False, description="Case-insensitive search")
    context_lines: int = Field(default=2, ge=0, le=100, description="Context lines around matches")


class FindSymbolInput(BaseModel):
    name: str = Field(description="Symbol name to find")
    symbol_type: SymbolType = Field(default=SymbolType.ANY, description="Type of symbol")
    file_glob: str = Field(default="*.kt", description="File glob pattern")


# --- Sprint Schemas ---

class CreateTaskInput(BaseModel):
    title: str = Field(description="Task title")
    description: str = Field(default="", description="Task description")
    tier: str = Field(default="3", description="Task tier (1-5)")
    priority: Priority = Field(default=Priority.MEDIUM, description="Task priority")

    @field_validator("tier")
    @classmethod
    def validate_tier(cls, v: str) -> str:
        try:
            tier_int = int(v)
            if tier_int < 1 or tier_int > 5:
                raise ValueError("Tier must be between 1 and 5")
        except ValueError:
            raise ValueError(f"Invalid tier: {v}")
        return v


class PhaseArtifactInput(BaseModel):
    cycle_id: int = Field(ge=1, description="Sprint cycle ID")
    phase: SprintPhase = Field(description="Sprint phase")


class EvaluateOutcomeInput(BaseModel):
    cycle_id: int = Field(ge=1, description="Sprint cycle ID")
    phase: SprintPhase = Field(description="Sprint phase to evaluate")


# --- Build Schemas ---

class GradleTestInput(BaseModel):
    module: str = Field(default="app", description="Gradle module")
    test_filter: str = Field(default="", description="Test class filter")
    timeout_seconds: int = Field(default=600, ge=10, le=3600, description="Timeout in seconds")


class GradleBuildInput(BaseModel):
    module: str = Field(default="app", description="Gradle module")
    variant: str = Field(default="Debug", description="Build variant")
    timeout_seconds: int = Field(default=600, ge=10, le=3600, description="Timeout in seconds")


# --- Sandbox Schemas ---

class ShellCommandInput(BaseModel):
    command: str = Field(description="Shell command to execute")
    timeout_seconds: int = Field(default=300, ge=1, le=3600, description="Timeout in seconds")


class PytestInput(BaseModel):
    path: str = Field(default="", description="Directory or file to test")
    test_filter: str = Field(default="", description="pytest -k filter")
    timeout_seconds: int = Field(default=300, ge=10, le=3600, description="Timeout in seconds")


# --- Settings Schemas ---

class UpdateSettingsInput(BaseModel):
    settings: dict[str, str] = Field(description="Settings key-value pairs")

    @field_validator("settings")
    @classmethod
    def validate_settings(cls, v: dict[str, str]) -> dict[str, str]:
        allowed_keys = {
            "workspace_root", "ollama_url", "ollama_api_key",
            "anthropic_api_key", "anthropic_auth_token",
            "anthropic_base_url", "default_cloud_model",
        }
        unknown = set(v.keys()) - allowed_keys
        if unknown:
            raise ValueError(f"Unknown setting keys: {unknown}")
        for key, value in v.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Setting '{key}' must be a non-empty string")
        return v
```

### 3.5 Plugin-Style Tool Registration

**Design:** A registry that tracks tool modules and their metadata.

```python
# ollamadev_mcp_server/registry.py
"""Tool module registry for plugin-style registration."""

from dataclasses import dataclass, field
from typing import Any, Callable

from mcp.server import MCPServer

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ToolModule:
    """Metadata for a registered tool module."""
    name: str
    module: Any
    register_fn: Callable[[MCPServer], None]
    category: str
    description: str
    tool_count: int = 0  # Filled after registration


class ToolRegistry:
    """Registry of tool modules."""

    def __init__(self):
        self._modules: list[ToolModule] = []

    def register_module(
        self,
        name: str,
        module: Any,
        category: str,
        description: str,
    ) -> None:
        """Register a tool module."""
        self._modules.append(ToolModule(
            name=name,
            module=module,
            register_fn=module.register,
            category=category,
            description=description,
        ))
        logger.debug("Registered tool module: %s (%s)", name, category)

    def register_all(self, mcp: MCPServer) -> None:
        """Register all modules with the MCP server."""
        for mod in self._modules:
            mod.register_fn(mcp)
            logger.info("Registered module: %s (%s)", mod.name, mod.category)

    def get_modules(self) -> list[ToolModule]:
        """Get all registered modules."""
        return list(self._modules)

    def get_module(self, name: str) -> ToolModule | None:
        """Get a module by name."""
        for mod in self._modules:
            if mod.name == name:
                return mod
        return None


# Global registry
_registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    """Get the global tool registry."""
    return _registry


def register_default_modules() -> None:
    """Register all default tool modules."""
    from ollamadev_mcp_server.tools import (
        build, code, dependencies, filesystem, git_tools,
        memory, meta, observability, patch, sandbox, settings, sprint,
    )

    _registry.register_module("filesystem", filesystem, "filesystem", "File read/write/delete/move")
    _registry.register_module("code", code, "code_intelligence", "Search, outline, symbol finding")
    _registry.register_module("build", build, "build_verification", "Gradle, lint, test parsing")
    _registry.register_module("sprint", sprint, "workflow", "Sprint phases, backlog, autonomous loop")
    _registry.register_module("memory", memory, "agent_state", "Key-value agent memory")
    _registry.register_module("meta", meta, "meta", "Tool catalog, suggestions, ping")
    _registry.register_module("patch", patch, "editing", "Unified diff patch application")
    _registry.register_module("git_tools", git_tools, "version_control", "Git status, diff, commit, log")
    _registry.register_module("dependencies", dependencies, "build", "Gradle dependency management")
    _registry.register_module("observability", observability, "debugging", "Task transcript reading")
    _registry.register_module("sandbox", sandbox, "execution", "Pytest, Gradle, shell execution")
    _registry.register_module("settings", settings, "configuration", "Server settings management")
```

---

## 4. Implementation Plan

### Step 1: Configuration Object (Day 1)
1. Create `config.py` with `ServerConfig` dataclass
2. Migrate `constants.py` to use `config.py` internally
3. Update all modules to use `get_config()` instead of direct imports
4. Write `tests/test_config.py`

### Step 2: Dynamic Tool Catalog (Day 2)
1. Create `catalog.py` with `build_tool_catalog()`
2. Update `meta.py` to use dynamic catalog
3. Add catalog validation tool
4. Write `tests/test_catalog.py`

### Step 3: Type-Safe Schemas (Day 2-3)
1. Create `schemas.py` with Pydantic models
2. Add schema validation to tool functions
3. Write `tests/test_schemas.py`

### Step 4: Config Hot-Reload (Day 3)
1. Create `config_watcher.py`
2. Integrate into server startup
3. Write `tests/test_config_watcher.py`

### Step 5: Tool Registry (Day 3-4)
1. Create `registry.py`
2. Update `server.py` to use registry
3. Write `tests/test_registry.py`

### Step 6: Migration and Verification (Day 4)
1. Run full test suite
2. Verify all tools still work
3. Update README

---

## 5. Impact Assessment

### 5.1 Backward Compatibility

| Change | Breaking? | Migration |
|--------|-----------|-----------|
| Config object | Internal | No API change for tools |
| Dynamic catalog | Internal | `describe_tools` output format unchanged |
| Pydantic schemas | Partial | Invalid inputs get clearer error messages |
| Config hot-reload | Additive | Opt-in via environment variable |
| Tool registry | Internal | `server.py` startup changes only |

### 5.2 New Dependencies

| Dependency | Version | Purpose |
|-----------|---------|--------|
| `pydantic` | `>=2.0` | Type-safe schemas (already transitive via MCP SDK) |

### 5.3 Deprecated

| Item | Replacement | Timeline |
|------|------------|----------|
| `constants.py` globals | `config.py` `ServerConfig` | Phase out over 2 releases |
| Hardcoded `_TOOL_CATALOG` | `catalog.py` `build_tool_catalog()` | Immediate |

---

## 6. Verification Plan

### 6.1 Unit Tests

```bash
pytest tests/test_config.py tests/test_catalog.py tests/test_schemas.py \
       tests/test_config_watcher.py tests/test_registry.py -v
```

### 6.2 Integration Tests

```bash
# Verify dynamic catalog matches registered tools
python -c "
from mcp.server import MCPServer
from ollamadev_mcp_server.catalog import build_tool_catalog, validate_catalog
from ollamadev_mcp_server.registry import get_registry, register_default_modules

register_default_modules()
mcp = MCPServer('Test')
get_registry().register_all(mcp)

issues = validate_catalog(mcp)
if issues:
    print('ISSUES:', issues)
else:
    print('Catalog is consistent')
"
```

### 6.3 Regression Tests

```bash
pytest -q
# Expected: All existing tests pass
```

---

## 7. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Config reload race condition | Use atomic file reads; lock during reload |
| Pydantic validation breaks existing tools | Start with optional validation; enable per-tool |
| Dynamic catalog misses tool metadata | Fall back to hardcoded phases for known tools |
| Registry changes break server startup | Keep `server.py` backward compatible |

---

## 8. Success Criteria

- [ ] No more hardcoded tool catalog
- [ ] `describe_tools` output always matches registered tools
- [ ] Configuration is injectable for testing
- [ ] Settings changes apply without restart (when watcher enabled)
- [ ] Tool inputs are validated with clear error messages
- [ ] All existing tests pass
- [ ] New test coverage > 90% for new modules

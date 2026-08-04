"""Tool module registry for plugin-style registration.

Provides a ``ToolRegistry`` that tracks tool modules and their metadata,
enabling dynamic discovery and registration.  Replaces the manual
registration calls in ``server.py`` with a declarative approach.

Usage::

    from ollamadev_mcp_server.registry import get_registry, register_default_modules

    register_default_modules()
    registry = get_registry()
    registry.register_all(mcp)
"""

from dataclasses import dataclass
from typing import Any, Callable

from mcp.server import MCPServer

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Tool module metadata
# ---------------------------------------------------------------------------


@dataclass
class ToolModule:
    """Metadata for a registered tool module.

    Attributes:
        name: Module name (e.g. "filesystem", "code").
        module: The module object.
        register_fn: The ``register(mcp)`` function.
        category: Category for grouping (e.g. "filesystem", "code_intelligence").
        description: Human-readable description.
        tool_count: Number of tools registered (filled after registration).
    """

    name: str
    module: Any
    register_fn: Callable[[MCPServer], None]
    category: str
    description: str
    tool_count: int = 0


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Registry of tool modules.

    Tracks all registered modules and provides methods to register them
    with an MCP server instance.
    """

    def __init__(self) -> None:
        self._modules: list[ToolModule] = []

    def register_module(
        self,
        name: str,
        module: Any,
        category: str,
        description: str,
    ) -> None:
        """Register a tool module.

        Args:
            name: Module name.
            module: The module object (must have a ``register(mcp)`` function).
            category: Category for grouping.
            description: Human-readable description.
        """
        if not hasattr(module, "register"):
            raise ValueError(f"Module {name} does not have a register() function")

        self._modules.append(
            ToolModule(
                name=name,
                module=module,
                register_fn=module.register,
                category=category,
                description=description,
            )
        )
        logger.debug("Registered tool module: %s (%s)", name, category)

    def register_all(self, mcp: MCPServer) -> None:
        """Register all modules with the MCP server.

        Calls each module's ``register(mcp)`` function in the order they
        were added.

        Args:
            mcp: The MCP server instance.
        """
        for mod in self._modules:
            mod.register_fn(mcp)
            logger.info("Registered module: %s (%s)", mod.name, mod.category)

    def get_modules(self) -> list[ToolModule]:
        """Get all registered modules.

        Returns:
            List of ``ToolModule`` instances.
        """
        return list(self._modules)

    def get_module(self, name: str) -> ToolModule | None:
        """Get a module by name.

        Args:
            name: Module name.

        Returns:
            ``ToolModule`` if found, else ``None``.
        """
        for mod in self._modules:
            if mod.name == name:
                return mod
        return None

    def get_modules_by_category(self, category: str) -> list[ToolModule]:
        """Get all modules in a category.

        Args:
            category: Category name.

        Returns:
            List of ``ToolModule`` instances in the category.
        """
        return [mod for mod in self._modules if mod.category == category]

    def clear(self) -> None:
        """Clear all registered modules (for testing)."""
        self._modules.clear()


# ---------------------------------------------------------------------------
# Global registry
# ---------------------------------------------------------------------------

_registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    """Get the global tool registry."""
    return _registry


def register_default_modules() -> None:
    """Register all default tool modules.

    Imports all tool modules and registers them with the global registry.
    """
    from ollamadev_mcp_server.tools import (
        build,
        cloudflare_computer,
        code,
        dependencies,
        filesystem,
        git_tools,
        memory,
        meta,
        observability,
        patch,
        sandbox,
        settings,
        sprint,
    )

    registry = get_registry()
    registry.clear()  # Clear any previous registrations

    registry.register_module("filesystem", filesystem, "filesystem", "File read/write/delete/move")
    registry.register_module("code", code, "code_intelligence", "Search, outline, symbol finding")
    registry.register_module("build", build, "build_verification", "Gradle, lint, test parsing")
    registry.register_module("sprint", sprint, "workflow", "Sprint phases, backlog, autonomous loop")
    registry.register_module("memory", memory, "agent_state", "Key-value agent memory")
    registry.register_module("meta", meta, "meta", "Tool catalog, suggestions, ping")
    registry.register_module("patch", patch, "editing", "Unified diff patch application")
    registry.register_module("git_tools", git_tools, "version_control", "Git status, diff, commit, log")
    registry.register_module("dependencies", dependencies, "build", "Gradle dependency management")
    registry.register_module("observability", observability, "debugging", "Task transcript reading")
    registry.register_module("sandbox", sandbox, "execution", "Pytest, Gradle, shell execution")
    registry.register_module("settings", settings, "configuration", "Server settings management")
    registry.register_module(
        "cloudflare_computer",
        cloudflare_computer,
        "cloud_computer",
        "Cloudflare Computer virtual workspace (read/write/list/exec/git over HTTP)",
    )

    logger.info("Registered %d default tool modules", len(registry.get_modules()))

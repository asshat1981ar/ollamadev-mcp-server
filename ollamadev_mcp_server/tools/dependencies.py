"""Dependency-management tools for the OllamaDev Android project."""

import re
from pathlib import Path

from mcp.server import MCPServer

from ollamadev_mcp_server.constants import WORKSPACE_ROOT
from ollamadev_mcp_server.tools.filesystem import _safe_path
from ollamadev_mcp_server.tool_decorator import tool_runtime
from ollamadev_mcp_server.tool_runtime import ToolContext


def _to_camel_alias(name: str) -> str:
    """Convert a kebab/snake name to a camelCase alias suitable for libs.versions.toml keys."""
    parts = re.split(r"[-_.]", name)
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _to_kebab_key(name: str) -> str:
    return re.sub(r"[_.]", "-", name).lower()


def _insert_before_section(text: str, section_header: str, new_line: str) -> str:
    """Insert a new line before the first occurrence of a section header, or append if absent."""
    match = re.search(rf"(^|\n){re.escape(section_header)}\s*\n", text)
    if not match:
        return text.rstrip() + "\n" + new_line + "\n"
    pos = match.start()
    return text[:pos] + new_line + "\n" + text[pos:]


def _add_version_to_catalog(text: str, alias: str, version: str) -> str:
    version_line = f'{alias} = "{version}"'
    # Insert just before [libraries] if [versions] exists, else append to [versions].
    if "[versions]" not in text:
        text = "[versions]\n" + text
    return _insert_before_section(text, "[libraries]", version_line)


def _add_library_to_catalog(text: str, kebab_key: str, group: str, name: str, alias: str) -> str:
    lib_line = f'{kebab_key} = {{ group = "{group}", name = "{name}", version.ref = "{alias}" }}'
    if "[libraries]" not in text:
        text = text.rstrip() + "\n\n[libraries]\n" + lib_line + "\n"
        return text
    # Insert just before [plugins] or [bundles] or end.
    for next_section in ("[plugins]", "[bundles]", "[metadata]"):
        if next_section in text:
            return _insert_before_section(text, next_section, lib_line)
    return text.rstrip() + "\n" + lib_line + "\n"


def _add_dependency_to_build_gradle(text: str, config: str, reference: str) -> str:
    """Insert a dependency line into the dependencies { } block of a build.gradle.kts file."""
    dep_line = f"  {config}({reference})"
    # Find dependencies block
    dep_block_match = re.search(r"dependencies\s*\{\s*\n", text)
    if not dep_block_match:
        # Append a new block at the end
        return text.rstrip() + f"\n\ndependencies {{\n{dep_line}\n}}\n"

    insert_pos = dep_block_match.end()
    return text[:insert_pos] + dep_line + "\n" + text[insert_pos:]


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    @tool_runtime(name="add_gradle_dependency")
    def add_gradle_dependency(
        ctx: ToolContext = None,
        alias: str = "",
        group: str = "",
        name: str = "",
        version: str = "",
        module: str = "app",
        configuration: str = "implementation",
        add_to_catalog: bool = True,
    ) -> str:
        """Add a Gradle dependency to the OllamaDev project.

        Args:
            alias:         Catalog alias / variable name, e.g. 'retrofit' or 'okhttp'.
            group:         Maven group, e.g. 'com.squareup.retrofit2'.
            name:          Maven artifact name, e.g. 'retrofit'.
            version:       Version string, e.g. '2.11.0'.
            module:        Gradle module to add the dependency to (default: 'app').
            configuration: Dependency configuration: implementation, api, testImplementation, etc.
            add_to_catalog: If True, add a version + library entry to libs.versions.toml and reference it.
                            If False, add the dependency inline in build.gradle.kts.

        Returns:
            Confirmation message describing what was changed.
        """
        catalog_path = _safe_path("gradle/libs.versions.toml")
        build_gradle = _safe_path(f"{module}/build.gradle.kts")
        if not build_gradle.exists():
            raise FileNotFoundError(f"Module build file not found: {module}/build.gradle.kts")

        camel_alias = _to_camel_alias(alias)
        kebab_key = _to_kebab_key(alias)
        changes: list[str] = []

        if add_to_catalog:
            if not catalog_path.exists():
                raise FileNotFoundError("gradle/libs.versions.toml not found")

            catalog_text = catalog_path.read_text(encoding="utf-8")
            catalog_text = _add_version_to_catalog(catalog_text, camel_alias, version)
            catalog_text = _add_library_to_catalog(catalog_text, kebab_key, group, name, camel_alias)
            catalog_path.write_text(catalog_text, encoding="utf-8")
            changes.append(f"Added '{camel_alias} = \"{version}\"' and library '{kebab_key}' to gradle/libs.versions.toml")

            build_text = build_gradle.read_text(encoding="utf-8")
            build_text = _add_dependency_to_build_gradle(build_text, configuration, f"libs.{kebab_key}")
            build_gradle.write_text(build_text, encoding="utf-8")
            changes.append(f"Added {configuration}(libs.{kebab_key}) to {module}/build.gradle.kts")
        else:
            build_text = build_gradle.read_text(encoding="utf-8")
            build_text = _add_dependency_to_build_gradle(
                build_text, configuration, f'"{group}:{name}:{version}"'
            )
            build_gradle.write_text(build_text, encoding="utf-8")
            changes.append(f"Added {configuration}(\"{group}:{name}:{version}\") to {module}/build.gradle.kts")

        return "\n".join(changes)

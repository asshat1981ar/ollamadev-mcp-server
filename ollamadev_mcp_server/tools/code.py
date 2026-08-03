"""Code-intelligence tools for the OllamaDev Kotlin project."""

import re
import subprocess
from pathlib import Path

from mcp.server import MCPServer

from ollamadev_mcp_server.constants import WORKSPACE_ROOT
from ollamadev_mcp_server.tool_decorator import tool_runtime
from ollamadev_mcp_server.tool_runtime import ToolContext
from ollamadev_mcp_server.tools.filesystem import _is_ignored, _safe_path


# Kotlin signature extraction patterns
_SIGNATURE_PATTERNS = [
    # package / import
    re.compile(r"^\s*(package|import)\s+([\w.]+)\s*;?"),
    # class / interface / object / data class
    re.compile(
        r"^\s*(?:abstract\s+|sealed\s+|open\s+|internal\s+|public\s+|private\s+|protected\s+)*"
        r"(?:(data|sealed|annotation|enum|inner)\s+)?"
        r"(class|interface|object)\s+([A-Za-z_]\w*)"
    ),
    # function signatures
    re.compile(
        r"^\s*(?:override\s+|abstract\s+|open\s+|private\s+|protected\s+|internal\s+|public\s+)*"
        r"fun\s+(?:<[^>]+>\s+)?([A-Za-z_]\w*)\s*\([^)]*\)"
    ),
    # top-level / property declarations
    re.compile(r"^\s*(?:const\s+|lateinit\s+)?(?:val|var)\s+([A-Za-z_]\w*)"),
]


def _search_files(workspace: Path, pattern: str, file_glob: str, ignore_case: bool, context_lines: int) -> str:
    cmd = ["grep", "-rn", f"--include={file_glob}", f"-C{context_lines}"]
    if ignore_case:
        cmd.append("-i")
    cmd += ["--", pattern, str(workspace)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    out = result.stdout.strip()
    out = out.replace(str(workspace) + "/", "")
    return out if out else "No matches found."


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    @tool_runtime(name="search_workspace")
    def search_workspace(
        ctx: ToolContext = None,
        pattern: str = "",
        file_glob: str = "*.kt",
        ignore_case: bool = False,
        context_lines: int = 2,
    ) -> str:
        """Grep for a regex pattern across workspace source files.

        Args:
            pattern:       Regular expression to search for.
            file_glob:     Glob pattern for file names to search (default: '*.kt').
            ignore_case:   Case-insensitive match (default: False).
            context_lines: Lines of context around each match (default: 2).

        Returns:
            grep output with file:line:content hits, or 'No matches found.'
        """
        workspace = ctx.workspace_root if ctx else WORKSPACE_ROOT
        return _search_files(workspace, pattern, file_glob, ignore_case, context_lines)

    @mcp.tool()
    @tool_runtime(name="get_file_outline")
    def get_file_outline(ctx: ToolContext = None, path: str = "") -> str:
        """Return a compact outline of a Kotlin source file.

        Extracts package, imports, classes, interfaces, objects, functions, and top-level
        properties with their line numbers.

        Args:
            path: Path relative to the workspace root.

        Returns:
            Markdown outline.
        """
        target = _safe_path(path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        lines = target.read_text(encoding="utf-8").splitlines()

        outline: list[str] = []
        for i, line in enumerate(lines, start=1):
            for pat in _SIGNATURE_PATTERNS:
                match = pat.match(line)
                if match:
                    outline.append(f"{i}: {match.group(0).strip()}")
                    break
        header = f"Outline of {path} ({len(outline)} signatures)\n"
        return header + "\n".join(outline) if outline else header + "No signatures detected."

    @mcp.tool()
    @tool_runtime(name="find_symbol")
    def find_symbol(
        ctx: ToolContext = None,
        name: str = "",
        symbol_type: str = "any",
        file_glob: str = "*.kt",
    ) -> str:
        """Find where a Kotlin symbol is declared.

        Args:
            name:        Symbol name to locate (e.g. 'SprintOrchestrator').
            symbol_type: One of: any, class, function, property.
            file_glob:   Glob pattern for files to search (default: '*.kt').

        Returns:
            file:line:declaration lines, or 'No declarations found.'
        """
        symbol_type = symbol_type.lower()
        type_map = {
            "class": r"(class|interface|object|data\s+class)\s+{name}\b",
            "function": r"fun\s+[^\(]*\b{name}\b\s*\(",
            "property": r"(val|var)\s+\b{name}\b",
        }

        if symbol_type == "any":
            patterns = [rf"\b{name}\b"]
        elif symbol_type in type_map:
            patterns = [type_map[symbol_type].format(name=re.escape(name))]
        else:
            raise ValueError(f"symbol_type must be one of: any, class, function, property")

        workspace = ctx.workspace_root if ctx else WORKSPACE_ROOT
        results: list[str] = []
        for pat in patterns:
            cmd = ["grep", "-rnE", f"--include={file_glob}", pat, str(workspace)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            for hit in result.stdout.strip().splitlines():
                hit = hit.replace(str(workspace) + "/", "")
                results.append(hit)

        return "\n".join(results) if results else "No declarations found."

    @mcp.tool()
    @tool_runtime(name="get_todos")
    def get_todos(
        ctx: ToolContext = None,
        file_glob: str = "*.kt",
        patterns: list[str] | None = None,
    ) -> str:
        """Extract TODO/FIXME/HACK/XXX markers from workspace source files.

        Args:
            file_glob: Glob pattern for files to scan (default: '*.kt').
            patterns:  List of marker strings to look for. Defaults to ['TODO', 'FIXME', 'HACK', 'XXX'].

        Returns:
            file:line:comment lines, or 'No TODOs found.'
        """
        if patterns is None:
            patterns = ["TODO", "FIXME", "HACK", "XXX"]
        if not patterns:
            return "No markers specified."

        regex = "|".join(re.escape(p) for p in patterns)
        workspace = ctx.workspace_root if ctx else WORKSPACE_ROOT
        cmd = ["grep", "-rn", f"--include={file_glob}", "-E", f"({regex})", str(workspace)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = result.stdout.strip()
        out = out.replace(str(WORKSPACE_ROOT) + "/", "")
        return out if out else "No TODOs found."

"""Filesystem tools for the OllamaDev workspace."""

import shutil
import subprocess
from pathlib import Path

from mcp.server import MCPServer

from ollamadev_mcp_server.constants import WORKSPACE_ROOT


def _safe_path(relative: str) -> Path:
    """Resolve a relative path inside the workspace, rejecting traversal."""
    target = (WORKSPACE_ROOT / relative).resolve()
    workspace = WORKSPACE_ROOT.resolve()
    if not str(target).startswith(str(workspace)):
        raise PermissionError(f"Path escapes workspace: {relative}")
    return target


def _is_ignored(path: Path) -> bool:
    """True for directories we don't want to walk into."""
    ignore = {".git", "build", ".gradle", ".venv", "__pycache__", ".idea"}
    return any(part in ignore for part in path.parts)


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def list_workspace_files(root: str = "") -> list[str]:
        """Return relative paths of all files in the OllamaDev workspace.

        Args:
            root: Sub-path within the workspace to limit the listing (default: entire workspace).
        """
        base = WORKSPACE_ROOT / root if root else WORKSPACE_ROOT
        if not base.exists():
            return []
        return sorted(
            str(p.relative_to(WORKSPACE_ROOT))
            for p in base.rglob("*")
            if p.is_file() and not _is_ignored(p)
        )

    @mcp.tool()
    def read_workspace_file(path: str) -> str:
        """Read a file from the OllamaDev workspace by its relative path.

        Args:
            path: Path relative to the workspace root (e.g. 'app/src/main/java/com/example/data/Entities.kt').
        """
        target = _safe_path(path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not target.is_file():
            raise ValueError(f"Path is not a file: {path}")
        return target.read_text(encoding="utf-8")

    @mcp.tool()
    def write_workspace_file(path: str, content: str, create_dirs: bool = True) -> str:
        """Write (or overwrite) a file in the OllamaDev workspace.

        Args:
            path:        Path relative to the workspace root.
            content:     Full UTF-8 text content to write.
            create_dirs: Create parent directories if they don't exist (default: True).

        Returns:
            Confirmation message including the number of bytes written.
        """
        target = _safe_path(path)
        if create_dirs:
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Written {len(content.encode())} bytes → {path}"

    @mcp.tool()
    def delete_workspace_file(path: str) -> str:
        """Delete a file inside the OllamaDev workspace.

        Warning: this tool can delete project files. Use with care.

        Args:
            path: Path relative to the workspace root.

        Returns:
            Confirmation message, or an error if the path does not exist or is a directory.
        """
        target = _safe_path(path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if target.is_dir():
            raise ValueError(f"Refusing to delete directory: {path}; use file-level deletes only")
        target.unlink()
        return f"Deleted {path}"

    @mcp.tool()
    def move_workspace_file(src: str, dst: str) -> str:
        """Move or rename a file within the OllamaDev workspace.

        Args:
            src: Source path relative to the workspace root.
            dst: Destination path relative to the workspace root.

        Returns:
            Confirmation message with source and destination.
        """
        src_path = _safe_path(src)
        dst_path = _safe_path(dst)
        if not src_path.exists():
            raise FileNotFoundError(f"Source not found: {src}")
        if src_path.is_dir():
            raise ValueError(f"Refusing to move directory: {src}; use file-level moves only")
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))
        return f"Moved {src} → {dst}"

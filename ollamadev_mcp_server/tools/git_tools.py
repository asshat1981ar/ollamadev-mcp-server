"""Git tools for the OllamaDev workspace.

These expose common git operations to agents so INTEGRATION and RETROSPECTIVE
phases can inspect real changes and create checkpoints.
"""

import subprocess
from pathlib import Path

from mcp.server import MCPServer

from ollamadev_mcp_server.constants import WORKSPACE_ROOT
from ollamadev_mcp_server.tool_decorator import tool_runtime
from ollamadev_mcp_server.tool_runtime import ToolContext
from ollamadev_mcp_server.tools.filesystem import _safe_path


def _git_available() -> bool:
    return subprocess.run(["which", "git"], capture_output=True, text=True).returncode == 0


def _run_git(cmd: list[str], timeout: int = 60) -> str:
    if not _git_available():
        return "ERROR: git command not found in this environment."
    result = subprocess.run(
        ["git"] + cmd,
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return (result.stdout + result.stderr).strip()


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    @tool_runtime(name="git_status_diff")
    def git_status_diff(ctx: ToolContext = None, path: str = "", staged: bool = False) -> str:
        """Show git status and a unified diff for the workspace.

        Args:
            path:   Optional relative file path to limit the diff/status to.
            staged: Show staged changes instead of unstaged (default: False).

        Returns:
            Combined status + diff output, or an error message if git is unavailable.
        """
        if not _git_available():
            return "ERROR: git command not found in this environment."

        status_cmd = ["status", "--short"]
        diff_cmd = ["diff"]
        if staged:
            diff_cmd.append("--cached")
        if path:
            workspace = ctx.workspace_root if ctx else WORKSPACE_ROOT
            target = (workspace / path).resolve()
            if not str(target).startswith(str(workspace.resolve())):
                raise PermissionError(f"Path escapes workspace: {path}")
            diff_cmd += ["--", str(target)]
            status_cmd += ["--", str(target)]

        status = _run_git(status_cmd)
        diff = _run_git(diff_cmd)
        return f"--- Status ---\n{status or '(clean)'}\n\n--- Diff ---\n{diff or '(no changes)'}"

    @mcp.tool()
    @tool_runtime(name="git_commit_checkpoint")
    def git_commit_checkpoint(ctx: ToolContext = None, message: str = "", author_name: str = "OllamaDev Agent", author_email: str = "agent@ollamadev.local") -> str:
        """Stage all changes in the workspace and create a git checkpoint commit.

        Args:
            message:      Commit message.
            author_name:  Author name for the commit.
            author_email: Author email for the commit.

        Returns:
            Commit result including the new hash, or an error message.
        """
        if not _git_available():
            return "ERROR: git command not found in this environment."

        add_out = _run_git(["add", "-A"])
        if add_out and "error" in add_out.lower():
            return f"ERROR during git add:\n{add_out}"

        commit_cmd = [
            "commit",
            "-m", message,
            f"--author={author_name} <{author_email}>",
            "--allow-empty"
        ]
        commit_out = _run_git(commit_cmd)

        # Try to extract the commit hash
        hash_out = _run_git(["rev-parse", "HEAD"])
        return f"Git checkpoint created.\n\n{commit_out}\n\nHEAD: {hash_out}"

    @mcp.tool()
    @tool_runtime(name="git_log")
    def git_log(ctx: ToolContext = None, limit: int = 10) -> str:
        """Return recent git log entries.

        Args:
            limit: Maximum number of commits to return (default: 10).

        Returns:
            One-line log output, or an error message if git is unavailable.
        """
        if not _git_available():
            return "ERROR: git command not found in this environment."
        return _run_git(["log", f"--max-count={limit}", "--oneline", "--decorate"])

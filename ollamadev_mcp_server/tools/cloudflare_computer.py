"""Cloudflare Computer tools for the OllamaDev agentic harness.

Cloudflare Computer (https://github.com/cloudflare/computer) is a preview
SQLite-backed virtual filesystem for Cloudflare Durable Objects, with pluggable
execution backends (container shell, isolated worker shell, isolated
JavaScript), an isomorphic-git client, and ready-made AI tools.

OllamaDev agents reach an existing Cloudflare Computer workspace over the HTTP
surface that the computer repo's example Workers (`examples/container`,
`examples/worker-shell`, `examples/worker-javascript`) expose:

    PUT  {base}/c/{workspace}/file/workspace/{path}   write a file
    GET  {base}/c/{workspace}/file/workspace/{path}   read a file
    POST {base}/c/{workspace}/exec                    run a command/shell

These tools proxy that surface so a Swarm/OllamaDev agent can operate a cloud
workspace (read/write/list/exec/git) through the same MCP plumbing it already
uses for the local workspace. They are a thin client: if no Cloudflare Computer
instance is running, each tool returns a clear, helpful error rather than
failing silently.

Configuration (env or persisted settings):
- CF_COMPUTER_BASE_URL   (default http://127.0.0.1:8787)
- CF_COMPUTER_WORKSPACE  (default "compute")
- CF_COMPUTER_TIMEOUT    (default 30)
"""

import json
from typing import Any

import requests
from mcp.server import MCPServer

from ollamadev_mcp_server.constants import (
    CF_COMPUTER_BASE_URL,
    CF_COMPUTER_TIMEOUT,
    CF_COMPUTER_WORKSPACE,
)
from ollamadev_mcp_server.tool_decorator import tool_runtime
from ollamadev_mcp_server.tool_runtime import ToolContext

# Allow tests to override these module-level values without touching env.
_CONFIG = {
    "base_url": CF_COMPUTER_BASE_URL,
    "workspace": CF_COMPUTER_WORKSPACE,
    "timeout": CF_COMPUTER_TIMEOUT,
}


def _cfg(key: str) -> Any:
    return _CONFIG.get(key)


def _base_url() -> str:
    return str(_cfg("base_url")).rstrip("/")


def _file_url(path: str) -> str:
    """Build the URL for a workspace file, mirroring the example HTTP surface."""
    from urllib.parse import quote

    ws = str(_cfg("workspace"))
    quoted = quote(path.lstrip("/"), safe="/")
    return f"{_base_url()}/c/{ws}/file/workspace/{quoted}"


def _exec_url() -> str:
    ws = str(_cfg("workspace"))
    return f"{_base_url()}/c/{ws}/exec"


def _timeout() -> int:
    return int(_cfg("timeout"))


def _not_configured(what: str) -> dict:
    return {
        "ok": False,
        "error": (
            f"Cloudflare Computer is not reachable for {what}. Set "
            f"CF_COMPUTER_BASE_URL (default {_base_url() or 'http://127.0.0.1:8787'}) to the "
            "Worker/DO that hosts the workspace HTTP surface, and CF_COMPUTER_WORKSPACE to the "
            "workspace name, then call cf_workspace_status to verify the connection."
        ),
    }


def _safe_get(url: str, timeout: int | None = None) -> requests.Response:
    return requests.get(url, timeout=timeout or _timeout())


def _safe_put(url: str, body: bytes, timeout: int | None = None) -> requests.Response:
    return requests.put(url, data=body, timeout=timeout or _timeout())


def _safe_post(url: str, payload: dict, timeout: int | None = None) -> requests.Response:
    return requests.post(url, json=payload, timeout=timeout or _timeout())
def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": True})
    @tool_runtime(name="cf_workspace_status")
    def cf_workspace_status(ctx: ToolContext = None) -> dict:
        """Report Cloudflare Computer connectivity and configuration.

        Returns:
            JSON dict with base URL, workspace name, connectivity status, and
            the surface index text when reachable.
        """
        url = _base_url()
        if not url:
            return _not_configured("status")
        try:
            resp = _safe_get(url)
            reachable = resp.status_code < 500
            return {
                "ok": reachable,
                "base_url": url,
                "workspace": str(_cfg("workspace")),
                "reachable": reachable,
                "http_status": resp.status_code,
                "surface": resp.text[:400] if reachable else "",
            }
        except requests.RequestException as exc:
            return _not_configured(f"status ({exc.__class__.__name__}: {exc})")

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": True})
    @tool_runtime(name="cf_read_workspace_file")
    def cf_read_workspace_file(ctx: ToolContext = None, path: str = "") -> dict:
        """Read a file from the Cloudflare Computer workspace by absolute path.

        Args:
            path: Workspace path (e.g. 'workspace/notes/todo.md' or '/workspace/notes/todo.md').

        Returns:
            JSON dict with ok and content, or ok=false with error details.
        """
        if not path.strip():
            return {"ok": False, "error": "path is required"}
        url = _file_url(path)
        try:
            resp = _safe_get(url)
            if resp.status_code == 404:
                return {"ok": False, "error": f"ENOENT: {path}", "http_status": 404}
            if resp.status_code >= 400:
                return {"ok": False, "error": resp.text[:400], "http_status": resp.status_code}
            body = resp.content
            try:
                content: Any = body.decode("utf-8")
            except UnicodeDecodeError:
                content = f"<binary> {len(body)} bytes (base64: {body[:64].hex()!r}...)"
            return {"ok": True, "path": path, "size": len(body), "content": content}
        except requests.RequestException as exc:
            return _not_configured(f"read {path} ({exc.__class__.__name__}: {exc})")

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": False})
    @tool_runtime(name="cf_write_workspace_file")
    def cf_write_workspace_file(
        ctx: ToolContext = None,
        path: str = "",
        content: str = "",
    ) -> dict:
        """Write (or overwrite) a file in the Cloudflare Computer workspace.

        Args:
            path:    Workspace path (e.g. 'workspace/notes/todo.md').
            content: Full UTF-8 text content to write.

        Returns:
            JSON dict with ok and number of bytes written.
        """
        if not path.strip():
            return {"ok": False, "error": "path is required"}
        url = _file_url(path)
        try:
            resp = _safe_put(url, content.encode("utf-8"))
            if resp.status_code >= 400:
                return {"ok": False, "error": resp.text[:400], "http_status": resp.status_code}
            return {"ok": True, "path": path, "bytes": len(content.encode("utf-8"))}
        except requests.RequestException as exc:
            return _not_configured(f"write {path} ({exc.__class__.__name__}: {exc})")

    @mcp.tool(annotations={"destructiveHint": True, "readOnlyHint": False})
    @tool_runtime(name="cf_list_workspace")
    def cf_list_workspace(ctx: ToolContext = None, path: str = "workspace") -> dict:
        """List a directory inside the Cloudflare Computer workspace.

        The example HTTP surface has no dedicated list endpoint, so this runs a
        listing through the exec surface (the container/shell backend).

        Args:
            path: Workspace directory to list (default: 'workspace').

        Returns:
            JSON dict with ok and the raw listing output.
        """
        command = "ls -la"
        if path.strip():
            command = f"ls -la {path}"
        return _run_exec(command=command, cwd="")

    @mcp.tool(annotations={"destructiveHint": True, "readOnlyHint": False})
    @tool_runtime(name="cf_exec_workspace")
    def cf_exec_workspace(
        ctx: ToolContext = None,
        command: str = "",
        cwd: str = "/workspace",
        timeout_ms: int = 30000,
    ) -> dict:
        """Run a command/shell in the Cloudflare Computer workspace.

        Executes arbitrary commands inside the configured Cloudflare Computer
        backend (container shell, worker shell, etc.). Marked destructive so
        OllamaDev's MCP risk gate requires human approval first.

        Args:
            command:   Shell command to run, e.g. 'npm test'.
            cwd:       Working directory inside the workspace (default: /workspace).
            timeout_ms: Backend execution cap in milliseconds (default: 30000).

        Returns:
            JSON dict mirroring the runtime exec result (status, exitCode,
            stdout, stderr).
        """
        if not command.strip():
            return {"ok": False, "error": "command is required"}
        return _run_exec(command=command, cwd=cwd, timeout_ms=timeout_ms)

    @mcp.tool(annotations={"destructiveHint": True, "readOnlyHint": False})
    @tool_runtime(name="cf_git_workspace")
    def cf_git_workspace(
        ctx: ToolContext = None,
        args: str = "status",
        cwd: str = "/workspace",
    ) -> dict:
        """Run a git subcommand inside the Cloudflare Computer workspace.

        Uses the workspace's git surface (isomorphic-git in the worker shell, or
        real git in the container backend). Supported subcommands include
        status, log, diff, clone, add, commit, push, pull, branch, checkout.
        Marked destructive because commit/push mutate state.

        Args:
            args: Git arguments exactly as after `git`, e.g. 'log -3 --oneline'.
            cwd:  Workspace directory containing the checkout.

        Returns:
            JSON dict with ok and the git command output, or ok=false on error.
        """
        if not args.strip():
            return {"ok": False, "error": "git args are required"}
        return _run_exec(command=f"git {args}", cwd=cwd)


def _run_exec(command: str, cwd: str, timeout_ms: int = 30000) -> dict:
    """Shared exec helper: POST to the Cloudflare Computer exec surface."""
    url = _exec_url()
    if not url or url == "/c//exec":
        return _not_configured("exec")
    payload: dict[str, Any] = {"command": command}
    if cwd:
        payload["cwd"] = cwd
    if timeout_ms:
        payload["timeoutMs"] = timeout_ms
    try:
        resp = _safe_post(url, payload)
    except requests.RequestException as exc:
        return _not_configured(f"exec ({exc.__class__.__name__}: {exc})")

    if resp.status_code >= 400:
        return {"ok": False, "error": resp.text[:400], "http_status": resp.status_code}

    try:
        result = resp.json()
    except ValueError:
        return {"ok": False, "error": "exec surface returned non-JSON response", "body": resp.text[:400]}

    # The computer repo's exec surface returns a WorkspaceRuntimeResult
    # ({status, exitCode, stdout, stderr, ...}). Flatten it for agent consumption.
    if isinstance(result, dict):
        return {
            "ok": result.get("status") == "completed",
            "command": command,
            "cwd": cwd,
            "status": result.get("status"),
            "exitCode": result.get("exitCode"),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "sync": result.get("sync"),
            "raw": json.dumps(result)[:4000],
        }
    return {"ok": True, "command": command, "raw": json.dumps(result)[:4000]}

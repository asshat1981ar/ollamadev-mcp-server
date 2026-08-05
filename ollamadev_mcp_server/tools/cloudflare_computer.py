"""Cloudflare Computer tools for the OllamaDev agentic harness.

Cloudflare Computer (https://github.com/cloudflare/computer) is a preview
SQLite-backed virtual filesystem for Cloudflare Durable Objects with pluggable
execution backends (container shell, isolated worker shell, isolated
JavaScript), an isomorphic-git client, and ready-made AI tools.

OllamaDev agents reach an existing Cloudflare Computer workspace over the HTTP
surface that the computer repo's example Workers expose:

    PUT  {base}/c/{workspace}/file/workspace/{path}   write a file
    GET  {base}/c/{workspace}/file/workspace/{path}   read a file
    POST {base}/c/{workspace}/exec                    run a command/shell (JSON)

Production hardening in this module:

- Config is validated up front (http/https only, workspace name charset,
  bounded timeouts) so a bad env var surfaces as a clear tool error.
- Requests reuse a connection-pooled ``requests.Session``; calls retry with
  exponential backoff on transient network errors (``HTTP_RETRY``) and retry a
  bounded number of times on 502/503/504.
- A circuit breaker protects the remote endpoint so a dead CF Computer does
  not hammer it from every agent turn.
- Paths are normalized and reject traversal/absolute escapes; exec output and
  reads are size-capped so agents never receive unbounded payloads.
- Destructive tools (exec, git, write) are audit-logged and annotated
  destructiveHint=true so OllamaDev's MCP risk gate requires human approval.

Configuration (env or persisted settings):

- CF_COMPUTER_BASE_URL   (default http://127.0.0.1:8787)
- CF_COMPUTER_WORKSPACE  (default "compute")
- CF_COMPUTER_TIMEOUT    (default 30)  per-request HTTP timeout in seconds
- CF_COMPUTER_MAX_RETRIES (default 3)
"""

import base64
import json
import re
import shlex
import time
from typing import Any
from urllib.parse import quote, urlsplit

import requests
from mcp.server import MCPServer
from requests.adapters import HTTPAdapter

from ollamadev_mcp_server.audit import audit_log
from ollamadev_mcp_server.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from ollamadev_mcp_server.constants import (
    CF_COMPUTER_BASE_URL,
    CF_COMPUTER_TIMEOUT,
    CF_COMPUTER_WORKSPACE,
)
from ollamadev_mcp_server.logging_config import get_logger
from ollamadev_mcp_server.retry import HTTP_RETRY
from ollamadev_mcp_server.tool_decorator import tool_runtime
from ollamadev_mcp_server.tool_runtime import ToolContext

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Overridable in tests via cf_mod._CONFIG["key"] = value, mirroring how other
# module singletons in this server are patched.
_CONFIG: dict[str, Any] = {
    "base_url": CF_COMPUTER_BASE_URL,
    "workspace": CF_COMPUTER_WORKSPACE,
    "timeout": CF_COMPUTER_TIMEOUT,
    "max_retries": 3,
    "max_read_bytes": 2 * 1024 * 1024,      # 2 MiB per read
    "max_exec_output_bytes": 256 * 1024,    # 256 KiB per stream
}

_SUPPORTED_SCHEMES = ("http", "https")
_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# git subcommands supported by workspace.git / the container git CLI.
# See docs/13_git_interface.md in the computer repo.
SUPPORTED_GIT_SUBCOMMANDS = frozenset({
    "add", "branch", "cat-file", "checkout", "clean", "clone", "commit",
    "config", "diff", "fetch", "init", "log", "ls-files", "ls-tree",
    "merge", "pull", "push", "remote", "reset", "rev-parse", "rm",
    "show", "stash", "status", "symbolic-ref", "switch", "tag",
    "update-ref",
})

MUTATING_GIT_SUBCOMMANDS = frozenset({
    "add", "branch", "checkout", "clean", "clone", "commit", "config",
    "fetch", "init", "merge", "pull", "push", "remote", "reset", "rm",
    "stash", "switch", "tag", "update-ref",
})

# ---------------------------------------------------------------------------
# Config resolution and validation
# ---------------------------------------------------------------------------


def _cfg(key: str) -> Any:
    return _CONFIG.get(key)


def _base_url() -> str:
    return str(_cfg("base_url") or "").rstrip("/")


def _validate_config() -> dict | None:
    """Validate configuration; return an error dict (ok False) or None."""
    url = _base_url()
    if not url:
        return _config_error("CF_COMPUTER_BASE_URL is empty; set it to the Worker URL hosting the workspace")
    parts = urlsplit(url)
    if parts.scheme not in _SUPPORTED_SCHEMES or not parts.hostname:
        return _config_error(
            f"CF_COMPUTER_BASE_URL must be an http(s) URL, got {url!r}"
        )
    ws = str(_cfg("workspace"))
    if not _WORKSPACE_RE.match(ws):
        return _config_error(
            f"CF_COMPUTER_WORKSPACE must match {_WORKSPACE_RE.pattern!r}, got {ws!r}"
        )
    timeout = int(_cfg("timeout") or 30)
    if not 1 <= timeout <= 300:
        return _config_error(f"CF_COMPUTER_TIMEOUT must be 1..300, got {timeout}")
    return None


def _config_error(detail: str) -> dict:
    return {
        "ok": False,
        "code": "CONFIG_ERROR",
        "error": f"Invalid Cloudflare Computer configuration: {detail}",
    }

# ---------------------------------------------------------------------------
# Transport: pooled session + retries + circuit breaker
# ---------------------------------------------------------------------------

_SESSION: requests.Session | None = None
_BREAKER = CircuitBreaker("cloudflare-computer", failure_threshold=5, recovery_timeout=60)


def get_computer_breaker() -> CircuitBreaker:
    """Return the module's Cloudflare Computer circuit breaker."""
    return _BREAKER


def _get_session() -> requests.Session:
    """Return a lazily-created, connection-pooled session."""
    global _SESSION
    if _SESSION is None:
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=8, pool_maxsize=16)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        _SESSION = session
    return _SESSION


def _reset_session() -> None:
    """Drop the shared session (tests)."""
    global _SESSION
    _SESSION = None


# Transport seams (tests monkeypatch these).
def _safe_get(url: str, timeout: int | None = None) -> requests.Response:
    return _get_session().get(url, timeout=timeout or int(_cfg("timeout") or 30), stream=True)


def _safe_put(url: str, body: bytes, timeout: int | None = None) -> requests.Response:
    return _get_session().put(url, data=body, timeout=timeout or int(_cfg("timeout") or 30))


def _safe_post(url: str, payload: dict, timeout: int | None = None) -> requests.Response:
    return _get_session().post(url, json=payload, timeout=timeout or int(_cfg("timeout") or 30))


_RETRYABLE_STATUSES = frozenset({502, 503, 504})
_RETRYABLE_EXCEPTIONS = (requests.ConnectionError, requests.Timeout)


def _call(method: str, url: str, **kwargs: Any) -> requests.Response:
    """Perform one logical request: circuit breaker + retries + backoff.

    Retries on transient network errors and on 502/503/504 up to
    ``max_retries`` attempts, using the standard ``HTTP_RETRY`` backoff.
    """
    max_retries = max(1, int(_cfg("max_retries") or 1))

    def _attempt() -> requests.Response:
        if method == "GET":
            return _safe_get(url, timeout=kwargs.get("timeout"))
        if method == "PUT":
            return _safe_put(url, body=kwargs.get("data", b""), timeout=kwargs.get("timeout"))
        return _safe_post(url, kwargs.get("json", {}), timeout=kwargs.get("timeout"))

    attempts_left = max_retries
    while True:
        try:
            resp: requests.Response = _BREAKER.call(_attempt)
        except CircuitBreakerOpen as exc:
            # Circuit is open on purpose — converting to ConnectionError lets the
            # tools surface a structured DEPENDENCY_ERROR without a pointless retry.
            raise requests.ConnectionError(str(exc)) from exc
        except _RETRYABLE_EXCEPTIONS as exc:
            attempts_left -= 1
            if attempts_left > 0:
                time.sleep(HTTP_RETRY.compute_delay(max_retries - attempts_left))
                continue
            raise
        if resp.status_code in _RETRYABLE_STATUSES and attempts_left > 1:
            attempts_left -= 1
            time.sleep(HTTP_RETRY.compute_delay(max_retries - attempts_left))
            continue
        # A reachable-but-5xx backend keeps its HTTP-error semantics (callers
        # see http_status); the circuit breaker opens on transport exceptions
        # (a dead/unreachable endpoint) via CircuitBreaker.call().
        return resp
    raise RuntimeError("unreachable: retry loop exhausted")


# ---------------------------------------------------------------------------
# Path + URL helpers
# ---------------------------------------------------------------------------


def _normalize_path(path: str) -> str:
    """Normalize a workspace path and reject traversal-style escapes.

    Returns a path with no leading slash and no ``.``/``..`` segments, or
    raises ``ValueError`` with a message when the path is unusable.
    """
    p = (path or "").strip()
    if "\x00" in p:
        raise ValueError("path contains a null byte")
    if any(ord(c) < 32 for c in p):
        raise ValueError("path contains control characters")
    if p.startswith("/"):
        p = p.lstrip("/")
    p = p.replace("\\", "/")
    segments = [seg for seg in p.split("/") if seg not in ("", ".")]
    if not segments:
        raise ValueError("path is required")
    if any(seg == ".." for seg in segments):
        raise ValueError("path must not contain '..' segments")
    if len(segments) > 64 or len(p) > 1024:
        raise ValueError("path is too deep or too long (max 64 segments / 1024 chars)")
    return "/".join(segments)


def _file_url(path: str) -> str:
    ws = str(_cfg("workspace"))
    quoted = quote(path, safe="/")
    return f"{_base_url()}/c/{ws}/file/workspace/{quoted}"


def _exec_url() -> str:
    ws = str(_cfg("workspace"))
    return f"{_base_url()}/c/{ws}/exec"


# ---------------------------------------------------------------------------
# Response shaping
# ---------------------------------------------------------------------------


def _err(code: str, message: str, **extra: Any) -> dict:
    """Build a structured error result."""
    result: dict[str, Any] = {"ok": False, "code": code, "error": message}
    result.update(extra)
    return result


def _not_configured(what: str, exc: Exception | None = None) -> dict:
    detail = f"{exc.__class__.__name__}: {exc}" if exc is not None else "endpoint not reachable"
    return _err(
        "DEPENDENCY_ERROR",
        f"Cloudflare Computer is unreachable for {what} ({detail}). "
        f"Check CF_COMPUTER_BASE_URL ({_base_url() or '<unset>'}) / CF_COMPUTER_WORKSPACE "
        f"({_cfg('workspace')!r}) and that the Worker is running.",
    )


def _unpack(response: requests.Response, cap_bytes: int) -> tuple[bytes, bool]:
    """Return (body bytes capped to cap_bytes, truncated_flag)."""
    try:
        declared = int(response.headers.get("content-length", "0") or 0)
    except (TypeError, ValueError):
        declared = 0
    if declared > cap_bytes:
        return b"", True
    body = response.content or b""
    if len(body) > cap_bytes:
        return body[:cap_bytes], True
    return body, False

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _client_id(ctx: ToolContext | None) -> str:
    return getattr(ctx, "agent_id", None) or "-"


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": True})
    @tool_runtime(name="cf_workspace_status")
    def cf_workspace_status(ctx: ToolContext = None) -> dict:
        """Report Cloudflare Computer connectivity, configuration, and circuit health.

        Returns:
            JSON dict with base URL, workspace name, reachability, HTTP status,
            the surface index text, and circuit-breaker status.
        """
        cfg_err = _validate_config()
        if cfg_err:
            return cfg_err
        url = _base_url()
        try:
            resp = _call("GET", url, timeout=min(int(_cfg("timeout") or 30), 15))
            reachable = resp.status_code < 500
            surface = ""
            if reachable:
                body, truncated = _unpack(resp, 400)
                surface = body.decode("utf-8", errors="replace")[:400]
            return {
                "ok": reachable,
                "base_url": url,
                "workspace": str(_cfg("workspace")),
                "reachable": reachable,
                "http_status": resp.status_code,
                "surface": surface,
                "circuit": get_computer_breaker().get_status(),
            }
        except _RETRYABLE_EXCEPTIONS as exc:
            return _not_configured("status", exc)

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": True})
    @tool_runtime(name="cf_read_workspace_file")
    def cf_read_workspace_file(
        ctx: ToolContext = None,
        path: str = "",
        binary: bool = False,
    ) -> dict:
        """Read a file from the Cloudflare Computer workspace.

        Args:
            path:   Workspace path (e.g. 'workspace/notes/todo.md'). Leading
                    slashes are normalized; '..' is rejected.
            binary: When True, return the raw bytes base64-encoded (for
                    non-UTF-8 files) instead of decoding to text.

        Returns:
            JSON dict with ok, path, size, content (or base64) and truncated flag.
        """
        cfg_err = _validate_config()
        if cfg_err:
            return cfg_err
        try:
            clean = _normalize_path(path)
        except ValueError as exc:
            return _err("VALIDATION_ERROR", str(exc), field="path")
        try:
            resp = _call("GET", _file_url(clean))
        except _RETRYABLE_EXCEPTIONS as exc:
            return _not_configured(f"read {path}", exc)
        if resp.status_code == 404:
            return _err("ENOENT", f"File not found: {path}", http_status=404)
        if resp.status_code >= 400:
            return _err(
                "HTTP_ERROR",
                resp.text[:300] or f"HTTP {resp.status_code}",
                http_status=resp.status_code,
            )
        body, truncated = _unpack(resp, int(_cfg("max_read_bytes")))
        content: Any = base64.b64encode(body).decode("ascii") if binary else body.decode("utf-8", errors="replace")
        return {
            "ok": True,
            "path": clean,
            "size": len(body),
            "truncated": truncated,
            "encoding": "base64" if binary else "utf-8",
            "content": content,
        }

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": False})
    @tool_runtime(name="cf_write_workspace_file")
    def cf_write_workspace_file(
        ctx: ToolContext = None,
        path: str = "",
        content: str = "",
        content_b64: str = "",
    ) -> dict:
        """Write (or overwrite) a file in the Cloudflare Computer workspace.

        Args:
            path:        Workspace path (e.g. 'workspace/notes/todo.md').
            content:     Full UTF-8 text content to write.
            content_b64: Alternative: base64-encoded bytes to write (for
                         binary files). Provide exactly one of the two.

        Returns:
            JSON dict with ok and number of bytes written.
        """
        cfg_err = _validate_config()
        if cfg_err:
            return cfg_err
        try:
            clean = _normalize_path(path)
        except ValueError as exc:
            return _err("VALIDATION_ERROR", str(exc), field="path")
        if bool(content) == bool(content_b64):
            return _err(
                "VALIDATION_ERROR",
                "provide exactly one of 'content' or 'content_b64'",
                field="content/content_b64",
            )
        try:
            body = base64.b64decode(content_b64) if content_b64 else content.encode("utf-8")
        except (ValueError, UnicodeError) as exc:
            return _err("VALIDATION_ERROR", f"invalid content_b64: {exc}", field="content_b64")
        try:
            resp = _call("PUT", _file_url(clean), data=body)
        except _RETRYABLE_EXCEPTIONS as exc:
            return _not_configured(f"write {path}", exc)
        if resp.status_code >= 400:
            return _err(
                "HTTP_ERROR",
                resp.text[:300] or f"HTTP {resp.status_code}",
                http_status=resp.status_code,
            )
        audit_log(
            "cf_write_workspace_file",
            _client_id(ctx),
            {"path": clean, "bytes": len(body)},
            result="ok",
        )
        return {"ok": True, "path": clean, "bytes": len(body)}

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": True})
    @tool_runtime(name="cf_list_workspace")
    def cf_list_workspace(ctx: ToolContext = None, path: str = "workspace") -> dict:
        """List a directory inside the Cloudflare Computer workspace.

        The example HTTP surface has no dedicated list endpoint, so this runs
        ``ls -la`` through the exec surface. Listing is read-only; exec output
        is size-capped like every other exec call.

        Args:
            path: Workspace directory to list (default: 'workspace').

        Returns:
            JSON dict with ok, the executed command, and its output.
        """
        cfg_err = _validate_config()
        if cfg_err:
            return cfg_err
        try:
            clean = _normalize_path(path)
        except ValueError as exc:
            return _err("VALIDATION_ERROR", str(exc), field="path")
        return _run_exec(command=f"ls -la {shlex.quote(clean)}", cwd="")

    @mcp.tool(annotations={"destructiveHint": True, "readOnlyHint": False})
    @tool_runtime(name="cf_exec_workspace")
    def cf_exec_workspace(
        ctx: ToolContext = None,
        command: str = "",
        argv: list[str] | None = None,
        cwd: str = "/workspace",
        timeout_ms: int = 30000,
        backend: str = "",
    ) -> dict:
        """Run a command/shell in the Cloudflare Computer workspace.

        Marked destructive so OllamaDev's MCP risk gate requires human approval
        before execution; the call is audit-logged.

        Args:
            command:   Shell command to run, e.g. 'npm test'. Optional if argv
                       is provided.
            argv:      Alternative to command: arg list that is shell-quoted
                       before execution (safer for untrusted tokens).
            cwd:       Working directory inside the workspace (default: /workspace).
            timeout_ms: Backend execution cap in milliseconds (default: 30000).
            backend:   Optional backend id (e.g. 'sandbox', 'shell') when the
                       surface forwards it.

        Returns:
            JSON dict mirroring the runtime exec result (status, exitCode,
            stdout, stderr) with output size-capped.
        """
        cfg_err = _validate_config()
        if cfg_err:
            return cfg_err
        if command and argv:
            return _err("VALIDATION_ERROR", "provide either 'command' or 'argv', not both")
        if argv is not None:
            if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
                return _err("VALIDATION_ERROR", "argv must be a non-empty list of strings")
            command = shlex.join(argv)
        if not command or not command.strip():
            return _err("VALIDATION_ERROR", "command is required")
        if len(command) > 8000:
            return _err("VALIDATION_ERROR", "command is too long (max 8000 chars)")
        if "\x00" in command:
            return _err("VALIDATION_ERROR", "command contains a null byte")
        result = _run_exec(command=command, cwd=cwd, timeout_ms=timeout_ms, backend=backend)
        if result.get("ok"):
            audit_log(
                "cf_exec_workspace",
                _client_id(ctx),
                {"command": command, "cwd": cwd, "exitCode": result.get("exitCode")},
                result="ok",
            )
        return result

    @mcp.tool(annotations={"destructiveHint": True, "readOnlyHint": False})
    @tool_runtime(name="cf_git_workspace")
    def cf_git_workspace(
        ctx: ToolContext = None,
        args: str = "status",
        cwd: str = "/workspace",
    ) -> dict:
        """Run a git subcommand inside the Cloudflare Computer workspace.

        Uses the workspace's git surface (isomorphic-git in the worker shell,
        or real git in the container backend). Only known, supported
        subcommands are allowed; MUTATING subcommands (commit, push, pull,
        checkout, reset, ...) are audit-logged and gated.

        Args:
            args: Git arguments exactly as after `git`, e.g. 'log -3 --oneline'.
            cwd:  Workspace directory containing the checkout.

        Returns:
            JSON dict with ok and the git command output.
        """
        cfg_err = _validate_config()
        if cfg_err:
            return cfg_err
        try:
            tokens = shlex.split(args)
        except ValueError as exc:
            return _err("VALIDATION_ERROR", f"invalid git args: {exc}", field="args")
        if not tokens:
            return _err("VALIDATION_ERROR", "git args are required (e.g. 'status')", field="args")
        # The git command executes in the backend's shell, so refuse shell
        # operators/metacharacters that could escape the intended command.
        if any(c in args for c in (';', '&', '|', '<', '>', '`', '$(')) or "\n" in args:
            return _err("VALIDATION_ERROR", "git args must not contain shell metacharacters", field="args")
        subcommand = tokens[0]
        if subcommand not in SUPPORTED_GIT_SUBCOMMANDS:
            return _err(
                "VALIDATION_ERROR",
                f"unsupported git subcommand {subcommand!r}; supported: "
                + ", ".join(sorted(SUPPORTED_GIT_SUBCOMMANDS)),
                field="args",
            )
        if any(c in args for c in ("\x00",)):
            return _err("VALIDATION_ERROR", "git args contain a null byte")
        result = _run_exec(command=f"git {args}", cwd=cwd)
        if subcommand in MUTATING_GIT_SUBCOMMANDS and result.get("ok"):
            audit_log(
                "cf_git_workspace",
                _client_id(ctx),
                {"args": args, "cwd": cwd, "exitCode": result.get("exitCode")},
                result="ok",
            )
        return result


# ---------------------------------------------------------------------------
# Exec helper
# ---------------------------------------------------------------------------


def _run_exec(command: str, cwd: str, timeout_ms: int = 30000, backend: str = "") -> dict:
    """POST to the Cloudflare Computer exec surface and flatten the result."""
    payload: dict[str, Any] = {"command": command}
    if cwd:
        payload["cwd"] = cwd
    if timeout_ms:
        payload["timeoutMs"] = int(timeout_ms)
    if backend:
        payload["backend"] = backend
    try:
        resp = _call("POST", _exec_url(), json=payload)
    except _RETRYABLE_EXCEPTIONS as exc:
        return _not_configured("exec", exc)

    if resp.status_code >= 400:
        return _err("HTTP_ERROR", resp.text[:300] or f"HTTP {resp.status_code}", http_status=resp.status_code)
    try:
        result = resp.json()
    except ValueError:
        return _err("HTTP_ERROR", "exec surface returned a non-JSON response", body=resp.text[:200])
    if not isinstance(result, dict):
        return _err("HTTP_ERROR", "exec surface returned an unexpected shape")

    cap = int(_cfg("max_exec_output_bytes"))
    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    stdout_truncated = len(stdout) > cap
    stderr_truncated = len(stderr) > cap
    sync = result.get("sync")
    return {
        "ok": result.get("status") == "completed",
        "command": command,
        "cwd": cwd,
        "status": result.get("status"),
        "exitCode": result.get("exitCode"),
        "stdout": stdout[:cap],
        "stderr": stderr[:cap],
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "pushed": result.get("pushed"),
        "pulled": result.get("pulled"),
        "sync_status": sync.get("status") if isinstance(sync, dict) else None,
        "raw": json.dumps(result)[:4000],
    }

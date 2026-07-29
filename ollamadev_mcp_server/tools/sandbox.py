"""Execution-sandbox tools for the OllamaDev agentic harness.

These tools let the verify phase invoke real test/execution tooling instead of
fabricating a result. They are intentionally minimal: they run commands inside
the configured WORKSPACE_ROOT on the same machine as the MCP server, returning
structured pass/fail output. Destructive commands (arbitrary shell) are annotated
so OllamaDev's existing MCP risk gate flags them for human approval.
"""

import json
import shutil
import subprocess
from pathlib import Path

from mcp.server import MCPServer

from ollamadev_mcp_server.constants import WORKSPACE_ROOT


def _run(
    cmd: list[str],
    cwd: Path = WORKSPACE_ROOT,
    timeout: int = 300,
) -> dict:
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "combined": (result.stdout + result.stderr).strip(),
    }


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": False})
    def run_pytest(
        path: str = "",
        test_filter: str = "",
        timeout_seconds: int = 300,
    ) -> str:
        """Run pytest in the workspace and return a structured pass/fail result.

        Args:
            path:          Relative directory or file to run pytest against (default: workspace root).
            test_filter:   Optional -k filter expression passed to pytest.
            timeout_seconds: Per-invocation timeout (default: 300).

        Returns:
            JSON with exit code, pass/fail status, and combined output.
        """
        if shutil.which("pytest") is None:
            return json.dumps(
                {"returncode": -1, "status": "FAILED", "error": "pytest is not installed or not on PATH"},
                indent=2,
            )

        target = WORKSPACE_ROOT / path if path else WORKSPACE_ROOT
        cmd = ["pytest", str(target)]
        if test_filter:
            cmd += ["-k", test_filter]

        output = _run(cmd, cwd=WORKSPACE_ROOT, timeout=timeout_seconds)
        status = "PASSED" if output["returncode"] == 0 else "FAILED"
        return json.dumps(
            {
                "returncode": output["returncode"],
                "status": status,
                "output": output["combined"],
            },
            indent=2,
        )

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": False})
    def run_gradle_test_command(
        test_filter: str = "",
        timeout_seconds: int = 600,
    ) -> str:
        """Run the OllamaDev Gradle unit-test command and return structured results.

        This is a sandbox-oriented wrapper around `./gradlew :app:testDebugUnitTest` so the
        verify phase can execute the real test suite via MCP. The command is run in the
        workspace root.

        Args:
            test_filter: Optional --tests filter (e.g. 'com.example.SprintOrchestratorTest').
            timeout_seconds: Per-invocation timeout (default: 600).

        Returns:
            JSON with exit code, pass/fail status, and combined Gradle output.
        """
        gradlew = WORKSPACE_ROOT / "gradlew"
        if not gradlew.exists():
            return json.dumps(
                {"returncode": -1, "status": "FAILED", "error": "gradlew not found in workspace root"},
                indent=2,
            )

        executable = str(gradlew) if gradlew.stat().st_mode & 0o111 else "bash"
        cmd = [str(gradlew), ":app:testDebugUnitTest", "--no-daemon"]
        if not gradlew.stat().st_mode & 0o111:
            cmd = ["bash", str(gradlew), ":app:testDebugUnitTest", "--no-daemon"]
        if test_filter:
            cmd += ["--tests", test_filter]

        output = _run(cmd, cwd=WORKSPACE_ROOT, timeout=timeout_seconds)
        status = "PASSED" if output["returncode"] == 0 else "FAILED"
        return json.dumps(
            {
                "returncode": output["returncode"],
                "status": status,
                "output": output["combined"],
            },
            indent=2,
        )

    @mcp.tool(annotations={"destructiveHint": True, "readOnlyHint": False})
    def run_shell_command(
        command: str,
        timeout_seconds: int = 300,
    ) -> str:
        """Run an arbitrary shell command in the workspace root.

        This is intentionally marked destructiveHint=true so OllamaDev's MCP risk gate
        forces human approval before execution. Use sparingly; prefer run_pytest or
        run_gradle_test_command for verification.

        Args:
            command: The shell command to execute (passed to /bin/sh -c).
            timeout_seconds: Per-invocation timeout (default: 300).

        Returns:
            JSON with exit code, pass/fail status, and combined stdout/stderr.
        """
        output = _run(["/bin/sh", "-c", command], cwd=WORKSPACE_ROOT, timeout=timeout_seconds)
        status = "PASSED" if output["returncode"] == 0 else "FAILED"
        return json.dumps(
            {
                "returncode": output["returncode"],
                "status": status,
                "output": output["combined"],
            },
            indent=2,
        )

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": True})
    def get_sandbox_status() -> str:
        """Return sandbox health and configuration.

        Returns:
            JSON with workspace root, pytest availability, gradlew presence, and uptime.
        """
        return json.dumps(
            {
                "workspace_root": str(WORKSPACE_ROOT),
                "pytest_available": shutil.which("pytest") is not None,
                "gradlew_present": (WORKSPACE_ROOT / "gradlew").exists(),
            },
            indent=2,
        )

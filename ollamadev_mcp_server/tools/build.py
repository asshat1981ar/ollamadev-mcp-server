"""Build / verification tools for the OllamaDev Android project."""

import json
import re
import subprocess
from pathlib import Path

from mcp.server import MCPServer

from ollamadev_mcp_server.constants import WORKSPACE_ROOT


def _run(cmd: list[str], timeout: int = 300) -> str:
    result = subprocess.run(
        cmd,
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return (result.stdout + result.stderr).strip()


def _read_if_exists(relative: str) -> str:
    path = WORKSPACE_ROOT / relative
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8")
    return f"# {relative} not found\n"


def _gradle_cmd(gradlew: Path, *args: str) -> list[str]:
    """Return a command list that works whether gradlew is executable or not."""
    if gradlew.stat().st_mode & 0o111:
        return [str(gradlew), *args]
    return ["bash", str(gradlew), *args]


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def run_gradle_tests(module: str = "app", test_filter: str = "") -> str:
        """Run Gradle unit tests for the OllamaDev project and return stdout + stderr.

        Args:
            module:      Gradle module to test (default: 'app').
            test_filter: Optional test class or method filter passed to --tests
                         (e.g. 'com.example.SprintOrchestratorTest').

        Returns:
            Combined stdout/stderr from the Gradle invocation.
        """
        gradlew = WORKSPACE_ROOT / "gradlew"
        if not gradlew.exists():
            return "ERROR: gradlew not found in workspace root"

        cmd = _gradle_cmd(gradlew, f":{module}:testDebugUnitTest", "--no-daemon")
        if test_filter:
            cmd += ["--tests", test_filter]

        result = subprocess.run(
            cmd,
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = result.stdout + result.stderr
        status = "PASSED" if result.returncode == 0 else "FAILED"
        return f"[Gradle exit {result.returncode} — {status}]\n\n{output}"

    @mcp.tool()
    def run_gradle_build(module: str = "app", variant: str = "Debug") -> str:
        """Run a compile-only Gradle build for the given module/variant.

        This is cheaper than running tests and catches syntax/import errors early.

        Args:
            module:  Gradle module to build (default: 'app').
            variant: Build variant, e.g. 'Debug' or 'Release' (default: 'Debug').

        Returns:
            Combined stdout/stderr with a pass/fail summary.
        """
        gradlew = WORKSPACE_ROOT / "gradlew"
        if not gradlew.exists():
            return "ERROR: gradlew not found in workspace root"

        cmd = _gradle_cmd(gradlew, f":{module}:assemble{variant}", "--no-daemon")
        result = subprocess.run(
            cmd,
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = result.stdout + result.stderr
        status = "PASSED" if result.returncode == 0 else "FAILED"
        return f"[Gradle assemble exit {result.returncode} — {status}]\n\n{output}"

    @mcp.tool()
    def run_lint(module: str = "app") -> str:
        """Run Android Lint for the given module and return output.

        Args:
            module: Gradle module to lint (default: 'app').

        Returns:
            Combined stdout/stderr from the lint invocation.
        """
        gradlew = WORKSPACE_ROOT / "gradlew"
        if not gradlew.exists():
            return "ERROR: gradlew not found in workspace root"

        cmd = _gradle_cmd(gradlew, f":{module}:lint", "--no-daemon")
        result = subprocess.run(
            cmd,
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = result.stdout + result.stderr
        status = "PASSED" if result.returncode == 0 else "FAILED"
        return f"[Gradle lint exit {result.returncode} — {status}]\n\n{output}"

    @mcp.tool()
    def parse_test_results(gradle_output: str) -> str:
        """Parse raw Gradle test output into a structured summary.

        Args:
            gradle_output: The raw stdout/stderr returned by run_gradle_tests.

        Returns:
            JSON string with keys: passed, failed, total, unresolved[], summary.
        """
        text = gradle_output or ""

        # Gradle often prints lines like: "123 tests completed, 5 failed" or "5 failed"
        completed_match = re.search(r"(\d+)\s+(?:tests?\s+)?completed", text, re.IGNORECASE)
        failed_match = re.search(r"(\d+)\s+(?:tests?\s+)?failed", text, re.IGNORECASE)

        total = int(completed_match.group(1)) if completed_match else 0
        failed = int(failed_match.group(1)) if failed_match else 0

        # If we see BUILD SUCCESSFUL but no counts, assume all passed.
        if total == 0 and "BUILD SUCCESSFUL" in text.upper():
            total = 1
            failed = 0

        # If we see BUILD FAILED but no counts, mark one unresolved failure.
        if total == 0 and "BUILD FAILED" in text.upper():
            total = 1
            failed = 1

        passed = max(0, total - failed)

        # Extract failure names/locations, but skip summary lines like "X tests completed, Y failed".
        unresolved: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if re.search(r"\b(completed|failed)\b", stripped, re.IGNORECASE) and re.search(r"\d+\s+(?:tests?\s+)?(?:completed|failed)", stripped, re.IGNORECASE):
                continue
            if re.search(r"FAILED$|FAILURE:|failed\s*\:", stripped, re.IGNORECASE):
                if stripped and stripped not in unresolved and len(unresolved) < 50:
                    unresolved.append(stripped)

        summary = f"{passed}/{total} tests passed, {failed} failed"
        result = {
            "passed": passed,
            "failed": failed,
            "total": total,
            "unresolved": unresolved,
            "summary": summary,
        }
        return json.dumps(result, indent=2)

    @mcp.tool()
    def run_ktlint_detekt(command: str = "ktlint", args: list[str] | None = None) -> str:
        """Run a Kotlin static-analysis tool if available.

        Args:
            command: Tool binary name, e.g. 'ktlint' or 'detekt-cli' (default: 'ktlint').
            args:    Additional CLI arguments (default: checks app/src/main/java).

        Returns:
            Tool output, or a message saying the tool is not installed.
        """
        if args is None:
            args = ["app/src/main/java"]

        binary = subprocess.run(["which", command], capture_output=True, text=True).stdout.strip()
        if not binary:
            return f"ERROR: {command} not found on PATH. Install it to enable Kotlin static analysis."

        cmd = [binary] + args
        result = subprocess.run(
            cmd,
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + result.stderr
        status = "PASSED" if result.returncode == 0 else "FAILED"
        return f"[{command} exit {result.returncode} — {status}]\n\n{output}"

    @mcp.tool()
    def get_build_config() -> str:
        """Read key Gradle build files and return a structured summary.

        Returns:
            Markdown summary of plugins, dependency versions, and module build configuration.
        """
        files = {
            "Version catalog": "gradle/libs.versions.toml",
            "Project build.gradle": "build.gradle.kts",
            "App build.gradle": "app/build.gradle.kts",
            "Settings": "settings.gradle.kts",
        }
        sections = []
        for title, rel in files.items():
            content = _read_if_exists(rel)
            sections.append(f"## {title} ({rel})\n```\n{content}\n```")
        return "\n\n".join(sections)

"""Build / verification tools for the OllamaDev Android project."""

import json
import re
import subprocess
import xml.etree.ElementTree as ET
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


def _run_linter(command: str, args: list[str] | None = None) -> str:
    """Run a Kotlin static-analysis binary if installed; else return a helpful error."""
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


def _run_detekt(args: list[str] | None = None) -> str:
    """Run detekt (tries 'detekt-cli' then 'detekt') with the given CLI args."""
    if args is None:
        args = ["--input", "app/src/main/java"]
    command = ""
    binary = ""
    for name in ("detekt-cli", "detekt"):
        candidate = subprocess.run(["which", name], capture_output=True, text=True).stdout.strip()
        if candidate:
            command = name
            binary = candidate
            break
    if not binary:
        return "ERROR: detekt not found on PATH (tried 'detekt-cli' and 'detekt'). Install it to enable static analysis."

    result = subprocess.run(
        [binary] + args,
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = result.stdout + result.stderr
    status = "PASSED" if result.returncode == 0 else "FAILED"
    return f"[{command} exit {result.returncode} — {status}]\n\n{output}"


def _parse_junit_xml_text(xml_text: str, source: str) -> dict:
    """Parse a JUnit XML report (testsuite/testcase) into a structured summary dict."""
    root = ET.fromstring(xml_text)
    suites = [root] if root.tag == "testsuite" else list(root)
    total = failures = errors = skipped = 0
    time_total = 0.0
    suite_results: list[dict] = []
    failure_details: list[dict] = []
    for suite in suites:
        if suite.tag != "testsuite":
            continue
        name = suite.get("name", "?")
        t = int(suite.get("tests", 0) or 0)
        f = int(suite.get("failures", 0) or 0)
        e = int(suite.get("errors", 0) or 0)
        s = int(suite.get("skipped", 0) or 0)
        total += t
        failures += f
        errors += e
        skipped += s
        time_total += float(suite.get("time", 0) or 0)
        suite_results.append({"name": name, "tests": t, "failures": f, "errors": e, "skipped": s})
        for case in suite.findall("testcase"):
            failed = case.find("failure")
            error_el = case.find("error")
            if failed is not None or error_el is not None:
                detail = failed if failed is not None else error_el
                failure_details.append(
                    {
                        "class": case.get("classname", ""),
                        "method": case.get("name", ""),
                        "type": "failure" if failed is not None else "error",
                        "message": (detail.get("message") or "")[:500],
                    }
                )
    passed = total - failures - errors
    return {
        "source": source,
        "total": total,
        "passed": passed,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "time_seconds": round(time_total, 2),
        "suites": suite_results,
        "failure_details": failure_details,
        "summary": f"{passed}/{total} tests passed, {failures} failed, {errors} errored, {skipped} skipped",
    }


def _parse_jacoco_xml_text(xml_text: str, source: str) -> dict:
    """Parse a JaCoCo XML report into per-counter and overall coverage percentages."""
    root = ET.fromstring(xml_text)
    counters: dict[str, dict] = {}
    for counter in root.findall(".//counter"):
        ctype = counter.get("type", "")
        missed = int(counter.get("missed", 0) or 0)
        covered = int(counter.get("covered", 0) or 0)
        bucket = counters.setdefault(ctype, {"missed": 0, "covered": 0})
        bucket["missed"] += missed
        bucket["covered"] += covered

    def pct(missed: int, covered: int) -> float:
        denom = missed + covered
        return round(100.0 * covered / denom, 2) if denom else 0.0

    total_missed = sum(c["missed"] for c in counters.values())
    total_covered = sum(c["covered"] for c in counters.values())
    return {
        "source": source,
        "counters": {
            k: {"missed": c["missed"], "covered": c["covered"], "coverage_pct": pct(c["missed"], c["covered"])}
            for k, c in counters.items()
        },
        "overall": {
            "missed": total_missed,
            "covered": total_covered,
            "coverage_pct": pct(total_missed, total_covered),
        },
    }


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
        return _run_linter(command, args)

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

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": True})
    def run_ktlint(args: list[str] | None = None) -> str:
        """Run ktlint over Kotlin sources (default: app/src/main/java).

        Args:
            args: Optional CLI arguments (default: checks app/src/main/java).

        Returns:
            Tool output, or a message saying ktlint is not installed.
        """
        return _run_linter("ktlint", args)

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": True})
    def run_detekt(args: list[str] | None = None) -> str:
        """Run detekt over Kotlin sources (default: --input app/src/main/java).

        Tries the 'detekt-cli' binary first, then 'detekt'.

        Args:
            args: Optional detekt CLI arguments.

        Returns:
            Tool output, or a message saying detekt is not installed.
        """
        return _run_detekt(args)

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": True})
    def parse_test_results_xml(
        results_dir: str = "app/build/test-results/testDebugUnitTest",
        raw_xml: str = "",
    ) -> str:
        """Parse JUnit XML test reports (Gradle's build/test-results) into structured JSON.

        Args:
            results_dir: Directory of JUnit XML files, relative to the workspace root
                         (default: app/build/test-results/testDebugUnitTest).
            raw_xml:     Optional XML text to parse directly instead of scanning results_dir.

        Returns:
            JSON summary: totals, per-suite breakdown, and failure details.
        """
        if raw_xml.strip():
            try:
                return json.dumps(_parse_junit_xml_text(raw_xml, "raw_xml"), indent=2)
            except ET.ParseError as exc:
                return json.dumps({"error": f"Invalid XML: {exc}"}, indent=2)

        base = WORKSPACE_ROOT / results_dir
        if not base.is_dir():
            return json.dumps(
                {
                    "error": f"Test-results directory not found: {results_dir}",
                    "hint": "Run run_gradle_tests first to generate JUnit XML reports.",
                },
                indent=2,
            )
        files = sorted(base.glob("*.xml"))
        if not files:
            return json.dumps({"error": f"No JUnit XML files found in {results_dir}"}, indent=2)

        parsed = []
        for f in files:
            try:
                parsed.append(_parse_junit_xml_text(f.read_text(encoding="utf-8"), str(f.relative_to(WORKSPACE_ROOT))))
            except ET.ParseError as exc:
                parsed.append({"source": str(f.relative_to(WORKSPACE_ROOT)), "error": str(exc)})

        totals = {"total": 0, "passed": 0, "failures": 0, "errors": 0, "skipped": 0, "files": len(parsed)}
        for entry in parsed:
            if "total" in entry:
                totals["total"] += entry["total"]
                totals["passed"] += entry["passed"]
                totals["failures"] += entry["failures"]
                totals["errors"] += entry["errors"]
                totals["skipped"] += entry["skipped"]
        totals["summary"] = f"{totals['passed']}/{totals['total']} tests passed across {totals['files']} file(s)"
        return json.dumps({"totals": totals, "files": parsed}, indent=2)

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": True})
    def get_coverage_summary(results_dir: str = "app/build/reports/jacoco/jacocoTestReport") -> str:
        """Read a JaCoCo XML coverage report and return structured coverage percentages.

        Args:
            results_dir: Directory containing the JaCoCo XML report, relative to the
                         workspace root (default: app/build/reports/jacoco/jacocoTestReport).

        Returns:
            JSON with per-counter (LINE, BRANCH, INSTRUCTION) and overall coverage, or a
            hint when no JaCoCo report has been generated yet.
        """
        base = WORKSPACE_ROOT / results_dir
        files = sorted(base.glob("*.xml")) if base.is_dir() else []
        if not files:
            return json.dumps(
                {
                    "error": f"No JaCoCo XML report found in {results_dir}",
                    "hint": "Enable JaCoCo (apply plugin 'jacoco' + a jacocoTestReport task in app/build.gradle.kts), "
                            "then run ':app:testDebugUnitTest :app:jacocoTestReport'.",
                },
                indent=2,
            )
        parsed = []
        for f in files:
            try:
                parsed.append(_parse_jacoco_xml_text(f.read_text(encoding="utf-8"), str(f.relative_to(WORKSPACE_ROOT))))
            except ET.ParseError as exc:
                parsed.append({"source": str(f.relative_to(WORKSPACE_ROOT)), "error": str(exc)})
        return json.dumps(parsed[0] if len(parsed) == 1 else parsed, indent=2)

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": False})
    def run_instrumented_tests(module: str = "app", variant: str = "Debug", test_filter: str = "") -> str:
        """Run Android instrumented tests (connectedAndroidTest) on a connected device/emulator.

        Requires adb on PATH and an attached device; otherwise returns a structured JSON message.

        Args:
            module:      Gradle module with androidTest sources (default: 'app').
            variant:     Build variant (default: 'Debug').
            test_filter: Optional --tests filter (e.g. 'com.example.ui.ScreenshotDriverTest').

        Returns:
            JSON with pass/fail status and combined gradle output.
        """
        adb = subprocess.run(["which", "adb"], capture_output=True, text=True).stdout.strip()
        if not adb:
            return json.dumps(
                {"status": "NO_DEVICE", "detail": "adb not found on PATH; cannot run instrumented tests."},
                indent=2,
            )

        devices_out = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=30).stdout
        connected = [ln for ln in devices_out.splitlines() if "\tdevice" in ln]
        if not connected:
            return json.dumps(
                {
                    "status": "NO_DEVICE",
                    "detail": "No connected Android device/emulator (adb devices returned none). "
                              "Start an emulator or plug in a device, then retry.",
                },
                indent=2,
            )

        gradlew = WORKSPACE_ROOT / "gradlew"
        if not gradlew.exists():
            return json.dumps({"status": "FAILED", "error": "gradlew not found in workspace root"}, indent=2)

        task = f":{module}:connected{variant.capitalize()}AndroidTest"
        cmd = _gradle_cmd(gradlew, task, "--no-daemon")
        if test_filter:
            cmd += ["--tests", test_filter]
        try:
            result = subprocess.run(cmd, cwd=str(WORKSPACE_ROOT), capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired:
            return json.dumps({"status": "TIMEOUT", "task": task}, indent=2)
        output = result.stdout + result.stderr
        status = "PASSED" if result.returncode == 0 else "FAILED"
        return json.dumps(
            {"status": status, "returncode": result.returncode, "task": task, "output": output[-8000:]},
            indent=2,
        )

    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": False})
    def run_screenshot_tests(
        module: str = "app",
        mode: str = "record",
        test_filter: str = "com.example.ui.ScreenshotDriverTest",
    ) -> str:
        """Run Roborazzi screenshot tests on the JVM (no emulator required).

        Args:
            module:      Gradle module (default: 'app').
            mode:        'record' regenerates golden images; 'verify' asserts they match
                         the committed goldens (default: 'record').
            test_filter: JUnit test class that drives the screenshots (default: the app's
                         ScreenshotDriverTest).

        Returns:
            JSON with pass/fail status and combined gradle output.
        """
        mode = mode.lower()
        if mode not in ("record", "verify"):
            raise ValueError("mode must be 'record' or 'verify'")
        gradlew = WORKSPACE_ROOT / "gradlew"
        if not gradlew.exists():
            return json.dumps({"status": "FAILED", "error": "gradlew not found in workspace root"}, indent=2)

        task = f":{module}:{mode}RoborazziDebug"
        cmd = _gradle_cmd(gradlew, task, "--no-daemon")
        if test_filter:
            cmd += ["--tests", test_filter]
        try:
            result = subprocess.run(cmd, cwd=str(WORKSPACE_ROOT), capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired:
            return json.dumps({"status": "TIMEOUT", "task": task}, indent=2)
        output = result.stdout + result.stderr
        status = "PASSED" if result.returncode == 0 else "FAILED"
        return json.dumps(
            {"status": status, "returncode": result.returncode, "task": task, "output": output[-8000:]},
            indent=2,
        )

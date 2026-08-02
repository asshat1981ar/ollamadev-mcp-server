"""Tests for the verification/testing tools in build.py."""

import asyncio
import json
import types
from pathlib import Path

import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ollamadev_mcp_server.tools import build

JUNIT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="com.example.FooTest" tests="4" failures="1" errors="1" skipped="1" time="1.5">
    <testcase name="passes" classname="com.example.FooTest" time="0.1"/>
    <testcase name="flaky" classname="com.example.FooTest" time="0.2">
      <failure message="boom">stack trace</failure>
    </testcase>
    <testcase name="broken" classname="com.example.FooTest" time="0.3">
      <error message="oops">stack</error>
    </testcase>
    <testcase name="skipped" classname="com.example.FooTest" time="0.0">
      <skipped/>
    </testcase>
  </testsuite>
</testsuites>
"""

JACOCO_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<report name="jacocoTestReport">
  <package name="com/example">
    <counter type="INSTRUCTION" missed="10" covered="90"/>
    <counter type="LINE" missed="5" covered="95"/>
    <counter type="BRANCH" missed="3" covered="7"/>
  </package>
</report>
"""


def _make_server(tmp_workspace: Path) -> MCPServer:
    import ollamadev_mcp_server.tools.build as build_mod
    build_mod.WORKSPACE_ROOT = tmp_workspace
    mcp = MCPServer("Test Verification")
    build.register(mcp)
    return mcp


def _fake_subprocess(monkeypatch, results: dict):
    """Replace build.subprocess.run, falling back to the real one for unlisted cmds."""
    real_run = build.subprocess.run

    def fake_run(cmd, *args, **kwargs):
        key = tuple(cmd)
        if key in results:
            return results[key]
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(build.subprocess, "run", fake_run)


# --- JUnit XML parsing ---


def test_parse_junit_xml_text_aggregates():
    data = build._parse_junit_xml_text(JUNIT_XML, "TEST-com.example.FooTest.xml")
    assert data["total"] == 4
    assert data["passed"] == 2
    assert data["failures"] == 1
    assert data["errors"] == 1
    assert data["skipped"] == 1
    assert len(data["failure_details"]) == 2
    assert data["failure_details"][0]["method"] == "flaky"
    assert data["failure_details"][0]["type"] == "failure"
    assert data["failure_details"][1]["type"] == "error"
    assert "2/4 tests passed" in data["summary"]


def test_parse_test_results_xml_from_dir(tmp_path):
    results_dir = tmp_path / "app/build/test-results/testDebugUnitTest"
    results_dir.mkdir(parents=True)
    (results_dir / "TEST-com.example.FooTest.xml").write_text(JUNIT_XML, encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("parse_test_results_xml", {}))
    data = json.loads(result.content[0].text)
    assert data["totals"]["total"] == 4
    assert data["totals"]["passed"] == 2
    assert data["totals"]["files"] == 1
    assert "2/4 tests passed" in data["totals"]["summary"]


def test_parse_test_results_xml_raw_xml(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("parse_test_results_xml", {"raw_xml": JUNIT_XML}))
    data = json.loads(result.content[0].text)
    assert data["source"] == "raw_xml"
    assert data["total"] == 4


def test_parse_test_results_xml_dir_missing(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("parse_test_results_xml", {}))
    data = json.loads(result.content[0].text)
    assert "not found" in data["error"]


def test_parse_test_results_xml_invalid_raw(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("parse_test_results_xml", {"raw_xml": "<testsuite>"}))
    data = json.loads(result.content[0].text)
    assert "Invalid XML" in data["error"]


# --- Coverage ---


def test_parse_jacoco_xml_text_percentages():
    data = build._parse_jacoco_xml_text(JACOCO_XML, "jacocoTestReport.xml")
    assert data["counters"]["LINE"]["missed"] == 5
    assert data["counters"]["LINE"]["covered"] == 95
    assert data["counters"]["LINE"]["coverage_pct"] == 95.0
    assert data["counters"]["INSTRUCTION"]["coverage_pct"] == 90.0
    # (90 + 95 + 7) / (10 + 90 + 5 + 95 + 3 + 7) = 192 / 210
    assert data["overall"]["coverage_pct"] == pytest.approx(91.43, abs=0.01)


def test_get_coverage_summary_found(tmp_path):
    report = tmp_path / "app/build/reports/jacoco/jacocoTestReport"
    report.mkdir(parents=True)
    (report / "jacocoTestReport.xml").write_text(JACOCO_XML, encoding="utf-8")
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("get_coverage_summary", {}))
    data = json.loads(result.content[0].text)
    assert data["source"] == "app/build/reports/jacoco/jacocoTestReport/jacocoTestReport.xml"
    assert data["counters"]["LINE"]["coverage_pct"] == 95.0


def test_get_coverage_summary_not_found(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("get_coverage_summary", {}))
    data = json.loads(result.content[0].text)
    assert "No JaCoCo XML report" in data["error"]
    assert "jacocoTestReport" in data["hint"]


# --- Linters ---


def test_run_ktlint_missing_binary(tmp_path, monkeypatch):
    _fake_subprocess(monkeypatch, {("which", "ktlint"): types.SimpleNamespace(returncode=1, stdout="", stderr="")})
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("run_ktlint", {}))
    assert "ktlint not found on PATH" in result.content[0].text


def test_run_ktlint_installed_passes(tmp_path, monkeypatch):
    _fake_subprocess(
        monkeypatch,
        {
            ("which", "ktlint"): types.SimpleNamespace(returncode=0, stdout="/usr/bin/ktlint\n", stderr=""),
            ("/usr/bin/ktlint", "app/src/main/java"): types.SimpleNamespace(returncode=0, stdout="clean\n", stderr=""),
        },
    )
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("run_ktlint", {}))
    assert "[ktlint exit 0 — PASSED]" in result.content[0].text
    assert "clean" in result.content[0].text


def test_run_ktlint_installed_fails(tmp_path, monkeypatch):
    _fake_subprocess(
        monkeypatch,
        {
            ("which", "ktlint"): types.SimpleNamespace(returncode=0, stdout="/usr/bin/ktlint\n", stderr=""),
            ("/usr/bin/ktlint", "app/src/main/java"): types.SimpleNamespace(returncode=1, stdout="", stderr="lint errors"),
        },
    )
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("run_ktlint", {}))
    assert "[ktlint exit 1 — FAILED]" in result.content[0].text


def test_run_detekt_missing_binary(tmp_path, monkeypatch):
    _fake_subprocess(
        monkeypatch,
        {
            ("which", "detekt-cli"): types.SimpleNamespace(returncode=1, stdout="", stderr=""),
            ("which", "detekt"): types.SimpleNamespace(returncode=1, stdout="", stderr=""),
        },
    )
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("run_detekt", {}))
    assert "detekt not found on PATH" in result.content[0].text


def test_run_detekt_installed(tmp_path, monkeypatch):
    _fake_subprocess(
        monkeypatch,
        {
            ("which", "detekt-cli"): types.SimpleNamespace(returncode=0, stdout="/usr/bin/detekt-cli\n", stderr=""),
            ("/usr/bin/detekt-cli", "--input", "app/src/main/java"): types.SimpleNamespace(
                returncode=0, stdout="ok\n", stderr=""
            ),
        },
    )
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("run_detekt", {}))
    assert "[detekt-cli exit 0 — PASSED]" in result.content[0].text
    assert "ok" in result.content[0].text


# --- Instrumented tests ---


def test_run_instrumented_tests_no_adb(tmp_path, monkeypatch):
    _fake_subprocess(monkeypatch, {("which", "adb"): types.SimpleNamespace(returncode=1, stdout="", stderr="")})
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("run_instrumented_tests", {}))
    data = json.loads(result.content[0].text)
    assert data["status"] == "NO_DEVICE"
    assert "adb not found" in data["detail"]


def test_run_instrumented_tests_no_device(tmp_path, monkeypatch):
    _fake_subprocess(
        monkeypatch,
        {
            ("which", "adb"): types.SimpleNamespace(returncode=0, stdout="/usr/bin/adb\n", stderr=""),
            ("/usr/bin/adb", "devices"): types.SimpleNamespace(returncode=0, stdout="List of devices attached\n\n", stderr=""),
        },
    )
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("run_instrumented_tests", {}))
    data = json.loads(result.content[0].text)
    assert data["status"] == "NO_DEVICE"
    assert "No connected" in data["detail"]


def test_run_instrumented_tests_missing_gradlew_with_device(tmp_path, monkeypatch):
    _fake_subprocess(
        monkeypatch,
        {
            ("which", "adb"): types.SimpleNamespace(returncode=0, stdout="/usr/bin/adb\n", stderr=""),
            ("/usr/bin/adb", "devices"): types.SimpleNamespace(
                returncode=0, stdout="List of devices attached\nemulator-5554\tdevice\n", stderr=""
            ),
        },
    )
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("run_instrumented_tests", {}))
    data = json.loads(result.content[0].text)
    assert data["status"] == "FAILED"
    assert "gradlew not found" in data["error"]


# --- Screenshot tests ---


def test_run_screenshot_tests_bad_mode(tmp_path):
    mcp = _make_server(tmp_path)
    with pytest.raises(ToolError, match="mode must be 'record' or 'verify'"):
        asyncio.run(mcp.call_tool("run_screenshot_tests", {"mode": "delete"}))


def test_run_screenshot_tests_missing_gradlew(tmp_path):
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("run_screenshot_tests", {}))
    data = json.loads(result.content[0].text)
    assert data["status"] == "FAILED"
    assert "gradlew not found" in data["error"]


def test_run_screenshot_tests_invokes_gradle(tmp_path):
    gradlew = tmp_path / "gradlew"
    gradlew.write_text("#!/bin/sh\necho \"ran:$@\"\nexit 0\n", encoding="utf-8")
    gradlew.chmod(0o755)
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("run_screenshot_tests", {}))
    data = json.loads(result.content[0].text)
    assert data["status"] == "PASSED"
    assert data["task"] == ":app:recordRoborazziDebug"
    assert ":app:recordRoborazziDebug" in data["output"]
    assert "com.example.ui.ScreenshotDriverTest" in data["output"]


def test_run_screenshot_tests_verify_mode(tmp_path):
    gradlew = tmp_path / "gradlew"
    gradlew.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    gradlew.chmod(0o755)
    mcp = _make_server(tmp_path)
    result = asyncio.run(mcp.call_tool("run_screenshot_tests", {"mode": "verify"}))
    data = json.loads(result.content[0].text)
    assert data["status"] == "PASSED"
    assert data["task"] == ":app:verifyRoborazziDebug"

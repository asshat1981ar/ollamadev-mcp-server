"""Tests for context window management."""

from ollamadev_mcp_server.context_manager import (
    CHARS_PER_TOKEN,
    ContextWindow,
    build_suggestion_context,
    estimate_tokens,
    format_tool_result_for_context,
)


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_string(self):
        assert estimate_tokens("hello") == 1  # 5 chars / 4 = 1

    def test_longer_string(self):
        assert estimate_tokens("hello world") == 2  # 11 chars / 4 = 2

    def test_exact_multiple(self):
        assert estimate_tokens("1234") == 1  # 4 chars / 4 = 1
        assert estimate_tokens("12345678") == 2  # 8 chars / 4 = 2


class TestContextWindow:
    def test_empty_window(self):
        window = ContextWindow(total_budget=100)
        result = window.assemble()
        assert result == ""

    def test_single_section_within_budget(self):
        window = ContextWindow(total_budget=1000)
        window.add_section("goal", "Fix authentication bug", priority=100)
        result = window.assemble()
        assert "## goal" in result
        assert "Fix authentication bug" in result

    def test_multiple_sections_within_budget(self):
        window = ContextWindow(total_budget=1000)
        window.add_section("goal", "Fix bug", priority=100)
        window.add_section("phase", "IMPLEMENTATION", priority=90)
        result = window.assemble()
        assert "## goal" in result
        assert "## phase" in result

    def test_priority_ordering(self):
        window = ContextWindow(total_budget=1000)
        window.add_section("low", "Low priority content", priority=10)
        window.add_section("high", "High priority content", priority=100)
        result = window.assemble()
        # High priority should appear first
        high_pos = result.find("## high")
        low_pos = result.find("## low")
        assert high_pos < low_pos

    def test_truncation_when_over_budget(self):
        # Create a window with very small budget
        window = ContextWindow(total_budget=10)  # 10 tokens = 40 chars
        window.add_section("large", "x" * 200, priority=100)
        result = window.assemble()
        # Should be truncated
        assert "(truncated)" in result
        assert len(result) < 200

    def test_smart_truncation_at_newline(self):
        window = ContextWindow(total_budget=10)
        content = "Line 1\nLine 2\nLine 3\n" + "x" * 100
        window.add_section("content", content, priority=100)
        result = window.assemble()
        # Should truncate at a newline if possible
        assert "..." in result

    def test_smart_truncation_at_sentence(self):
        window = ContextWindow(total_budget=10)
        content = "First sentence. Second sentence. " + "x" * 100
        window.add_section("content", content, priority=100)
        result = window.assemble()
        assert "..." in result

    def test_sections_separated_by_blank_lines(self):
        window = ContextWindow(total_budget=1000)
        window.add_section("section1", "Content 1", priority=100)
        window.add_section("section2", "Content 2", priority=90)
        result = window.assemble()
        # Sections should be separated by blank lines
        assert "\n\n" in result


class TestBuildSuggestionContext:
    def test_basic_context(self):
        result = build_suggestion_context(
            goal="Fix bug",
            phase="IMPLEMENTATION",
            tool_results=[],
            tool_catalog="# Tools\n- ping",
            max_tokens=1000,
        )
        assert "Sprint Goal" in result
        assert "Fix bug" in result
        assert "Current Phase" in result
        assert "IMPLEMENTATION" in result

    def test_with_tool_results(self):
        tool_results = [
            {"tool_name": "search_workspace", "text": "Found 5 matches"},
            {"tool_name": "read_workspace_file", "text": "File content..."},
        ]
        result = build_suggestion_context(
            goal="Fix bug",
            phase="IMPLEMENTATION",
            tool_results=tool_results,
            tool_catalog="# Tools",
            max_tokens=1000,
        )
        assert "Recent Actions" in result
        assert "search_workspace" in result

    def test_respects_max_tokens(self):
        # Create a very small budget
        result = build_suggestion_context(
            goal="Fix bug",
            phase="IMPLEMENTATION",
            tool_results=[],
            tool_catalog="x" * 10000,
            max_tokens=10,  # Very small budget
        )
        # Should be truncated
        assert len(result) < 10000


class TestFormatToolResultForContext:
    def test_short_result(self):
        result = format_tool_result_for_context("ping", "pong", max_chars=500)
        assert result == "[ping] pong"

    def test_long_result_truncated(self):
        long_result = "x" * 1000
        result = format_tool_result_for_context("search", long_result, max_chars=100)
        assert result.startswith("[search] ")
        assert "..." in result
        assert len(result) < 200

    def test_json_result_extracts_key_fields(self):
        import json
        json_result = json.dumps({
            "status": "PASSED",
            "total": 10,
            "passed": 8,
            "failed": 2,
        })
        result = format_tool_result_for_context("run_tests", json_result, max_chars=500)
        assert "[run_tests]" in result
        assert "status=PASSED" in result

    def test_json_result_with_error(self):
        import json
        json_result = json.dumps({
            "status": "FAILED",
            "error": "Connection timeout",
        })
        result = format_tool_result_for_context("api_call", json_result, max_chars=500)
        assert "[api_call]" in result
        assert "status=FAILED" in result
        assert "error=Connection timeout" in result

    def test_invalid_json_falls_back_to_truncation(self):
        invalid_json = "{invalid json" * 10  # Make it longer than max_chars
        result = format_tool_result_for_context("parse", invalid_json, max_chars=50)
        assert "[parse]" in result
        assert "..." in result

"""Tests for timeout configuration."""

from ollamadev_mcp_server.timeouts import (
    DEFAULT_AUTONOMOUS_TIMEOUT,
    DEFAULT_GRADLE_TIMEOUT,
    DEFAULT_LLM_TIMEOUT,
    DEFAULT_SHELL_TIMEOUT,
    DEFAULT_TOOL_TIMEOUT,
    TOOL_TIMEOUTS,
    get_all_timeouts,
    get_timeout,
)


class TestGetTimeout:
    def test_known_tool(self):
        assert get_timeout("search_workspace") == 30
        assert get_timeout("run_gradle_tests") == DEFAULT_GRADLE_TIMEOUT
        assert get_timeout("suggest_next_action") == DEFAULT_LLM_TIMEOUT
        assert get_timeout("run_autonomous_sprint") == DEFAULT_AUTONOMOUS_TIMEOUT

    def test_unknown_tool_uses_default(self):
        assert get_timeout("unknown_tool") == DEFAULT_TOOL_TIMEOUT

    def test_all_timeouts_are_positive(self):
        for name, timeout in TOOL_TIMEOUTS.items():
            assert timeout > 0, f"Timeout for {name} should be positive"


class TestGetAllTimeouts:
    def test_returns_copy(self):
        t1 = get_all_timeouts()
        t2 = get_all_timeouts()
        assert t1 == t2
        assert t1 is not t2  # Different dict objects

    def test_contains_known_tools(self):
        timeouts = get_all_timeouts()
        assert "search_workspace" in timeouts
        assert "run_gradle_tests" in timeouts
        assert "run_shell_command" in timeouts


class TestDefaults:
    def test_defaults_are_reasonable(self):
        assert DEFAULT_TOOL_TIMEOUT == 60
        assert DEFAULT_LLM_TIMEOUT == 120
        assert DEFAULT_SHELL_TIMEOUT == 300
        assert DEFAULT_GRADLE_TIMEOUT == 600
        assert DEFAULT_AUTONOMOUS_TIMEOUT == 3600

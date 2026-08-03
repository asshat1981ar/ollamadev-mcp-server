"""Tests for rate limiting."""

import time
import pytest
from unittest.mock import patch

from ollamadev_mcp_server.rate_limit import (
    TokenBucket,
    RateLimiter,
    check_rate_limit,
    get_limiter,
    TOOL_RATE_LIMITS,
)
from ollamadev_mcp_server.errors import OllamaDevError


class TestTokenBucket:
    def test_initial_tokens_equal_burst(self):
        bucket = TokenBucket(rate_per_min=60, burst=10)
        # Should be able to consume all burst tokens
        for _ in range(10):
            assert bucket.consume() is True
        # 11th should fail
        assert bucket.consume() is False

    def test_tokens_replenish_over_time(self):
        bucket = TokenBucket(rate_per_min=600, burst=5)  # 10/sec
        # Drain all tokens
        for _ in range(5):
            bucket.consume()
        assert bucket.consume() is False
        # Wait a bit for replenishment
        time.sleep(0.2)
        # Should have ~2 tokens now
        assert bucket.consume() is True

    def test_consume_multiple_tokens(self):
        bucket = TokenBucket(rate_per_min=60, burst=10)
        assert bucket.consume(5) is True
        assert bucket.consume(5) is True
        assert bucket.consume(1) is False


class TestRateLimiter:
    def test_global_limit(self):
        limiter = RateLimiter()
        with patch("ollamadev_mcp_server.rate_limit.DEFAULT_RATE_LIMIT", 5), \
             patch("ollamadev_mcp_server.rate_limit.DEFAULT_BURST_LIMIT", 5), \
             patch("ollamadev_mcp_server.rate_limit.RATE_LIMIT_ENABLED", True):
            for _ in range(5):
                limiter.check("client-a")
            with pytest.raises(OllamaDevError) as exc_info:
                limiter.check("client-a")
            assert exc_info.value.code == "RATE_LIMIT_EXCEEDED"

    def test_per_tool_limit(self):
        limiter = RateLimiter()
        with patch("ollamadev_mcp_server.rate_limit.RATE_LIMIT_ENABLED", True), \
             patch("ollamadev_mcp_server.rate_limit.DEFAULT_RATE_LIMIT", 1000), \
             patch("ollamadev_mcp_server.rate_limit.DEFAULT_BURST_LIMIT", 1000):
            # TOOL_RATE_LIMITS["run_shell_command"] = 5, burst = max(1, 5//2) = 2
            # First 2 calls should succeed
            limiter.check("client-a", tool_name="run_shell_command")
            limiter.check("client-a", tool_name="run_shell_command")
            # 3rd call should fail (burst=2)
            with pytest.raises(OllamaDevError) as exc_info:
                limiter.check("client-a", tool_name="run_shell_command")
            assert exc_info.value.code == "TOOL_RATE_LIMIT_EXCEEDED"

    def test_disabled_does_nothing(self):
        limiter = RateLimiter()
        with patch("ollamadev_mcp_server.rate_limit.RATE_LIMIT_ENABLED", False):
            # Should not raise even with many calls
            for _ in range(1000):
                limiter.check("client-a")

    def test_different_clients_independent(self):
        limiter = RateLimiter()
        with patch("ollamadev_mcp_server.rate_limit.RATE_LIMIT_ENABLED", True), \
             patch("ollamadev_mcp_server.rate_limit.DEFAULT_RATE_LIMIT", 2), \
             patch("ollamadev_mcp_server.rate_limit.DEFAULT_BURST_LIMIT", 2):
            limiter.check("client-a")
            limiter.check("client-a")
            # client-a is exhausted
            with pytest.raises(OllamaDevError):
                limiter.check("client-a")
            # client-b should still work
            limiter.check("client-b")

    def test_reset_specific_client(self):
        limiter = RateLimiter()
        with patch("ollamadev_mcp_server.rate_limit.RATE_LIMIT_ENABLED", True), \
             patch("ollamadev_mcp_server.rate_limit.DEFAULT_RATE_LIMIT", 1), \
             patch("ollamadev_mcp_server.rate_limit.DEFAULT_BURST_LIMIT", 1):
            limiter.check("client-a")
            with pytest.raises(OllamaDevError):
                limiter.check("client-a")
            limiter.reset("client-a")
            limiter.check("client-a")  # Should work after reset

    def test_reset_all_clients(self):
        limiter = RateLimiter()
        with patch("ollamadev_mcp_server.rate_limit.RATE_LIMIT_ENABLED", True), \
             patch("ollamadev_mcp_server.rate_limit.DEFAULT_RATE_LIMIT", 1), \
             patch("ollamadev_mcp_server.rate_limit.DEFAULT_BURST_LIMIT", 1):
            limiter.check("client-a")
            limiter.check("client-b")
            limiter.reset()
            limiter.check("client-a")
            limiter.check("client-b")

    def test_unknown_tool_uses_global_only(self):
        limiter = RateLimiter()
        with patch("ollamadev_mcp_server.rate_limit.RATE_LIMIT_ENABLED", True), \
             patch("ollamadev_mcp_server.rate_limit.DEFAULT_RATE_LIMIT", 100), \
             patch("ollamadev_mcp_server.rate_limit.DEFAULT_BURST_LIMIT", 100):
            # Unknown tool should not hit per-tool limits
            for _ in range(50):
                limiter.check("client-a", tool_name="unknown_tool")


class TestCheckRateLimit:
    def test_module_level_convenience(self):
        with patch("ollamadev_mcp_server.rate_limit.RATE_LIMIT_ENABLED", False):
            check_rate_limit("any-client")  # Should not raise


class TestToolRateLimits:
    def test_known_tools_have_limits(self):
        assert "suggest_next_action" in TOOL_RATE_LIMITS
        assert "run_shell_command" in TOOL_RATE_LIMITS
        assert "run_autonomous_sprint" in TOOL_RATE_LIMITS

    def test_all_limits_are_positive(self):
        for tool, limit in TOOL_RATE_LIMITS.items():
            assert limit > 0, f"{tool} limit should be positive"

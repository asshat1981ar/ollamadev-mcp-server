"""Rate limiting for the OllamaDev MCP server.

Implements a token-bucket algorithm with per-client and per-tool limits.
Rate limiting is **enabled by default** but can be disabled via
``RATE_LIMIT_ENABLED=false``.

Usage::

    from ollamadev_mcp_server.rate_limit import check_rate_limit

    check_rate_limit("client-abc", tool_name="suggest_next_action")
"""

import os
import time
from collections import defaultdict

from ollamadev_mcp_server.errors import OllamaDevError
from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RATE_LIMIT_ENABLED: bool = os.environ.get("RATE_LIMIT_ENABLED", "true").lower() == "true"
DEFAULT_RATE_LIMIT: int = int(os.environ.get("DEFAULT_RATE_LIMIT", "100"))  # req/min
DEFAULT_BURST_LIMIT: int = int(os.environ.get("DEFAULT_BURST_LIMIT", "20"))

# Per-tool rate limits (requests per minute)
TOOL_RATE_LIMITS: dict[str, int] = {
    "suggest_next_action": 10,
    "run_shell_command": 5,
    "run_gradle_tests": 3,
    "run_gradle_test_command": 3,
    "run_gradle_build": 3,
    "run_instrumented_tests": 2,
    "run_autonomous_sprint": 1,
}


# ---------------------------------------------------------------------------
# Token bucket
# ---------------------------------------------------------------------------


class TokenBucket:
    """Thread-unsafe token bucket (callers serialise externally)."""

    def __init__(self, rate_per_min: int, burst: int):
        self.rate_per_min = rate_per_min
        self.burst = burst
        self.tokens = float(burst)
        self.last_update = time.monotonic()

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume *tokens*.  Returns ``True`` on success."""
        now = time.monotonic()
        elapsed_min = (now - self.last_update) / 60.0
        self.last_update = now
        self.tokens = min(self.burst, self.tokens + elapsed_min * self.rate_per_min)
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


class RateLimiter:
    """Per-client rate limiter with optional per-tool sub-limits."""

    def __init__(self) -> None:
        self._global_buckets: dict[str, TokenBucket] = {}
        self._tool_buckets: dict[str, dict[str, TokenBucket]] = defaultdict(dict)

    def check(self, client_id: str, tool_name: str | None = None) -> None:
        """Check rate limit.  Raises ``OllamaDevError`` (429) if exceeded."""
        if not RATE_LIMIT_ENABLED:
            return

        # Global limit
        if client_id not in self._global_buckets:
            self._global_buckets[client_id] = TokenBucket(DEFAULT_RATE_LIMIT, DEFAULT_BURST_LIMIT)
        if not self._global_buckets[client_id].consume():
            logger.warning("Global rate limit exceeded for client: %s", client_id)
            raise OllamaDevError(
                "Rate limit exceeded. Please wait before making more requests.",
                code="RATE_LIMIT_EXCEEDED",
                status_code=429,
            )

        # Per-tool limit
        if tool_name and tool_name in TOOL_RATE_LIMITS:
            limit = TOOL_RATE_LIMITS[tool_name]
            buckets = self._tool_buckets[tool_name]
            if client_id not in buckets:
                buckets[client_id] = TokenBucket(limit, max(1, limit // 2))
            if not buckets[client_id].consume():
                logger.warning("Tool rate limit exceeded: client=%s tool=%s", client_id, tool_name)
                raise OllamaDevError(
                    f"Rate limit exceeded for tool '{tool_name}'. Limit: {limit}/min",
                    code="TOOL_RATE_LIMIT_EXCEEDED",
                    status_code=429,
                )

    def reset(self, client_id: str | None = None) -> None:
        """Reset buckets.  If *client_id* is ``None``, reset all."""
        if client_id is None:
            self._global_buckets.clear()
            self._tool_buckets.clear()
        else:
            self._global_buckets.pop(client_id, None)
            for tool_buckets in self._tool_buckets.values():
                tool_buckets.pop(client_id, None)


# Global instance
_limiter = RateLimiter()


def check_rate_limit(client_id: str, tool_name: str | None = None) -> None:
    """Check rate limit for a client (module-level convenience)."""
    _limiter.check(client_id, tool_name)


def get_limiter() -> RateLimiter:
    """Return the global ``RateLimiter`` instance (for testing)."""
    return _limiter

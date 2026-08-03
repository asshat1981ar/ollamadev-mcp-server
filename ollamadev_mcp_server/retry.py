"""Retry logic with exponential backoff and jitter.

Provides configurable retry decorators for both sync and async functions.
Used primarily for LLM API calls that may fail transiently.

Usage::

    from ollamadev_mcp_server.retry import with_retry, LLM_RETRY

    @with_retry(LLM_RETRY)
    def call_llm(prompt: str) -> str:
        ...
"""

import asyncio
import functools
import random
import time
from typing import Any, Callable, TypeVar

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------


class RetryConfig:
    """Configuration for retry behavior.

    Attributes:
        max_attempts: Maximum number of attempts (including the first).
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Maximum delay cap in seconds.
        exponential_base: Multiplier for exponential backoff.
        jitter: Whether to add random jitter to delays.
        retryable_exceptions: Tuple of exception types to retry on.
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions

    def compute_delay(self, attempt: int) -> float:
        """Compute delay for a given attempt number (0-based).

        Uses exponential backoff with optional jitter.
        """
        delay = min(
            self.base_delay * (self.exponential_base ** attempt),
            self.max_delay,
        )
        if self.jitter:
            # Full jitter: random value between 0 and computed delay
            delay = random.uniform(0, delay)
        return delay


# ---------------------------------------------------------------------------
# Predefined configs
# ---------------------------------------------------------------------------

DEFAULT_RETRY = RetryConfig(
    max_attempts=3,
    base_delay=1.0,
    retryable_exceptions=(ConnectionError, TimeoutError, OSError),
)

LLM_RETRY = RetryConfig(
    max_attempts=3,
    base_delay=2.0,
    max_delay=30.0,
    retryable_exceptions=(ConnectionError, TimeoutError, OSError),
)

HTTP_RETRY = RetryConfig(
    max_attempts=3,
    base_delay=1.0,
    max_delay=15.0,
    retryable_exceptions=(ConnectionError, TimeoutError),
)


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------


def with_retry(config: RetryConfig | None = None):
    """Decorator that adds retry logic to a sync function.

    Args:
        config: Retry configuration.  Defaults to ``DEFAULT_RETRY``.
    """
    cfg = config or DEFAULT_RETRY

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exc: Exception | None = None
            for attempt in range(cfg.max_attempts):
                try:
                    return func(*args, **kwargs)
                except cfg.retryable_exceptions as exc:
                    last_exc = exc
                    if attempt < cfg.max_attempts - 1:
                        delay = cfg.compute_delay(attempt)
                        logger.warning(
                            "Retry %d/%d for %s after %.1fs: %s",
                            attempt + 1,
                            cfg.max_attempts,
                            func.__name__,
                            delay,
                            exc,
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "All %d attempts failed for %s: %s",
                            cfg.max_attempts,
                            func.__name__,
                            exc,
                        )
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


def with_async_retry(config: RetryConfig | None = None):
    """Decorator that adds retry logic to an async function.

    Args:
        config: Retry configuration.  Defaults to ``DEFAULT_RETRY``.
    """
    cfg = config or DEFAULT_RETRY

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(cfg.max_attempts):
                try:
                    return await func(*args, **kwargs)
                except cfg.retryable_exceptions as exc:
                    last_exc = exc
                    if attempt < cfg.max_attempts - 1:
                        delay = cfg.compute_delay(attempt)
                        logger.warning(
                            "Async retry %d/%d for %s after %.1fs: %s",
                            attempt + 1,
                            cfg.max_attempts,
                            func.__name__,
                            delay,
                            exc,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "All %d async attempts failed for %s: %s",
                            cfg.max_attempts,
                            func.__name__,
                            exc,
                        )
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator

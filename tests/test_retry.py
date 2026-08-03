"""Tests for retry logic with exponential backoff."""

import time
from unittest.mock import Mock, patch

import pytest

from ollamadev_mcp_server.retry import (
    DEFAULT_RETRY,
    HTTP_RETRY,
    LLM_RETRY,
    RetryConfig,
    with_async_retry,
    with_retry,
)


class TestRetryConfig:
    def test_default_config(self):
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.exponential_base == 2.0
        assert config.jitter is True

    def test_compute_delay_exponential(self):
        config = RetryConfig(base_delay=1.0, exponential_base=2.0, jitter=False)
        assert config.compute_delay(0) == 1.0
        assert config.compute_delay(1) == 2.0
        assert config.compute_delay(2) == 4.0
        assert config.compute_delay(3) == 8.0

    def test_compute_delay_max_cap(self):
        config = RetryConfig(base_delay=10.0, max_delay=15.0, jitter=False)
        assert config.compute_delay(0) == 10.0
        assert config.compute_delay(1) == 15.0  # Capped
        assert config.compute_delay(2) == 15.0  # Still capped

    def test_compute_delay_with_jitter(self):
        config = RetryConfig(base_delay=10.0, jitter=True)
        # With jitter, delay should be between 0 and computed delay
        for _ in range(10):
            delay = config.compute_delay(0)
            assert 0 <= delay <= 10.0


class TestPredefinedConfigs:
    def test_default_retry(self):
        assert DEFAULT_RETRY.max_attempts == 3
        assert DEFAULT_RETRY.base_delay == 1.0
        assert ConnectionError in DEFAULT_RETRY.retryable_exceptions

    def test_llm_retry(self):
        assert LLM_RETRY.max_attempts == 3
        assert LLM_RETRY.base_delay == 2.0
        assert LLM_RETRY.max_delay == 30.0

    def test_http_retry(self):
        assert HTTP_RETRY.max_attempts == 3
        assert HTTP_RETRY.base_delay == 1.0
        assert HTTP_RETRY.max_delay == 15.0


class TestWithRetry:
    def test_success_no_retry(self):
        mock_func = Mock(return_value="success")

        @with_retry(DEFAULT_RETRY)
        def test_func():
            return mock_func()

        result = test_func()
        assert result == "success"
        assert mock_func.call_count == 1

    def test_retry_on_failure(self):
        mock_func = Mock(side_effect=[ConnectionError("fail"), "success"])

        @with_retry(RetryConfig(max_attempts=3, base_delay=0.01, jitter=False))
        def test_func():
            return mock_func()

        result = test_func()
        assert result == "success"
        assert mock_func.call_count == 2

    def test_max_attempts_exceeded(self):
        mock_func = Mock(side_effect=ConnectionError("always fails"))

        @with_retry(RetryConfig(max_attempts=3, base_delay=0.01, jitter=False))
        def test_func():
            return mock_func()

        with pytest.raises(ConnectionError, match="always fails"):
            test_func()

        assert mock_func.call_count == 3

    def test_non_retryable_exception(self):
        mock_func = Mock(side_effect=ValueError("not retryable"))

        @with_retry(RetryConfig(max_attempts=3, retryable_exceptions=(ConnectionError,)))
        def test_func():
            return mock_func()

        with pytest.raises(ValueError, match="not retryable"):
            test_func()

        assert mock_func.call_count == 1

    def test_retry_with_args(self):
        mock_func = Mock(side_effect=[ConnectionError(), "result"])

        @with_retry(RetryConfig(max_attempts=3, base_delay=0.01, jitter=False))
        def test_func(a, b, c=None):
            return mock_func(a, b, c=c)

        result = test_func(1, 2, c=3)
        assert result == "result"
        mock_func.assert_called_with(1, 2, c=3)


class TestWithAsyncRetry:
    def test_async_success_no_retry(self):
        import asyncio
        mock_func = Mock(return_value="success")

        @with_async_retry(DEFAULT_RETRY)
        async def test_func():
            return mock_func()

        result = asyncio.run(test_func())
        assert result == "success"
        assert mock_func.call_count == 1

    def test_async_retry_on_failure(self):
        import asyncio
        mock_func = Mock(side_effect=[ConnectionError("fail"), "success"])

        @with_async_retry(RetryConfig(max_attempts=3, base_delay=0.01, jitter=False))
        async def test_func():
            return mock_func()

        result = asyncio.run(test_func())
        assert result == "success"
        assert mock_func.call_count == 2

    def test_async_max_attempts_exceeded(self):
        import asyncio
        mock_func = Mock(side_effect=ConnectionError("always fails"))

        @with_async_retry(RetryConfig(max_attempts=3, base_delay=0.01, jitter=False))
        async def test_func():
            return mock_func()

        with pytest.raises(ConnectionError, match="always fails"):
            asyncio.run(test_func())

        assert mock_func.call_count == 3

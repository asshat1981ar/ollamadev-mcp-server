"""Tests for circuit breaker pattern."""

import time
from unittest.mock import Mock

import pytest

from ollamadev_mcp_server.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpen,
    CircuitState,
    get_anthropic_breaker,
    get_ollama_breaker,
)


class TestCircuitState:
    def test_state_values(self):
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


class TestCircuitBreakerOpen:
    def test_exception_message(self):
        exc = CircuitBreakerOpen("test_service", 30.0)
        assert "test_service" in str(exc)
        assert "30" in str(exc)
        assert exc.service == "test_service"
        assert exc.remaining_seconds == 30.0


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        breaker = CircuitBreaker("test")
        assert breaker.state == CircuitState.CLOSED

    def test_successful_call_keeps_closed(self):
        breaker = CircuitBreaker("test")
        mock_func = Mock(return_value="success")
        result = breaker.call(mock_func)
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED

    def test_failure_increments_count(self):
        breaker = CircuitBreaker("test", failure_threshold=3)
        mock_func = Mock(side_effect=ValueError("fail"))
        
        with pytest.raises(ValueError):
            breaker.call(mock_func)
        
        assert breaker._failure_count == 1
        assert breaker.state == CircuitState.CLOSED

    def test_opens_after_threshold(self):
        breaker = CircuitBreaker("test", failure_threshold=3)
        mock_func = Mock(side_effect=ValueError("fail"))
        
        for _ in range(3):
            with pytest.raises(ValueError):
                breaker.call(mock_func)
        
        assert breaker.state == CircuitState.OPEN

    def test_open_circuit_rejects_calls(self):
        breaker = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)
        mock_func = Mock(side_effect=ValueError("fail"))
        
        # Trigger open state
        for _ in range(2):
            with pytest.raises(ValueError):
                breaker.call(mock_func)
        
        assert breaker.state == CircuitState.OPEN
        
        # Next call should be rejected immediately
        with pytest.raises(CircuitBreakerOpen):
            breaker.call(Mock(return_value="success"))

    def test_half_open_after_recovery_timeout(self):
        breaker = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1)
        mock_func = Mock(side_effect=ValueError("fail"))
        
        # Trigger open state
        for _ in range(2):
            with pytest.raises(ValueError):
                breaker.call(mock_func)
        
        assert breaker.state == CircuitState.OPEN
        
        # Wait for recovery timeout
        time.sleep(0.15)
        
        # Should transition to half-open
        assert breaker.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes_circuit(self):
        breaker = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1)
        mock_func = Mock(side_effect=[ValueError("fail"), ValueError("fail"), "success"])
        
        # Trigger open state
        for _ in range(2):
            with pytest.raises(ValueError):
                breaker.call(mock_func)
        
        assert breaker.state == CircuitState.OPEN
        
        # Wait for recovery timeout
        time.sleep(0.15)
        
        # Successful call should close circuit
        result = breaker.call(mock_func)
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED

    def test_half_open_failure_reopens_circuit(self):
        breaker = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1)
        mock_func = Mock(side_effect=ValueError("fail"))
        
        # Trigger open state
        for _ in range(2):
            with pytest.raises(ValueError):
                breaker.call(mock_func)
        
        # Wait for recovery timeout
        time.sleep(0.15)
        assert breaker.state == CircuitState.HALF_OPEN
        
        # Failed call should reopen circuit
        with pytest.raises(ValueError):
            breaker.call(mock_func)
        
        assert breaker.state == CircuitState.OPEN

    def test_reset(self):
        breaker = CircuitBreaker("test", failure_threshold=2)
        mock_func = Mock(side_effect=ValueError("fail"))
        
        # Trigger open state
        for _ in range(2):
            with pytest.raises(ValueError):
                breaker.call(mock_func)
        
        assert breaker.state == CircuitState.OPEN
        
        # Manual reset
        breaker.reset()
        assert breaker.state == CircuitState.CLOSED
        assert breaker._failure_count == 0

    def test_get_status(self):
        breaker = CircuitBreaker("test", failure_threshold=5, recovery_timeout=60)
        status = breaker.get_status()
        
        assert status["service"] == "test"
        assert status["state"] == "closed"
        assert status["failure_count"] == 0
        assert status["failure_threshold"] == 5
        assert status["recovery_timeout"] == 60

    def test_half_open_max_calls(self):
        breaker = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1, half_open_max_calls=1)
        mock_func = Mock(side_effect=ValueError("fail"))
        
        # Trigger open state
        for _ in range(2):
            with pytest.raises(ValueError):
                breaker.call(mock_func)
        
        # Wait for recovery timeout
        time.sleep(0.15)
        assert breaker.state == CircuitState.HALF_OPEN
        
        # First call in half-open should be allowed
        with pytest.raises(ValueError):
            breaker.call(mock_func)
        
        # Circuit should be open again
        assert breaker.state == CircuitState.OPEN


class TestPreconfiguredBreakers:
    def test_ollama_breaker(self):
        breaker = get_ollama_breaker()
        assert breaker.service == "ollama"
        assert breaker.failure_threshold == 5
        assert breaker.recovery_timeout == 60

    def test_anthropic_breaker(self):
        breaker = get_anthropic_breaker()
        assert breaker.service == "anthropic"
        assert breaker.failure_threshold == 3
        assert breaker.recovery_timeout == 120

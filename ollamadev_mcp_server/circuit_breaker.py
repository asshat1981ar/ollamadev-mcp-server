"""Circuit breaker pattern for external service calls.

Prevents cascading failures by tracking failures and temporarily blocking
calls to failing services.  Three states: CLOSED (normal) → OPEN (failing)
→ HALF_OPEN (testing recovery).

Usage::

    from ollamadev_mcp_server.circuit_breaker import CircuitBreaker

    breaker = CircuitBreaker("ollama", failure_threshold=5, recovery_timeout=60)
    result = breaker.call(ollama_api.generate, prompt="...")
"""

import enum
import threading
import time
from typing import Any, Callable

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Circuit states
# ---------------------------------------------------------------------------


class CircuitState(enum.Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, calls pass through
    OPEN = "open"  # Failing, calls are rejected immediately
    HALF_OPEN = "half_open"  # Testing if service recovered


# ---------------------------------------------------------------------------
# Circuit breaker exception
# ---------------------------------------------------------------------------


class CircuitBreakerOpen(Exception):
    """Raised when circuit is open and call is rejected."""

    def __init__(self, service: str, remaining_seconds: float):
        super().__init__(
            f"Circuit breaker OPEN for '{service}'. "
            f"Try again in {remaining_seconds:.0f}s."
        )
        self.service = service
        self.remaining_seconds = remaining_seconds


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """Thread-safe circuit breaker.

    Attributes:
        service: Name of the service being protected.
        failure_threshold: Number of failures before opening circuit.
        recovery_timeout: Seconds to wait before trying half-open.
        half_open_max_calls: Max calls allowed in half-open state.
    """

    def __init__(
        self,
        service: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
    ):
        self.service = service
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current state, transitioning from OPEN to HALF_OPEN if timeout elapsed."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    logger.info(
                        "Circuit breaker '%s' transitioning OPEN → HALF_OPEN after %.1fs",
                        self.service,
                        elapsed,
                    )
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
            return self._state

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute a function through the circuit breaker.

        Args:
            func: Function to call.
            *args, **kwargs: Arguments to pass to the function.

        Returns:
            The function's return value.

        Raises:
            CircuitBreakerOpen: If circuit is open and call is rejected.
            Exception: Any exception from the function (after recording failure).
        """
        current_state = self.state

        if current_state == CircuitState.OPEN:
            remaining = self.recovery_timeout - (time.monotonic() - self._last_failure_time)
            raise CircuitBreakerOpen(self.service, max(0, remaining))

        if current_state == CircuitState.HALF_OPEN:
            with self._lock:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerOpen(self.service, self.recovery_timeout)
                self._half_open_calls += 1

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                logger.info(
                    "Circuit breaker '%s' transitioning HALF_OPEN → CLOSED (success)",
                    self.service,
                )
                self._state = CircuitState.CLOSED
            self._failure_count = 0

    def _on_failure(self) -> None:
        """Record a failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    logger.warning(
                        "Circuit breaker '%s' → OPEN after %d failures",
                        self.service,
                        self._failure_count,
                    )
                self._state = CircuitState.OPEN

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = 0
            logger.info("Circuit breaker '%s' manually reset to CLOSED", self.service)

    def get_status(self) -> dict[str, Any]:
        """Get circuit breaker status for diagnostics.

        Returns:
            Dict with service name, state, failure count, and thresholds.
        """
        return {
            "service": self.service,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


# ---------------------------------------------------------------------------
# Pre-configured breakers
# ---------------------------------------------------------------------------

_ollama_breaker = CircuitBreaker("ollama", failure_threshold=5, recovery_timeout=60)
_anthropic_breaker = CircuitBreaker("anthropic", failure_threshold=3, recovery_timeout=120)


def get_ollama_breaker() -> CircuitBreaker:
    """Get the global Ollama circuit breaker."""
    return _ollama_breaker


def get_anthropic_breaker() -> CircuitBreaker:
    """Get the global Anthropic circuit breaker."""
    return _anthropic_breaker

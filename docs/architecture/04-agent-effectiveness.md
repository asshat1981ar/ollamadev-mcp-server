# Phase 4: Autonomous Agent Effectiveness

> **Status:** DESIGN  
> **Priority:** P1  
> **Estimated Effort:** 3-4 days  
> **Dependencies:** Phase 1 (logging, timeouts), Phase 2 (auth for agent identity)  

---

## 1. Executive Summary

Phase 4 focuses on making the autonomous agent loop (`run_autonomous_sprint`) and LLM-powered tools (`suggest_next_action`) more robust, efficient, and effective. The current implementation has no retry logic, no circuit breaker, no context window management, and no learning from past tool calls.

### Deliverables

| Component | Module | Lines (est.) |
|-----------|--------|-------------|
| Retry with backoff | `retry.py` | ~120 |
| Circuit breaker | `circuit_breaker.py` | ~100 |
| Context window manager | `context_manager.py` | ~150 |
| Tool call history | `tool_history.py` | ~120 |
| Sprint loop improvements | Refactored `sprint.py` | ~200 |
| Suggestion improvements | Refactored `meta.py` | ~150 |
| Tests | `tests/test_phase4_*.py` | ~400 |
| **Total** | | **~1,240** |

---

## 2. Current State Analysis

### 2.1 No Retry Logic

**Evidence:** `meta.py:470` — Single HTTP call with no retry:

```python
resp = requests.post(endpoint, headers=headers, json=payload, timeout=120)
resp.raise_for_status()
```

**Impact:** Any transient network error, LLM timeout, or temporary overload causes the entire `suggest_next_action` call to fail, which cascades into the autonomous sprint loop failing for that phase iteration.

### 2.2 No Circuit Breaker

**Evidence:** `meta.py:478-512` — Direct HTTP calls to Anthropic with no fallback:

```python
def _ask_anthropic(system_prompt: str, user_prompt: str, model: str) -> str:
    resp = requests.post(
        f"{ANTHROPIC_BASE_URL}/v1/messages",
        headers=headers,
        json=body,
        timeout=120,
    )
    resp.raise_for_status()
```

**Impact:** If the Anthropic API is down, every `suggest_next_action` call with `provider="anthropic"` will wait 120 seconds and then fail. The autonomous sprint loop wastes an entire phase iteration on each attempt.

### 2.3 No Context Window Management

**Evidence:** `sprint.py:63-66` — Simple truncation:

```python
def _truncate_context(context: str, max_chars: int = _MAX_CONTEXT_CHARS) -> str:
    if len(context) <= max_chars:
        return context
    return "..." + context[-(max_chars - 3):]
```

**Impact:** The truncation is naive — it just keeps the last N characters, which may cut in the middle of a word, JSON object, or code block. The `suggest_next_action` prompt includes this truncated context, which may be incoherent.

### 2.4 No Tool Call History

**Evidence:** The autonomous sprint loop accumulates a short context string but does not persist tool call history across phases or sprints.

```python
# sprint.py — _run_autonomous_sprint
context_parts: list[str] = []
# ... actions append to context_parts ...
context = "\n---\n".join(context_parts[-5:])  # Only last 5 actions
```

**Impact:** The agent cannot learn from mistakes made in previous phases or sprints. It may repeat the same failed tool calls.

### 2.5 Autonomous Sprint Loop Issues

**Evidence:** `sprint.py:108-250` — The `_run_autonomous_sprint` function:

```python
async def _run_autonomous_sprint(
    mcp: MCPServer,
    goal: str,
    cycle_id: int = 0,
    max_phase_iterations: int = 3,
    auto_create_backlog_tasks: bool = True,
    model: str = "llama3",
) -> str:
```

**Issues identified:**
1. No overall timeout — can run indefinitely
2. No progress reporting — caller has no visibility into which phase is running
3. No early termination — continues even if all phases are failing
4. No cost tracking — LLM calls are not counted
5. Fixed phase order — cannot skip phases or reorder based on goal
6. No phase-specific prompts — same `suggest_next_action` prompt for all phases

---

## 3. Proposed Architecture

### 3.1 Retry with Exponential Backoff

**Design:** Configurable retry decorator with jitter.

```python
# ollamadev_mcp_server/retry.py
"""Retry logic with exponential backoff and jitter."""

import asyncio
import functools
import random
import time
from typing import Any, Callable, TypeVar

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class RetryConfig:
    """Configuration for retry behavior."""

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
        """Compute delay for a given attempt number (0-based)."""
        delay = min(
            self.base_delay * (self.exponential_base ** attempt),
            self.max_delay,
        )
        if self.jitter:
            delay = delay * (0.5 + random.random())  # 50%-150% of computed delay
        return delay


# Predefined configs
DEFAULT_RETRY = RetryConfig(
    max_attempts=3,
    base_delay=1.0,
    retryable_exceptions=(ConnectionError, TimeoutError, OSError),
)

LLM_RETRY = RetryConfig(
    max_attempts=3,
    base_delay=2.0,
    max_delay=30.0,
    retryable_exceptions=(ConnectionError, TimeoutError),
)

HTTP_RETRY = RetryConfig(
    max_attempts=3,
    base_delay=1.0,
    max_delay=15.0,
    retryable_exceptions=(ConnectionError, TimeoutError),
)


def with_retry(config: RetryConfig | None = None):
    """Decorator that adds retry logic to a sync function."""
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
                            attempt + 1, cfg.max_attempts, func.__name__, delay, exc,
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "All %d attempts failed for %s: %s",
                            cfg.max_attempts, func.__name__, exc,
                        )
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator


def with_async_retry(config: RetryConfig | None = None):
    """Decorator that adds retry logic to an async function."""
    cfg = config or DEFAULT_RETRY

    def decorator(func):
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
                            attempt + 1, cfg.max_attempts, func.__name__, delay, exc,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "All %d async attempts failed for %s: %s",
                            cfg.max_attempts, func.__name__, exc,
                        )
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator
```

### 3.2 Circuit Breaker

**Design:** Three-state circuit breaker (CLOSED → OPEN → HALF_OPEN).

```python
# ollamadev_mcp_server/circuit_breaker.py
"""Circuit breaker pattern for external service calls."""

import enum
import threading
import time
from typing import Any, Callable

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)


class CircuitState(enum.Enum):
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Failing, reject calls
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreakerError(Exception):
    """Raised when circuit is open and call is rejected."""
    def __init__(self, service: str, remaining_seconds: float):
        super().__init__(
            f"Circuit breaker OPEN for '{service}'. "
            f"Try again in {remaining_seconds:.0f}s."
        )
        self.service = service
        self.remaining_seconds = remaining_seconds


class CircuitBreaker:
    """Thread-safe circuit breaker."""

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
        with self._lock:
            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
            return self._state

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute a function through the circuit breaker."""
        state = self.state

        if state == CircuitState.OPEN:
            remaining = self.recovery_timeout - (time.monotonic() - self._last_failure_time)
            raise CircuitBreakerError(self.service, max(0, remaining))

        if state == CircuitState.HALF_OPEN:
            with self._lock:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerError(self.service, self.recovery_timeout)
                self._half_open_calls += 1

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                logger.info("Circuit breaker HALF_OPEN → CLOSED for '%s'", self.service)
                self._state = CircuitState.CLOSED
            self._failure_count = 0

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    logger.warning(
                        "Circuit breaker → OPEN for '%s' after %d failures",
                        self.service, self._failure_count,
                    )
                self._state = CircuitState.OPEN

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = 0

    def get_status(self) -> dict:
        """Get circuit breaker status for health checks."""
        return {
            "service": self.service,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


# Pre-configured circuit breakers
_ollama_breaker = CircuitBreaker("ollama", failure_threshold=5, recovery_timeout=60)
_anthropic_breaker = CircuitBreaker("anthropic", failure_threshold=3, recovery_timeout=120)


def get_ollama_breaker() -> CircuitBreaker:
    return _ollama_breaker


def get_anthropic_breaker() -> CircuitBreaker:
    return _anthropic_breaker
```

### 3.3 Context Window Manager

**Design:** Smart context assembly that respects token budgets and preserves structure.

```python
# ollamadev_mcp_server/context_manager.py
"""Context window management for LLM prompts."""

import json
import re
from typing import Any

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

# Approximate token-to-character ratio (English text ≈ 4 chars/token)
CHARS_PER_TOKEN = 4

# Default context budgets (in tokens)
DEFAULT_CONTEXT_BUDGET = 4096
SYSTEM_PROMPT_BUDGET = 1024
TOOL_CATALOG_BUDGET = 2048
HISTORY_BUDGET = 1024


class ContextWindow:
    """Manages a context window with budget-aware assembly."""

    def __init__(self, total_budget: int = DEFAULT_CONTEXT_BUDGET):
        self.total_budget = total_budget
        self.sections: dict[str, str] = {}
        self.priorities: dict[str, int] = {}  # Higher = kept first

    def add_section(self, name: str, content: str, priority: int = 0) -> None:
        """Add a section to the context window."""
        self.sections[name] = content
        self.priorities[name] = priority

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        return len(text) // CHARS_PER_TOKEN

    def assemble(self) -> str:
        """Assemble sections within budget, respecting priorities."""
        # Sort by priority (highest first)
        sorted_sections = sorted(
            self.sections.items(),
            key=lambda x: self.priorities.get(x[0], 0),
            reverse=True,
        )

        parts: list[str] = []
        used_tokens = 0

        for name, content in sorted_sections:
            content_tokens = self.estimate_tokens(content)
            if used_tokens + content_tokens <= self.total_budget:
                parts.append(f"## {name}\n{content}")
                used_tokens += content_tokens
            else:
                # Try to fit a truncated version
                remaining = self.total_budget - used_tokens
                if remaining > 50:  # Minimum useful content
                    truncated = self._truncate_smart(content, remaining * CHARS_PER_TOKEN)
                    parts.append(f"## {name} (truncated)\n{truncated}")
                    used_tokens += remaining
                    logger.debug(
                        "Truncated section '%s' from %d to %d chars",
                        name, len(content), len(truncated),
                    )
                break

        return "\n\n".join(parts)

    def _truncate_smart(self, text: str, max_chars: int) -> str:
        """Truncate text at a natural boundary (line, sentence, or word)."""
        if len(text) <= max_chars:
            return text

        # Try to truncate at a line boundary
        truncated = text[:max_chars]
        last_newline = truncated.rfind("\n")
        if last_newline > max_chars * 0.5:
            return truncated[:last_newline] + "\n..."

        # Try to truncate at a sentence boundary
        last_sentence = max(
            truncated.rfind(". "),
            truncated.rfind(".\n"),
            truncated.rfind("! "),
            truncated.rfind("? "),
        )
        if last_sentence > max_chars * 0.5:
            return truncated[:last_sentence + 1] + "..."

        # Fall back to word boundary
        last_space = truncated.rfind(" ")
        if last_space > max_chars * 0.5:
            return truncated[:last_space] + "..."

        return truncated[:max_chars - 3] + "..."


def build_suggestion_context(
    goal: str,
    phase: str,
    tool_results: list[dict[str, Any]],
    tool_catalog: str,
    max_tokens: int = DEFAULT_CONTEXT_BUDGET,
) -> str:
    """Build context for the suggest_next_action prompt."""
    window = ContextWindow(total_budget=max_tokens)

    # High priority: goal and phase
    window.add_section("Sprint Goal", goal, priority=100)
    window.add_section("Current Phase", phase, priority=90)

    # Medium priority: recent tool results
    if tool_results:
        results_text = "\n".join(
            f"- {r['tool_name']}: {r.get('text', r.get('error', ''))[:200]}"
            for r in tool_results[-5:]
        )
        window.add_section("Recent Actions", results_text, priority=50)

    # Lower priority: tool catalog
    window.add_section("Available Tools", tool_catalog, priority=10)

    return window.assemble()


def format_tool_result_for_context(
    tool_name: str,
    result: str,
    max_chars: int = 500,
) -> str:
    """Format a tool result for inclusion in context."""
    if len(result) <= max_chars:
        return f"[{tool_name}] {result}"

    # Try to extract the most useful part
    # For JSON results, try to extract key fields
    try:
        data = json.loads(result)
        if isinstance(data, dict):
            summary_parts = []
            for key in ("status", "error", "summary", "message"):
                if key in data:
                    summary_parts.append(f"{key}={data[key]}")
            if summary_parts:
                return f"[{tool_name}] {', '.join(summary_parts)}"
    except (json.JSONDecodeError, TypeError):
        pass

    # Fall back to first N chars
    return f"[{tool_name}] {result[:max_chars]}..."
```

### 3.4 Tool Call History

**Design:** Persistent tool call history for learning and debugging.

```python
# ollamadev_mcp_server/tool_history.py
"""Tool call history for agent learning and debugging."""

import json
import time
from collections import deque
from pathlib import Path
from typing import Any

from ollamadev_mcp_server.constants import STORE_DIR
from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

HISTORY_FILE = STORE_DIR / "tool_call_history.json"
MAX_HISTORY_SIZE = 1000


class ToolCallRecord:
    """A single tool call record."""

    def __init__(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        success: bool,
        duration_ms: float,
        error: str | None = None,
        cycle_id: int | None = None,
        phase: str | None = None,
    ):
        self.tool_name = tool_name
        self.arguments = arguments
        self.success = success
        self.duration_ms = duration_ms
        self.error = error
        self.cycle_id = cycle_id
        self.phase = phase
        self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "success": self.success,
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error,
            "cycle_id": self.cycle_id,
            "phase": self.phase,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCallRecord":
        record = cls(
            tool_name=data["tool_name"],
            arguments=data.get("arguments", {}),
            success=data["success"],
            duration_ms=data.get("duration_ms", 0),
            error=data.get("error"),
            cycle_id=data.get("cycle_id"),
            phase=data.get("phase"),
        )
        record.timestamp = data.get("timestamp", time.time())
        return record


class ToolCallHistory:
    """Manages tool call history with persistence."""

    def __init__(self, max_size: int = MAX_HISTORY_SIZE):
        self._max_size = max_size
        self._records: deque[ToolCallRecord] = deque(maxlen=max_size)
        self._load()

    def record(self, call: ToolCallRecord) -> None:
        """Record a tool call."""
        self._records.append(call)
        self._save()

    def get_recent(self, n: int = 10) -> list[ToolCallRecord]:
        """Get the N most recent tool calls."""
        return list(self._records)[-n:]

    def get_for_phase(self, cycle_id: int, phase: str) -> list[ToolCallRecord]:
        """Get tool calls for a specific sprint phase."""
        return [
            r for r in self._records
            if r.cycle_id == cycle_id and r.phase == phase
        ]

    def get_failures(self, tool_name: str | None = None, limit: int = 10) -> list[ToolCallRecord]:
        """Get recent failed tool calls."""
        failures = [r for r in self._records if not r.success]
        if tool_name:
            failures = [r for r in failures if r.tool_name == tool_name]
        return failures[-limit:]

    def get_tool_stats(self, tool_name: str) -> dict[str, Any]:
        """Get statistics for a specific tool."""
        calls = [r for r in self._records if r.tool_name == tool_name]
        if not calls:
            return {"tool_name": tool_name, "total_calls": 0}

        successes = [r for r in calls if r.success]
        durations = [r.duration_ms for r in calls]

        return {
            "tool_name": tool_name,
            "total_calls": len(calls),
            "success_count": len(successes),
            "failure_count": len(calls) - len(successes),
            "success_rate": len(successes) / len(calls),
            "avg_duration_ms": sum(durations) / len(durations),
            "min_duration_ms": min(durations),
            "max_duration_ms": max(durations),
        }

    def clear(self) -> None:
        """Clear all history."""
        self._records.clear()
        self._save()

    def _load(self) -> None:
        """Load history from disk."""
        if not HISTORY_FILE.exists():
            return
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            for item in data:
                self._records.append(ToolCallRecord.from_dict(item))
        except (json.JSONDecodeError, OSError, KeyError) as exc:
            logger.warning("Failed to load tool history: %s", exc)

    def _save(self) -> None:
        """Save history to disk."""
        try:
            STORE_DIR.mkdir(parents=True, exist_ok=True)
            data = [r.to_dict() for r in self._records]
            HISTORY_FILE.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to save tool history: %s", exc)


# Global history instance
_history: ToolCallHistory | None = None


def get_history() -> ToolCallHistory:
    """Get the global tool call history."""
    global _history
    if _history is None:
        _history = ToolCallHistory()
    return _history
```

### 3.5 Autonomous Sprint Improvements

**Design:** Enhanced sprint loop with progress reporting, early termination, and phase-specific prompts.

Key improvements to `_run_autonomous_sprint`:

1. **Overall timeout** — Configurable via `DEFAULT_AUTONOMOUS_TIMEOUT`
2. **Progress callbacks** — Report phase transitions to logger
3. **Early termination** — Stop if 3 consecutive phases fail evaluation
4. **Phase-specific prompts** — Different system prompts per phase
5. **Cost tracking** — Count LLM calls and estimate tokens
6. **Tool history integration** — Use past failures to inform suggestions
7. **Smart phase skipping** — Skip phases that are not relevant to the goal

```python
# Phase-specific system prompts for suggest_next_action
PHASE_PROMPTS = {
    "discovery": (
        "You are in the DISCOVERY phase. Your goal is to explore the codebase, "
        "understand the current state, and identify relevant files and patterns. "
        "Prefer read-only tools: list_workspace_files, read_workspace_file, "
        "search_workspace, get_file_outline."
    ),
    "design": (
        "You are in the DESIGN phase. Your goal is to plan the implementation. "
        "Use code intelligence tools to understand interfaces and dependencies. "
        "Prefer: get_file_outline, find_symbol, search_workspace."
    ),
    "implementation": (
        "You are in the IMPLEMENTATION phase. Your goal is to write or modify code. "
        "Prefer: write_workspace_file, apply_file_patch, add_gradle_dependency."
    ),
    "verification": (
        "You are in the VERIFICATION phase. Your goal is to verify the implementation. "
        "Prefer: run_gradle_tests, run_pytest, run_lint, parse_test_results, "
        "search_workspace (to verify changes)."
    ),
    "integration": (
        "You are in the INTEGRATION phase. Your goal is to ensure everything works together. "
        "Prefer: git_status_diff, get_build_config, get_todos, find_symbol."
    ),
    "retrospective": (
        "You are in the RETROSPECTIVE phase. Your goal is to evaluate the sprint outcome "
        "and record lessons learned. "
        "Prefer: evaluate_sprint_outcome, store_memory, create_sprint_task."
    ),
}
```

---

## 4. Implementation Plan

### Step 1: Retry Module (Day 1)
1. Create `retry.py` with sync and async retry decorators
2. Apply to `_ask_ollama` and `_ask_anthropic` in `meta.py`
3. Write `tests/test_retry.py`

### Step 2: Circuit Breaker (Day 1-2)
1. Create `circuit_breaker.py`
2. Integrate into LLM call paths
3. Add circuit breaker status to health check
4. Write `tests/test_circuit_breaker.py`

### Step 3: Context Window Manager (Day 2)
1. Create `context_manager.py`
2. Replace naive truncation in `sprint.py`
3. Use in `suggest_next_action` prompt assembly
4. Write `tests/test_context_manager.py`

### Step 4: Tool Call History (Day 2-3)
1. Create `tool_history.py`
2. Record calls in autonomous sprint loop
3. Add history tool for inspection
4. Write `tests/test_tool_history.py`

### Step 5: Sprint Loop Improvements (Day 3-4)
1. Add overall timeout to `_run_autonomous_sprint`
2. Add phase-specific prompts
3. Add early termination logic
4. Add progress logging
5. Write `tests/test_sprint_improvements.py`

### Step 6: Integration and Verification (Day 4)
1. Run full test suite
2. Test autonomous sprint with mock LLM
3. Verify retry and circuit breaker behavior
4. Update README

---

## 5. Impact Assessment

### 5.1 Backward Compatibility

| Change | Breaking? | Migration |
|--------|-----------|-----------|
| Retry logic | No | Transparent to callers |
| Circuit breaker | Partial | Calls fail fast when breaker is open |
| Context manager | Internal | Better prompts, same API |
| Tool history | Additive | New file in `store/` |
| Sprint improvements | Partial | New optional parameters |

### 5.2 New Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MAX_RETRIES` | `3` | Max retry attempts for LLM calls |
| `LLM_RETRY_BASE_DELAY` | `2.0` | Base delay in seconds for retry |
| `CIRCUIT_BREAKER_FAILURE_THRESHOLD` | `5` | Failures before opening circuit |
| `CIRCUIT_BREAKER_RECOVERY_TIMEOUT` | `60` | Seconds before trying half-open |
| `CONTEXT_BUDGET_TOKENS` | `4096` | Max tokens for suggestion context |
| `SPRINT_EARLY_TERMINATION` | `true` | Stop after 3 consecutive failed phases |

### 5.3 New Dependencies

None. All modules use Python standard library only.

---

## 6. Verification Plan

### 6.1 Unit Tests

```bash
pytest tests/test_retry.py tests/test_circuit_breaker.py \
       tests/test_context_manager.py tests/test_tool_history.py \
       tests/test_sprint_improvements.py -v
```

### 6.2 Integration Tests

```bash
# Test retry behavior with failing endpoint
python -c "
from ollamadev_mcp_server.retry import with_retry, RetryConfig
import requests

@with_retry(RetryConfig(max_attempts=2, base_delay=0.1))
def failing_call():
    raise ConnectionError('simulated')

try:
    failing_call()
except ConnectionError:
    print('Retry worked: failed after 2 attempts')
"

# Test circuit breaker
python -c "
from ollamadev_mcp_server.circuit_breaker import CircuitBreaker, CircuitState

cb = CircuitBreaker('test', failure_threshold=3, recovery_timeout=1)
for i in range(3):
    try:
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError('fail')))
    except RuntimeError:
        pass

assert cb.state == CircuitState.OPEN
print('Circuit breaker opened after 3 failures')
"
```

### 6.3 Regression Tests

```bash
pytest -q
# Expected: All existing tests pass
```

---

## 7. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Retry delays slow down responsive calls | Use short base delays; only retry on transient errors |
| Circuit breaker stays open too long | Configurable recovery timeout; manual reset tool |
| Context truncation loses critical info | Priority-based assembly; smart truncation at boundaries |
| History file grows unbounded | Fixed max size with deque; periodic cleanup |
| Phase-specific prompts may be wrong | Keep prompts configurable; log prompt assembly |

---

## 8. Success Criteria

- [ ] LLM calls retry on transient failures
- [ ] Circuit breaker prevents cascading failures
- [ ] Context window respects token budgets
- [ ] Tool call history is persisted and queryable
- [ ] Autonomous sprint has overall timeout
- [ ] Autonomous sprint reports progress
- [ ] Autonomous sprint terminates early on repeated failures
- [ ] All existing tests pass
- [ ] New test coverage > 90% for new modules

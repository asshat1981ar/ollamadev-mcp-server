# Phase 5: Advanced Observability

> **Status:** DESIGN  
> **Priority:** P2  
> **Estimated Effort:** 4-5 days  
> **Dependencies:** Phase 1 (structured logging), Phase 4 (tool history)  

---

## 1. Executive Summary

Phase 5 builds on the structured logging foundation from Phase 1 to provide production-grade observability: Prometheus metrics, distributed tracing, performance profiling, usage analytics, and a real-time dashboard. These capabilities are essential for operating the MCP server reliably at scale and for understanding how agents use the tools.

### Deliverables

| Component | Module | Lines (est.) |
|-----------|--------|-------------|
| Metrics collector | `metrics.py` | ~200 |
| Prometheus exporter | `metrics_exporter.py` | ~120 |
| Distributed tracing | `tracing.py` | ~150 |
| Performance profiler | `profiler.py` | ~120 |
| Usage analytics | `analytics.py` | ~150 |
| Dashboard endpoints | `dashboard.py` | ~180 |
| Tests | `tests/test_phase5_*.py` | ~400 |
| **Total** | | **~1,320** |

---

## 2. Current State Analysis

### 2.1 No Metrics

After Phase 1, we have structured JSON logs, but no quantitative metrics. We cannot answer:
- What is the p95 latency for each tool?
- How many tool calls per minute are we serving?
- What is the error rate per tool?
- How much memory is the server using?
- How many active sessions are there?

### 2.2 No Distributed Tracing

After Phase 1, each tool call has a correlation ID, but we cannot:
- Visualize the full request flow across tools
- See parent-child relationships between tool calls
- Export traces to Jaeger/Zipkin for analysis
- Correlate traces across the MCP server and OllamaDev app

### 2.3 No Performance Profiling

We cannot identify:
- Which tools are slowest
- Which tools consume the most memory
- Whether there are memory leaks
- Where CPU time is spent

### 2.4 No Usage Analytics

We cannot answer:
- Which tools are most popular?
- Which tools fail most often?
- What is the typical agent workflow pattern?
- Are there tools that are never used?

### 2.5 No Dashboard

There is no way to visualize server health, tool usage, or agent activity in real-time without parsing log files manually.

---

## 3. Proposed Architecture

### 3.1 Metrics Collector

**Design:** Lightweight metrics collection using counters, gauges, and histograms.

```python
# ollamadev_mcp_server/metrics.py
"""Metrics collection for the OllamaDev MCP server."""

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class Counter:
    """Monotonically increasing counter."""
    name: str
    description: str
    labels: dict[str, str] = field(default_factory=dict)
    value: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self.value += amount

    def get(self) -> float:
        with self._lock:
            return self.value


@dataclass
class Gauge:
    """Value that can go up and down."""
    name: str
    description: str
    labels: dict[str, str] = field(default_factory=dict)
    value: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set(self, value: float) -> None:
        with self._lock:
            self.value = value

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self.value += amount

    def dec(self, amount: float = 1.0) -> None:
        with self._lock:
            self.value -= amount

    def get(self) -> float:
        with self._lock:
            return self.value


@dataclass
class Histogram:
    """Distribution of values across configurable buckets."""
    name: str
    description: str
    buckets: tuple[float, ...] = (
        0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0,
        2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0,
    )
    labels: dict[str, str] = field(default_factory=dict)
    _counts: dict[float, int] = field(default_factory=dict)
    _sum: float = 0.0
    _count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def observe(self, value: float) -> None:
        with self._lock:
            self._sum += value
            self._count += 1
            for bucket in self.buckets:
                if bucket not in self._counts:
                    self._counts[bucket] = 0
                if value <= bucket:
                    self._counts[bucket] += 1
            # +Inf bucket
            inf_key = float("inf")
            if inf_key not in self._counts:
                self._counts[inf_key] = 0
            self._counts[inf_key] += 1

    def get(self) -> dict[str, Any]:
        with self._lock:
            return {
                "sum": self._sum,
                "count": self._count,
                "buckets": {
                    str(k): v for k, v in sorted(self._counts.items())
                },
            }


class MetricsRegistry:
    """Central registry for all metrics."""

    def __init__(self):
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}
        self._lock = threading.Lock()

    def counter(self, name: str, description: str = "", **labels: str) -> Counter:
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._counters:
                self._counters[key] = Counter(name, description, labels)
            return self._counters[key]

    def gauge(self, name: str, description: str = "", **labels: str) -> Gauge:
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._gauges:
                self._gauges[key] = Gauge(name, description, labels)
            return self._gauges[key]

    def histogram(self, name: str, description: str = "", buckets: tuple[float, ...] | None = None, **labels: str) -> Histogram:
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._histograms:
                kwargs = {"name": name, "description": description, "labels": labels}
                if buckets is not None:
                    kwargs["buckets"] = buckets
                self._histograms[key] = Histogram(**kwargs)
            return self._histograms[key]

    def get_all(self) -> dict[str, Any]:
        """Get all metrics as a dictionary."""
        return {
            "counters": {k: {"value": v.get(), "description": v.description, "labels": v.labels} for k, v in self._counters.items()},
            "gauges": {k: {"value": v.get(), "description": v.description, "labels": v.labels} for k, v in self._gauges.items()},
            "histograms": {k: {**v.get(), "description": v.description, "labels": v.labels} for k, v in self._histograms.items()},
        }

    def _make_key(self, name: str, labels: dict[str, str]) -> str:
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"


# Global registry
_registry = MetricsRegistry()


def get_registry() -> MetricsRegistry:
    return _registry


# --- Pre-defined metrics ---

def tool_calls_total(tool_name: str, status: str) -> Counter:
    return _registry.counter("mcp_tool_calls_total", "Total tool calls", tool=tool_name, status=status)


def tool_duration_seconds(tool_name: str) -> Histogram:
    return _registry.histogram("mcp_tool_duration_seconds", "Tool call duration", tool=tool_name)


def active_sessions() -> Gauge:
    return _registry.gauge("mcp_active_sessions", "Number of active MCP sessions")


def llm_requests_total(provider: str, status: str) -> Counter:
    return _registry.counter("mcp_llm_requests_total", "Total LLM API requests", provider=provider, status=status)


def llm_request_duration_seconds(provider: str) -> Histogram:
    return _registry.histogram("mcp_llm_request_duration_seconds", "LLM API request duration", provider=provider)


def server_uptime_seconds() -> Gauge:
    return _registry.gauge("mcp_server_uptime_seconds", "Server uptime in seconds")


def memory_usage_bytes() -> Gauge:
    return _registry.gauge("mcp_memory_usage_bytes", "Server memory usage in bytes")
```

### 3.2 Prometheus Exporter

**Design:** Export metrics in Prometheus text format via an HTTP endpoint.

```python
# ollamadev_mcp_server/metrics_exporter.py
"""Prometheus-compatible metrics exporter."""

import json
from typing import Any

from ollamadev_mcp_server.logging_config import get_logger
from ollamadev_mcp_server.metrics import get_registry

logger = get_logger(__name__)


def format_prometheus_text() -> str:
    """Format all metrics in Prometheus text exposition format."""
    registry = get_registry()
    all_metrics = registry.get_all()
    lines: list[str] = []

    # Counters
    for key, data in all_metrics["counters"].items():
        name = data.get("name", key)
        lines.append(f"# HELP {name} {data['description']}")
        lines.append(f"# TYPE {name} counter")
        labels = _format_labels(data.get("labels", {}))
        lines.append(f"{name}{labels} {data['value']}")

    # Gauges
    for key, data in all_metrics["gauges"].items():
        name = data.get("name", key)
        lines.append(f"# HELP {name} {data['description']}")
        lines.append(f"# TYPE {name} gauge")
        labels = _format_labels(data.get("labels", {}))
        lines.append(f"{name}{labels} {data['value']}")

    # Histograms
    for key, data in all_metrics["histograms"].items():
        name = data.get("name", key)
        lines.append(f"# HELP {name} {data['description']}")
        lines.append(f"# TYPE {name} histogram")
        labels_dict = data.get("labels", {})
        base_labels = _format_labels(labels_dict, trailing_comma=True)
        for bucket, count in data.get("buckets", {}).items():
            le = "+Inf" if bucket == "inf" else bucket
            lines.append(f"{name}_bucket{{le=\"{le}\"{base_labels}}} {count}")
        lines.append(f"{name}_sum{labels_dict and _format_labels(labels_dict) or ''} {data['sum']}")
        lines.append(f"{name}_count{labels_dict and _format_labels(labels_dict) or ''} {data['count']}")

    return "\n".join(lines) + "\n"


def format_json() -> dict[str, Any]:
    """Format all metrics as JSON."""
    return get_registry().get_all()


def _format_labels(labels: dict[str, str], trailing_comma: bool = False) -> str:
    if not labels:
        return ""
    parts = [f'{k}="{v}"' for k, v in sorted(labels.items())]
    inner = ",".join(parts)
    if trailing_comma and inner:
        inner += ","
    return f"{{{inner}}}"
```

### 3.3 Distributed Tracing

**Design:** OpenTelemetry-compatible trace context propagation.

```python
# ollamadev_mcp_server/tracing.py
"""Distributed tracing for the OllamaDev MCP server."""

import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

# Context variables for trace propagation
_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")
_span_id: ContextVar[str] = ContextVar("span_id", default="-")
_parent_span_id: ContextVar[str] = ContextVar("parent_span_id", default="-")


@dataclass
class Span:
    """A single span in a distributed trace."""
    trace_id: str
    span_id: str
    parent_span_id: str
    operation_name: str
    start_time: float
    end_time: float = 0.0
    status: str = "OK"
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })

    def finish(self, status: str = "OK") -> None:
        self.end_time = time.time()
        self.status = status

    def duration_ms(self) -> float:
        if self.end_time == 0:
            return (time.time() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "operation_name": self.operation_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms(), 2),
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
        }


def new_trace_id() -> str:
    return uuid.uuid4().hex


def new_span_id() -> str:
    return uuid.uuid4().hex[:16]


def start_span(operation_name: str, attributes: dict[str, Any] | None = None) -> Span:
    """Start a new span."""
    trace_id = _trace_id.get("-")
    if trace_id == "-":
        trace_id = new_trace_id()
        _trace_id.set(trace_id)

    parent_span_id = _span_id.get("-")
    span_id = new_span_id()

    span = Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        operation_name=operation_name,
        start_time=time.time(),
        attributes=attributes or {},
    )

    _span_id.set(span_id)
    _parent_span_id.set(parent_span_id)

    logger.debug(
        "Span started: %s (trace=%s, span=%s)",
        operation_name, trace_id, span_id,
    )
    return span


def finish_span(span: Span, status: str = "OK") -> None:
    """Finish a span and log it."""
    span.finish(status)
    _span_id.set(span.parent_span_id)

    logger.info(
        "Span finished: %s (%.1fms, %s)",
        span.operation_name, span.duration_ms(), status,
        extra={"extra_data": span.to_dict()},
    )


def get_trace_context() -> dict[str, str]:
    """Get current trace context for propagation."""
    return {
        "trace_id": _trace_id.get("-"),
        "span_id": _span_id.get("-"),
        "parent_span_id": _parent_span_id.get("-"),
    }


def set_trace_context(trace_id: str, span_id: str = "-", parent_span_id: str = "-") -> None:
    """Set trace context from incoming request."""
    _trace_id.set(trace_id)
    _span_id.set(span_id)
    _parent_span_id.set(parent_span_id)


class SpanCollector:
    """Collects finished spans for export."""

    def __init__(self, max_size: int = 10000):
        self._spans: list[Span] = []
        self._max_size = max_size

    def collect(self, span: Span) -> None:
        self._spans.append(span)
        if len(self._spans) > self._max_size:
            self._spans = self._spans[-self._max_size:]

    def get_recent(self, n: int = 100) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._spans[-n:]]

    def get_by_trace(self, trace_id: str) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._spans if s.trace_id == trace_id]

    def clear(self) -> None:
        self._spans.clear()


_span_collector = SpanCollector()


def get_span_collector() -> SpanCollector:
    return _span_collector
```

### 3.4 Performance Profiler

**Design:** Lightweight profiling for tool execution.

```python
# ollamadev_mcp_server/profiler.py
"""Performance profiling for the OllamaDev MCP server."""

import os
import time
import tracemalloc
from collections import defaultdict
from typing import Any

from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)


class ToolProfiler:
    """Profile tool execution time and memory usage."""

    def __init__(self):
        self._tool_times: dict[str, list[float]] = defaultdict(list)
        self._tool_memory: dict[str, list[int]] = defaultdict(list)
        self._max_samples = int(os.environ.get("PROFILER_MAX_SAMPLES", "1000"))
        self._memory_tracking = os.environ.get("PROFILER_MEMORY", "false").lower() == "true"

    def record_execution(self, tool_name: str, duration_ms: float, memory_bytes: int = 0) -> None:
        """Record a tool execution."""
        self._tool_times[tool_name].append(duration_ms)
        if len(self._tool_times[tool_name]) > self._max_samples:
            self._tool_times[tool_name] = self._tool_times[tool_name][-self._max_samples:]

        if memory_bytes > 0:
            self._tool_memory[tool_name].append(memory_bytes)
            if len(self._tool_memory[tool_name]) > self._max_samples:
                self._tool_memory[tool_name] = self._tool_memory[tool_name][-self._max_samples:]

    def get_stats(self, tool_name: str | None = None) -> dict[str, Any]:
        """Get profiling statistics."""
        if tool_name:
            return self._stats_for_tool(tool_name)

        return {
            name: self._stats_for_tool(name)
            for name in sorted(self._tool_times.keys())
        }

    def _stats_for_tool(self, tool_name: str) -> dict[str, Any]:
        times = self._tool_times.get(tool_name, [])
        if not times:
            return {"tool_name": tool_name, "call_count": 0}

        sorted_times = sorted(times)
        n = len(sorted_times)

        stats: dict[str, Any] = {
            "tool_name": tool_name,
            "call_count": n,
            "min_ms": round(sorted_times[0], 2),
            "max_ms": round(sorted_times[-1], 2),
            "mean_ms": round(sum(sorted_times) / n, 2),
            "median_ms": round(sorted_times[n // 2], 2),
            "p95_ms": round(sorted_times[int(n * 0.95)], 2) if n >= 20 else None,
            "p99_ms": round(sorted_times[int(n * 0.99)], 2) if n >= 100 else None,
        }

        memory = self._tool_memory.get(tool_name, [])
        if memory:
            stats["memory"] = {
                "min_bytes": min(memory),
                "max_bytes": max(memory),
                "mean_bytes": sum(memory) // len(memory),
            }

        return stats

    def get_slow_tools(self, threshold_ms: float = 1000, limit: int = 10) -> list[dict[str, Any]]:
        """Get tools with average execution time above threshold."""
        slow = []
        for name in self._tool_times:
            stats = self._stats_for_tool(name)
            if stats.get("mean_ms", 0) > threshold_ms:
                slow.append(stats)
        slow.sort(key=lambda x: x.get("mean_ms", 0), reverse=True)
        return slow[:limit]

    def clear(self) -> None:
        self._tool_times.clear()
        self._tool_memory.clear()


class MemoryProfiler:
    """Track memory usage using tracemalloc."""

    def __init__(self):
        self._snapshots: list[dict[str, Any]] = []
        self._tracking = False

    def start(self) -> None:
        if not self._tracking:
            tracemalloc.start()
            self._tracking = True
            logger.info("Memory profiling started")

    def stop(self) -> None:
        if self._tracking:
            tracemalloc.stop()
            self._tracking = False
            logger.info("Memory profiling stopped")

    def take_snapshot(self, label: str = "") -> dict[str, Any]:
        """Take a memory snapshot."""
        if not self._tracking:
            return {"error": "Memory profiling not started"}

        snapshot = tracemalloc.take_snapshot()
        current, peak = tracemalloc.get_traced_memory()

        # Get top memory allocations
        stats = snapshot.statistics("lineno")[:10]
        top_allocations = [
            {
                "file": str(stat.traceback),
                "size_bytes": stat.size,
                "count": stat.count,
            }
            for stat in stats
        ]

        result = {
            "label": label,
            "timestamp": time.time(),
            "current_bytes": current,
            "peak_bytes": peak,
            "top_allocations": top_allocations,
        }
        self._snapshots.append(result)
        return result

    def get_diff(self, snapshot_idx: int = -1) -> dict[str, Any]:
        """Get memory diff between snapshots."""
        if len(self._snapshots) < 2:
            return {"error": "Need at least 2 snapshots for diff"}
        # Return latest snapshot info
        return self._snapshots[snapshot_idx]


# Global instances
_tool_profiler = ToolProfiler()
_memory_profiler = MemoryProfiler()


def get_tool_profiler() -> ToolProfiler:
    return _tool_profiler


def get_memory_profiler() -> MemoryProfiler:
    return _memory_profiler
```

### 3.5 Usage Analytics

**Design:** Aggregate tool usage patterns for insights.

```python
# ollamadev_mcp_server/analytics.py
"""Usage analytics for the OllamaDev MCP server."""

import json
import time
from collections import Counter as PyCounter
from pathlib import Path
from typing import Any

from ollamadev_mcp_server.constants import STORE_DIR
from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)

ANALYTICS_FILE = STORE_DIR / "usage_analytics.json"


class UsageAnalytics:
    """Track and analyze tool usage patterns."""

    def __init__(self):
        self._tool_counts: PyCounter = PyCounter()
        self._tool_errors: PyCounter = PyCounter()
        self._phase_usage: PyCounter = PyCounter()
        self._hourly_usage: PyCounter = PyCounter()
        self._agent_workflows: list[list[str]] = []
        self._current_workflow: list[str] = []
        self._load()

    def record_tool_call(self, tool_name: str, success: bool, phase: str | None = None) -> None:
        """Record a tool call."""
        self._tool_counts[tool_name] += 1
        if not success:
            self._tool_errors[tool_name] += 1
        if phase:
            self._phase_usage[f"{phase}:{tool_name}"] += 1

        hour = time.strftime("%Y-%m-%dT%H")
        self._hourly_usage[hour] += 1

        self._current_workflow.append(tool_name)
        self._save()

    def end_workflow(self) -> None:
        """Mark the end of an agent workflow."""
        if self._current_workflow:
            self._agent_workflows.append(self._current_workflow[:])
            if len(self._agent_workflows) > 1000:
                self._agent_workflows = self._agent_workflows[-1000:]
            self._current_workflow.clear()
            self._save()

    def get_tool_popularity(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get most popular tools."""
        return [
            {
                "tool_name": name,
                "calls": count,
                "errors": self._tool_errors.get(name, 0),
                "error_rate": self._tool_errors.get(name, 0) / count if count > 0 else 0,
            }
            for name, count in self._tool_counts.most_common(limit)
        ]

    def get_phase_usage(self) -> dict[str, dict[str, int]]:
        """Get tool usage per phase."""
        result: dict[str, dict[str, int]] = {}
        for key, count in self._phase_usage.items():
            phase, tool = key.split(":", 1)
            if phase not in result:
                result[phase] = {}
            result[phase][tool] = count
        return result

    def get_hourly_usage(self, hours: int = 24) -> list[dict[str, Any]]:
        """Get hourly usage for the last N hours."""
        now = time.time()
        result = []
        for i in range(hours):
            hour_ts = now - (i * 3600)
            hour_key = time.strftime("%Y-%m-%dT%H", time.localtime(hour_ts))
            result.append({
                "hour": hour_key,
                "calls": self._hourly_usage.get(hour_key, 0),
            })
        return list(reversed(result))

    def get_workflow_patterns(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get common workflow patterns."""
        pattern_counter: PyCounter = PyCounter()
        for workflow in self._agent_workflows:
            # Create a pattern signature from the tool sequence
            pattern = " -> ".join(workflow[:5])  # First 5 tools
            pattern_counter[pattern] += 1
        return [
            {"pattern": pattern, "count": count}
            for pattern, count in pattern_counter.most_common(limit)
        ]

    def get_summary(self) -> dict[str, Any]:
        """Get a complete analytics summary."""
        return {
            "total_calls": sum(self._tool_counts.values()),
            "total_errors": sum(self._tool_errors.values()),
            "unique_tools": len(self._tool_counts),
            "workflows_recorded": len(self._agent_workflows),
            "top_tools": self.get_tool_popularity(10),
            "hourly_usage": self.get_hourly_usage(24),
            "workflow_patterns": self.get_workflow_patterns(5),
        }

    def _load(self) -> None:
        if not ANALYTICS_FILE.exists():
            return
        try:
            data = json.loads(ANALYTICS_FILE.read_text(encoding="utf-8"))
            self._tool_counts = PyCounter(data.get("tool_counts", {}))
            self._tool_errors = PyCounter(data.get("tool_errors", {}))
            self._phase_usage = PyCounter(data.get("phase_usage", {}))
            self._hourly_usage = PyCounter(data.get("hourly_usage", {}))
            self._agent_workflows = data.get("workflows", [])
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load analytics: %s", exc)

    def _save(self) -> None:
        try:
            STORE_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "tool_counts": dict(self._tool_counts),
                "tool_errors": dict(self._tool_errors),
                "phase_usage": dict(self._phase_usage),
                "hourly_usage": dict(self._hourly_usage),
                "workflows": self._agent_workflows[-100:],
            }
            ANALYTICS_FILE.write_text(
                json.dumps(data, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to save analytics: %s", exc)


_analytics: UsageAnalytics | None = None


def get_analytics() -> UsageAnalytics:
    global _analytics
    if _analytics is None:
        _analytics = UsageAnalytics()
    return _analytics
```

### 3.6 Dashboard Endpoints

**Design:** MCP tools that expose dashboard data as JSON.

```python
# ollamadev_mcp_server/dashboard.py
"""Dashboard tools for real-time server monitoring."""

import json
from typing import Any

from ollamadev_mcp_server.logging_config import get_logger
from ollamadev_mcp_server.metrics import get_registry
from ollamadev_mcp_server.metrics_exporter import format_json, format_prometheus_text
from ollamadev_mcp_server.analytics import get_analytics
from ollamadev_mcp_server.profiler import get_tool_profiler, get_memory_profiler
from ollamadev_mcp_server.tracing import get_span_collector

logger = get_logger(__name__)


def get_dashboard_overview() -> str:
    """Get a complete dashboard overview as JSON."""
    analytics = get_analytics()
    profiler = get_tool_profiler()

    return json.dumps({
        "overview": {
            "total_tool_calls": sum(analytics._tool_counts.values()),
            "total_errors": sum(analytics._tool_errors.values()),
            "unique_tools_used": len(analytics._tool_counts),
        },
        "top_tools": analytics.get_tool_popularity(10),
        "slow_tools": profiler.get_slow_tools(threshold_ms=500, limit=10),
        "hourly_usage": analytics.get_hourly_usage(24),
        "recent_errors": [
            {"tool": t["tool_name"], "errors": t["errors"]}
            for t in analytics.get_tool_popularity(50)
            if t["errors"] > 0
        ][:10],
    }, indent=2)


def get_metrics_dashboard() -> str:
    """Get metrics dashboard as JSON."""
    return json.dumps(format_json(), indent=2)


def get_profiling_dashboard() -> str:
    """Get profiling dashboard as JSON."""
    profiler = get_tool_profiler()
    return json.dumps({
        "tool_stats": profiler.get_stats(),
        "slow_tools": profiler.get_slow_tools(),
    }, indent=2)


def get_tracing_dashboard(trace_id: str | None = None, limit: int = 50) -> str:
    """Get tracing dashboard as JSON."""
    collector = get_span_collector()
    if trace_id:
        spans = collector.get_by_trace(trace_id)
    else:
        spans = collector.get_recent(limit)
    return json.dumps({"spans": spans}, indent=2)


def get_analytics_dashboard() -> str:
    """Get analytics dashboard as JSON."""
    analytics = get_analytics()
    return json.dumps(analytics.get_summary(), indent=2)


def export_prometheus_metrics() -> str:
    """Export metrics in Prometheus text format."""
    return format_prometheus_text()
```

---

## 4. Implementation Plan

### Step 1: Metrics Collector (Day 1)
1. Create `metrics.py` with Counter, Gauge, Histogram
2. Create `MetricsRegistry` with thread-safe operations
3. Define pre-built metrics for tools and LLM calls
4. Write `tests/test_metrics.py`

### Step 2: Prometheus Exporter (Day 1-2)
1. Create `metrics_exporter.py`
2. Implement Prometheus text format
3. Add `/metrics` HTTP endpoint
4. Write `tests/test_metrics_exporter.py`

### Step 3: Distributed Tracing (Day 2)
1. Create `tracing.py` with Span and context propagation
2. Integrate into tool call middleware
3. Add trace context to structured logs
4. Write `tests/test_tracing.py`

### Step 4: Performance Profiler (Day 2-3)
1. Create `profiler.py` with ToolProfiler and MemoryProfiler
2. Instrument tool execution with timing
3. Add memory tracking (optional, env-controlled)
4. Write `tests/test_profiler.py`

### Step 5: Usage Analytics (Day 3)
1. Create `analytics.py`
2. Track tool calls, errors, phase usage
3. Record workflow patterns
4. Write `tests/test_analytics.py`

### Step 6: Dashboard Tools (Day 3-4)
1. Create `dashboard.py`
2. Register dashboard tools in `server.py`
3. Add `/metrics` and `/dashboard` HTTP endpoints
4. Write `tests/test_dashboard.py`

### Step 7: Integration and Verification (Day 4-5)
1. Run full test suite
2. Start server and verify metrics endpoint
3. Verify Prometheus scraping works
4. Test dashboard tools
5. Update README with observability documentation

---

## 5. Impact Assessment

### 5.1 Backward Compatibility

| Change | Breaking? | Migration |
|--------|-----------|-----------|
| Metrics collection | No | Additive, no API changes |
| Prometheus endpoint | No | New `/metrics` HTTP endpoint |
| Tracing | No | Additive, enriches logs |
| Profiling | No | Opt-in via environment variable |
| Analytics | No | Additive, new file in `store/` |
| Dashboard tools | No | New MCP tools |

### 5.2 New Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `METRICS_ENABLED` | `true` | Enable metrics collection |
| `METRICS_ENDPOINT` | `/metrics` | Prometheus metrics endpoint path |
| `TRACING_ENABLED` | `true` | Enable distributed tracing |
| `PROFILER_ENABLED` | `false` | Enable performance profiling |
| `PROFILER_MEMORY` | `false` | Enable memory profiling (higher overhead) |
| `PROFILER_MAX_SAMPLES` | `1000` | Max samples per tool |
| `ANALYTICS_ENABLED` | `true` | Enable usage analytics |
| `DASHBOARD_ENABLED` | `true` | Enable dashboard tools |

### 5.3 New Dependencies

| Dependency | Version | Purpose | Required? |
|-----------|---------|--------|-----------|
| None | — | All modules use stdlib only | No |

**Note:** For production Prometheus scraping, the `/metrics` endpoint returns standard Prometheus text format. No additional Python packages are needed. If OpenTelemetry export is desired in the future, `opentelemetry-api` and `opentelemetry-sdk` can be added as optional dependencies.

---

## 6. Verification Plan

### 6.1 Unit Tests

```bash
pytest tests/test_metrics.py tests/test_metrics_exporter.py \
       tests/test_tracing.py tests/test_profiler.py \
       tests/test_analytics.py tests/test_dashboard.py -v
```

### 6.2 Integration Tests

```bash
# Start server with metrics enabled
METRICS_ENABLED=true TRACING_ENABLED=true uv run serve &
SERVER_PID=$!

# Call some tools
for i in {1..10}; do
  curl -s -X POST http://localhost:5000/mcp \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ping","arguments":{}}}'
done

# Check Prometheus metrics endpoint
curl -s http://localhost:5000/metrics
# Expected: Prometheus text format with mcp_tool_calls_total, etc.

# Check dashboard tool
curl -s -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_dashboard_overview","arguments":{}}}'
# Expected: JSON with overview, top_tools, slow_tools, etc.

kill $SERVER_PID
```

### 6.3 Prometheus Scraping Test

```bash
# Configure Prometheus to scrape (prometheus.yml)
# scrape_configs:
#   - job_name: 'ollamadev-mcp'
#     static_configs:
#       - targets: ['localhost:5000']
#     metrics_path: '/metrics'

# Verify metrics are valid Prometheus format
promtool check-metrics < <(curl -s http://localhost:5000/metrics)
```

### 6.4 Regression Tests

```bash
pytest -q
# Expected: All existing tests pass
```

---

## 7. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Metrics overhead slows tools | Use lock-free data structures where possible; batch updates |
| Trace data grows unbounded | Fixed max size in SpanCollector; periodic cleanup |
| Memory profiling adds overhead | Opt-in via environment variable; disabled by default |
| Analytics file grows large | Cap at 1000 workflows; hourly usage limited to 30 days |
| Dashboard tools expose sensitive data | Only expose aggregated metrics, not raw tool arguments |

---

## 8. Success Criteria

- [ ] Prometheus metrics endpoint returns valid format
- [ ] All tool calls are counted and timed
- [ ] Distributed traces are captured with parent-child relationships
- [ ] Performance profiler identifies slow tools
- [ ] Usage analytics tracks tool popularity and error rates
- [ ] Dashboard tools return real-time server data
- [ ] Memory profiling is available (opt-in)
- [ ] All existing tests pass
- [ ] New test coverage > 90% for new modules
- [ ] Grafana dashboard JSON is provided (optional)

---

## 9. Future Enhancements (Out of Scope)

- **Grafana dashboard JSON** — Pre-built dashboard for visualization
- **Alerting rules** — Prometheus alerting for error rates and latency
- **OpenTelemetry export** — Export traces to Jaeger/Zipkin
- **Log aggregation** — Forward structured logs to ELK/Loki
- **Cost tracking** — Track LLM API costs per agent/sprint
- **Anomaly detection** — Detect unusual tool usage patterns

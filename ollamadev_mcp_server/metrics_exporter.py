"""Simple Prometheus-format metrics exporter for OllamaDev MCP server.

This module provides an MCP tool `get_metrics_prometheus` that returns
Prometheus plaintext metrics aggregated from the local tool_call_history.json
store (ToolHistory). It's intentionally dependency-free and suitable as an
MVP until an in-process Prometheus client or OTLP exporter is added.
"""
from typing import Dict
from collections import defaultdict
from ollamadev_mcp_server.tool_history import get_history


BUCKETS_MS = [5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000]


def _format_label(labels: Dict[str, str]) -> str:
    if not labels:
        return ""
    return ",".join(f'{k}="{v}"' for k, v in labels.items())


def collect_metrics_text() -> str:
    """Collect metrics from ToolHistory and render as Prometheus text.

    Returns:
        Prometheus plaintext exposition of a small set of metrics:
        - mcp_tool_calls_total{tool}
        - mcp_tool_errors_total{tool}
        - mcp_tool_duration_ms_sum{tool}
        - mcp_tool_duration_ms_count{tool}
        - mcp_tool_duration_ms_bucket{tool,le}
    """
    history = get_history()
    records = history.get_recent(1000)

    calls = defaultdict(int)
    errors = defaultdict(int)
    duration_sum = defaultdict(float)
    duration_count = defaultdict(int)
    buckets = {tool: [0 for _ in BUCKETS_MS] for tool in set(r.tool_name for r in records)}

    for r in records:
        t = r.tool_name
        calls[t] += 1
        if not r.success:
            errors[t] += 1
        duration_sum[t] += float(r.duration_ms or 0)
        duration_count[t] += 1
        # bucket duration
        for i, bound in enumerate(BUCKETS_MS):
            if r.duration_ms <= bound:
                buckets[t][i] += 1

    lines = []
    # Counters
    for tool in sorted(calls.keys()):
        lines.append(f'# HELP mcp_tool_calls_total Total tool calls for {tool}')
        lines.append(f'# TYPE mcp_tool_calls_total counter')
        lines.append(f'mcp_tool_calls_total{{tool="{tool}"}} {calls[tool]}')

        lines.append(f'# HELP mcp_tool_errors_total Total failing tool calls for {tool}')
        lines.append(f'# TYPE mcp_tool_errors_total counter')
        lines.append(f'mcp_tool_errors_total{{tool="{tool}"}} {errors[tool]}')

        # durations
        lines.append(f'# HELP mcp_tool_duration_ms Histogram of tool durations (ms) for {tool}')
        lines.append(f'# TYPE mcp_tool_duration_ms histogram')

        cumulative = 0
        for bound, cnt in zip(BUCKETS_MS, buckets.get(tool, [])):
            cumulative += cnt
            lines.append(f'mcp_tool_duration_ms_bucket{{tool="{tool}",le="{bound}"}} {cumulative}')
        # +Inf
        lines.append(f'mcp_tool_duration_ms_bucket{{tool="{tool}",le="+Inf"}} {calls[tool]}')
        lines.append(f'mcp_tool_duration_ms_sum{{tool="{tool}"}} {duration_sum[tool]:.2f}')
        lines.append(f'mcp_tool_duration_ms_count{{tool="{tool}"}} {duration_count[tool]}')

    # Uptime metric (best-effort using history timestamps)
    lines.append('# HELP mcp_tool_history_entries Number of stored tool history records')
    lines.append('# TYPE mcp_tool_history_entries gauge')
    lines.append(f'mcp_tool_history_entries {len(records)}')

    return "\n".join(lines) + "\n"


# MCP tool shim (imported by registry)
from mcp.server import MCPServer


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations={"destructiveHint": False, "readOnlyHint": True})
    def get_metrics_prometheus() -> str:
        """Return Prometheus plaintext metrics aggregated from local tool history."""
        return collect_metrics_text()

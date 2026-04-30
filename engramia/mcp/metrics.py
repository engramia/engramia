# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Prometheus metrics for hosted MCP.

Imported lazily by ``http_server.py`` and incremented from the request
handler / tool dispatch path. ``prometheus_client`` is an existing dep
(used by ``api/prom_metrics.py``) so no new packages.

The collectors registered here become visible at the existing ``/metrics``
endpoint when ``ENGRAMIA_METRICS=true``.
"""

from __future__ import annotations

try:
    from prometheus_client import Counter, Gauge, Histogram

    _ENABLED = True
except ImportError:  # pragma: no cover  — optional dep

    class _Stub:
        def __init__(self, *_a, **_kw): ...
        def labels(self, *_a, **_kw):
            return self

        def inc(self, *_a, **_kw): ...
        def dec(self, *_a, **_kw): ...
        def set(self, *_a, **_kw): ...
        def observe(self, *_a, **_kw): ...

    Counter = Gauge = Histogram = _Stub  # type: ignore[assignment, misc]
    _ENABLED = False


MCP_ACTIVE_SESSIONS = Gauge(
    "engramia_mcp_active_sessions",
    "Active hosted MCP sessions, labeled by tenant tier.",
    ["plan_tier"],
)

MCP_TOOL_CALLS_TOTAL = Counter(
    "engramia_mcp_tool_calls_total",
    "Hosted MCP tool calls, labeled by tool, tier, and outcome.",
    ["tool", "plan_tier", "status"],  # status: ok | tier_blocked | rbac_denied | quota | error
)

MCP_TOOL_CALL_DURATION = Histogram(
    "engramia_mcp_tool_call_duration_seconds",
    "Hosted MCP tool call wall-clock duration.",
    ["tool"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

MCP_CONNECTION_LIMIT_REJECTIONS_TOTAL = Counter(
    "engramia_mcp_connection_limit_rejections_total",
    "Hosted MCP session opens rejected by per-tenant connection limit.",
    ["plan_tier"],
)

MCP_TIER_REJECTIONS_TOTAL = Counter(
    "engramia_mcp_tier_rejections_total",
    "Hosted MCP session opens rejected by tier gate (tier below team).",
    ["plan_tier"],
)

MCP_SESSION_EVICTIONS_TOTAL = Counter(
    "engramia_mcp_session_evictions_total",
    "Hosted MCP sessions evicted by reason.",
    ["reason"],  # idle | client_close | error
)


def is_enabled() -> bool:
    return _ENABLED

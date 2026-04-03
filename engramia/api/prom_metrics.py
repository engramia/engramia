# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Prometheus custom metrics for Engramia.

Registers Gauges and Counters for Engramia-specific signals and exposes
them via a ASGI app mounted at /metrics.

Usage (in app.py)::

    from engramia.api.prom_metrics import build_metrics_app
    app.mount("/metrics", build_metrics_app(app.state.memory))
"""

import logging

_log = logging.getLogger(__name__)


def build_metrics_app(memory):
    """Return an ASGI app that serves Prometheus metrics.

    Registers a custom CollectorRegistry with Engramia Gauges that are
    updated on every scrape via a callback-based MultiGauge.

    Args:
        memory: The shared Memory instance used to read live metrics.

    Returns:
        An ASGI application suitable for mounting at /metrics.
    """
    try:
        from prometheus_client import (
            CONTENT_TYPE_LATEST,
            CollectorRegistry,
            Gauge,
            generate_latest,
            make_asgi_app,
        )
    except ImportError:
        _log.warning("prometheus_client not installed — /metrics not available")
        raise

    registry = CollectorRegistry(auto_describe=True)

    pattern_count = Gauge(
        "engramia_pattern_count",
        "Total number of stored patterns",
        registry=registry,
    )
    avg_eval_score = Gauge(
        "engramia_avg_eval_score",
        "Rolling average evaluation score (0–10)",
        registry=registry,
    )
    total_runs = Gauge(
        "engramia_total_runs",
        "Total number of learn() calls recorded",
        registry=registry,
    )
    success_rate = Gauge(
        "engramia_success_rate",
        "Fraction of runs recorded as successful (0–1)",
        registry=registry,
    )
    reuse_rate = Gauge(
        "engramia_reuse_rate",
        "Fraction of recall() calls that returned at least one match",
        registry=registry,
    )

    def _collect():
        try:
            m = memory.metrics
            pattern_count.set(m.pattern_count)
            avg_eval_score.set(m.avg_eval_score if m.avg_eval_score is not None else 0.0)
            total_runs.set(m.runs)
            success_rate.set(m.success_rate)
            reuse_rate.set(m.reuse_rate)
        except Exception as exc:
            _log.warning("Failed to collect Prometheus metrics: %s", exc)

    # ASGI app that updates gauges before responding
    _base_app = make_asgi_app(registry=registry)

    async def metrics_asgi(scope, receive, send):
        _collect()
        await _base_app(scope, receive, send)

    return metrics_asgi

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Prometheus metrics for the Engramia API.

All prometheus_client imports are lazy — when the ``telemetry`` extra is not
installed every function becomes a no-op so the rest of the codebase can
import this module unconditionally.

Configuration:
    ENGRAMIA_METRICS    true | false  (default: false)
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

_enabled: bool = False

# ---------------------------------------------------------------------------
# Metric objects — populated by init_metrics()
# ---------------------------------------------------------------------------

REQUEST_DURATION = None   # Histogram: method, path, status_code
REQUEST_COUNT = None       # Counter:   method, path, status_code

LLM_CALL_DURATION = None   # Histogram: provider, model
EMBEDDING_DURATION = None  # Histogram: provider
STORAGE_OP_DURATION = None # Histogram: backend, operation

PATTERN_COUNT = None       # Gauge:     (unlabelled — global aggregate)
RECALL_HITS = None         # Counter
RECALL_MISSES = None       # Counter

JOB_SUBMITTED = None       # Counter:   operation
JOB_COMPLETED = None       # Counter:   operation, status


def is_enabled() -> bool:
    """Return True if Prometheus metrics have been initialised."""
    return _enabled


def init_metrics() -> None:
    """Create and register all Prometheus metric objects.

    No-op (with a warning) if ``prometheus_client`` is not installed.
    Idempotent — safe to call multiple times.
    """
    global _enabled
    global REQUEST_DURATION, REQUEST_COUNT
    global LLM_CALL_DURATION, EMBEDDING_DURATION, STORAGE_OP_DURATION
    global PATTERN_COUNT, RECALL_HITS, RECALL_MISSES
    global JOB_SUBMITTED, JOB_COMPLETED

    if _enabled:
        return

    try:
        from prometheus_client import Counter, Gauge, Histogram
    except ImportError:
        _log.warning(
            "prometheus_client not installed — metrics disabled. "
            "Install with: pip install engramia[telemetry]"
        )
        return

    REQUEST_DURATION = Histogram(
        "engramia_request_duration_seconds",
        "HTTP request duration",
        ["method", "path", "status_code"],
    )
    REQUEST_COUNT = Counter(
        "engramia_requests_total",
        "Total HTTP requests",
        ["method", "path", "status_code"],
    )

    LLM_CALL_DURATION = Histogram(
        "engramia_llm_call_duration_seconds",
        "LLM provider call duration",
        ["provider", "model"],
    )
    EMBEDDING_DURATION = Histogram(
        "engramia_embedding_duration_seconds",
        "Embedding provider call duration",
        ["provider"],
    )
    STORAGE_OP_DURATION = Histogram(
        "engramia_storage_op_duration_seconds",
        "Storage backend operation duration",
        ["backend", "operation"],
    )

    PATTERN_COUNT = Gauge(
        "engramia_pattern_count_total",
        "Total number of patterns stored",
    )
    RECALL_HITS = Counter(
        "engramia_recall_hits_total",
        "Recall operations that returned >=1 result",
    )
    RECALL_MISSES = Counter(
        "engramia_recall_misses_total",
        "Recall operations that returned 0 results",
    )

    JOB_SUBMITTED = Counter(
        "engramia_jobs_submitted_total",
        "Async jobs submitted",
        ["operation"],
    )
    JOB_COMPLETED = Counter(
        "engramia_jobs_completed_total",
        "Async jobs completed",
        ["operation", "status"],
    )

    _enabled = True
    _log.info("Prometheus metrics enabled.")


# ---------------------------------------------------------------------------
# Safe observation helpers — all are no-ops when metrics are disabled
# ---------------------------------------------------------------------------


def observe_request(method: str, path: str, status_code: int, duration_s: float) -> None:
    if not _enabled:
        return
    labels = [method, path, str(status_code)]
    REQUEST_DURATION.labels(*labels).observe(duration_s)
    REQUEST_COUNT.labels(*labels).inc()


def observe_llm(provider: str, model: str, duration_s: float) -> None:
    if not _enabled:
        return
    LLM_CALL_DURATION.labels(provider, model).observe(duration_s)


def observe_embedding(provider: str, duration_s: float) -> None:
    if not _enabled:
        return
    EMBEDDING_DURATION.labels(provider).observe(duration_s)


def observe_storage(backend: str, operation: str, duration_s: float) -> None:
    if not _enabled:
        return
    STORAGE_OP_DURATION.labels(backend, operation).observe(duration_s)


def set_pattern_count(count: int) -> None:
    if not _enabled:
        return
    PATTERN_COUNT.set(count)


def inc_recall_hit() -> None:
    if _enabled:
        RECALL_HITS.inc()


def inc_recall_miss() -> None:
    if _enabled:
        RECALL_MISSES.inc()


def inc_job_submitted(operation: str) -> None:
    if _enabled:
        JOB_SUBMITTED.labels(operation).inc()


def inc_job_completed(operation: str, status: str) -> None:
    if _enabled:
        JOB_COMPLETED.labels(operation, status).inc()

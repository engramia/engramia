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
from typing import Any

_log = logging.getLogger(__name__)

_enabled: bool = False

# ---------------------------------------------------------------------------
# Metric objects — populated by init_metrics()
# ---------------------------------------------------------------------------

REQUEST_DURATION: Any = None  # Histogram: method, path, status_code
REQUEST_COUNT: Any = None  # Counter:   method, path, status_code

LLM_CALL_DURATION: Any = None  # Histogram: provider, model, role
EMBEDDING_DURATION: Any = None  # Histogram: provider
STORAGE_OP_DURATION: Any = None  # Histogram: backend, operation
LLM_FAILOVER: Any = None  # Counter: fallback_position
ROLE_CEILING_FALLBACK: Any = None  # Counter: role

PATTERN_COUNT: Any = None  # Gauge:     (unlabelled — global aggregate)
RECALL_HITS: Any = None  # Counter
RECALL_MISSES: Any = None  # Counter

JOB_SUBMITTED: Any = None  # Counter:   operation
JOB_COMPLETED: Any = None  # Counter:   operation, status


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
    global LLM_FAILOVER, ROLE_CEILING_FALLBACK
    global PATTERN_COUNT, RECALL_HITS, RECALL_MISSES
    global JOB_SUBMITTED, JOB_COMPLETED

    if _enabled:
        return

    try:
        from prometheus_client import Counter, Gauge, Histogram
    except ImportError:
        _log.warning(
            "prometheus_client not installed — metrics disabled. Install with: pip install engramia[telemetry]"
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

    # NB: tenant_id is intentionally NOT a label here. With per-role
    # routing (Phase 6.6 #2) the dimensions are already
    # provider × model × role; adding tenant would push series count
    # into Prometheus warning zone. Use ROI analytics rollups
    # (engramia/analytics/) for per-tenant breakdowns.
    LLM_CALL_DURATION = Histogram(
        "engramia_llm_call_duration_seconds",
        "LLM provider call duration",
        ["provider", "model", "role"],
    )
    LLM_FAILOVER = Counter(
        "engramia_llm_failover_total",
        "Provider failover events — primary call failed transient and chain advanced",
        ["fallback_position"],
    )
    ROLE_CEILING_FALLBACK = Counter(
        "engramia_role_ceiling_fallback_total",
        "Per-role cost ceiling reached — call routed to default_model instead",
        ["role"],
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


def observe_llm(provider: str, model: str, duration_s: float, role: str = "default") -> None:
    if not _enabled:
        return
    LLM_CALL_DURATION.labels(provider, model, role).observe(duration_s)


def observe_failover(tenant_id: str, fallback_position: int) -> None:
    """Record a failover event — primary call failed transient, chain advanced.

    The ``tenant_id`` parameter is accepted for the call-site signature but
    deliberately not used as a label (cardinality control). Tenant-scoped
    failover analysis goes through analytics rollups instead.
    """
    if not _enabled:
        return
    LLM_FAILOVER.labels(str(fallback_position)).inc()


def observe_role_ceiling_fallback(tenant_id: str, role: str) -> None:
    """Record a cost-ceiling fallback — role spend reached cap, used default.

    Same cardinality discipline as ``observe_failover``: ``tenant_id`` is
    not labelled. The ``role`` label is bounded by KNOWN_ROLES + a small
    long tail of Enterprise custom roles, well within Prometheus comfort.
    """
    if not _enabled:
        return
    ROLE_CEILING_FALLBACK.labels(role).inc()


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

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""ROI rollup aggregator.

Reads raw ROIEvent records from ROICollector and computes per-scope,
per-window ROIRollup summaries. Results are persisted under the
``analytics/rollup/{window}/{tenant}/{project}`` key namespace so that
API reads are O(1) lookups rather than full-scan aggregations.
"""

import logging
import statistics
import time
from datetime import UTC, datetime
from typing import Literal

from engramia.analytics.collector import ROICollector
from engramia.analytics.models import (
    EventKind,
    LearnSummary,
    RecallOutcome,
    ROIEvent,
    ROIRollup,
)
from engramia.providers.base import StorageBackend

_log = logging.getLogger(__name__)

_Window = Literal["hourly", "daily", "weekly"]

_ROLLUP_PREFIX = "analytics/rollup"

# Window durations in seconds
_WINDOW_SECONDS: dict[str, int] = {
    "hourly": 3600,
    "daily": 86400,
    "weekly": 604800,
}

# ROI composite score weights
_WEIGHT_REUSE = 0.6
_WEIGHT_EVAL = 0.4


def _iso_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _window_start_iso(window: str) -> str:
    """Return the ISO-8601 UTC start of the most recent complete window."""
    duration = _WINDOW_SECONDS[window]
    now = time.time()
    start = now - (now % duration)
    return datetime.fromtimestamp(start, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rollup_key(window: str, tenant_id: str, project_id: str) -> str:
    return f"{_ROLLUP_PREFIX}/{window}/{tenant_id}/{project_id}"


class ROIAggregator:
    """Computes and persists ROI rollup summaries from raw events.

    Args:
        storage: The active StorageBackend instance shared with Memory.
        collector: The ROICollector instance providing raw events.
    """

    def __init__(self, storage: StorageBackend, collector: ROICollector) -> None:
        self._storage = storage
        self._collector = collector

    def rollup(self, window: _Window = "daily") -> list[ROIRollup]:
        """Aggregate raw events for the given window into ROIRollup records.

        Computes one ROIRollup per (tenant_id, project_id) pair discovered in
        the raw event stream. Persists each rollup under
        ``analytics/rollup/{window}/{tenant}/{project}`` and returns the full
        list. Safe to call multiple times — results are idempotent for the same
        window.

        Args:
            window: One of "hourly", "daily", or "weekly".

        Returns:
            List of ROIRollup objects, one per discovered (tenant, project) scope.

        Raises:
            ValueError: If window is not one of the supported values.
        """
        if window not in _WINDOW_SECONDS:
            raise ValueError(f"Unsupported window {window!r}. Use: {list(_WINDOW_SECONDS)}")

        since_ts = time.time() - _WINDOW_SECONDS[window]
        events = self._collector.load_events(since_ts=since_ts)

        # Group by (tenant_id, project_id)
        grouped: dict[tuple[str, str], list[ROIEvent]] = {}
        for e in events:
            key = (e.scope_tenant, e.scope_project)
            grouped.setdefault(key, []).append(e)

        window_start = _window_start_iso(window)
        computed_at = _iso_now()
        results: list[ROIRollup] = []

        for (tenant_id, project_id), scope_events in grouped.items():
            rollup = _compute_rollup(
                tenant_id=tenant_id,
                project_id=project_id,
                window=window,
                window_start=window_start,
                computed_at=computed_at,
                events=scope_events,
            )
            storage_key = _rollup_key(window, tenant_id, project_id)
            self._storage.save(storage_key, rollup.model_dump())
            _log.info(
                "ROI rollup persisted: window=%s scope=%s/%s roi=%.2f",
                window,
                tenant_id,
                project_id,
                rollup.roi_score,
            )
            results.append(rollup)

        return results

    def get_rollup(
        self,
        window: str,
        tenant_id: str,
        project_id: str,
    ) -> ROIRollup | None:
        """Load a previously computed rollup from storage.

        Args:
            window: Aggregation window ("hourly"|"daily"|"weekly").
            tenant_id: Tenant identifier.
            project_id: Project identifier.

        Returns:
            ROIRollup if found, else None.
        """
        key = _rollup_key(window, tenant_id, project_id)
        data = self._storage.load(key)
        if data is None:
            return None
        try:
            return ROIRollup.model_validate(data)
        except Exception:
            _log.warning("Failed to deserialize rollup at key %r", key)
            return None


# ---------------------------------------------------------------------------
# Pure computation helper (module-level for testability)
# ---------------------------------------------------------------------------


def _compute_rollup(
    tenant_id: str,
    project_id: str,
    window: _Window,
    window_start: str,
    computed_at: str,
    events: list[ROIEvent],
) -> ROIRollup:
    """Compute a ROIRollup from a list of events for one scope."""
    learn_events = [e for e in events if e.kind == EventKind.LEARN]
    recall_events = [e for e in events if e.kind == EventKind.RECALL]

    # --- recall summary ---
    duplicate = sum(1 for e in recall_events if e.reuse_tier == "duplicate")
    adapt = sum(1 for e in recall_events if e.reuse_tier == "adapt")
    fresh = sum(1 for e in recall_events if e.reuse_tier == "fresh")
    total_recall = len(recall_events)

    sims = [e.similarity for e in recall_events if e.similarity is not None]
    avg_sim = round(sum(sims) / len(sims), 4) if sims else 0.0
    reuse_rate = round((duplicate + adapt) / total_recall, 4) if total_recall > 0 else 0.0

    recall_summary = RecallOutcome(
        total=total_recall,
        duplicate_hits=duplicate,
        adapt_hits=adapt,
        fresh_misses=fresh,
        reuse_rate=reuse_rate,
        avg_similarity=avg_sim,
    )

    # --- learn summary ---
    scores = [e.eval_score for e in learn_events if e.eval_score is not None]
    if scores:
        avg_eval = round(sum(scores) / len(scores), 4)
        sorted_s = sorted(scores)
        p50 = round(statistics.median(sorted_s), 4)
        idx_90 = max(0, int((len(sorted_s) - 1) * 0.9))
        p90 = round(sorted_s[idx_90], 4)
    else:
        avg_eval = p50 = p90 = 0.0

    learn_summary = LearnSummary(
        total=len(learn_events),
        avg_eval_score=avg_eval,
        p50_eval_score=p50,
        p90_eval_score=p90,
    )

    # --- composite ROI score (0-10) ---
    roi = round(
        _WEIGHT_REUSE * reuse_rate * 10.0 + _WEIGHT_EVAL * avg_eval,
        4,
    )
    roi = min(10.0, max(0.0, roi))

    return ROIRollup(
        tenant_id=tenant_id,
        project_id=project_id,
        window=window,
        window_start=window_start,
        recall=recall_summary,
        learn=learn_summary,
        roi_score=roi,
        computed_at=computed_at,
    )

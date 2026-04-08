# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""ROI event collector.

Appends lightweight ROIEvent records to the ``analytics/events`` storage key.
Uses a rolling window of MAX_EVENTS=10_000 to bound storage growth.

Thread-safety relies on the StorageBackend implementation:
- JSONStorage: protected by its internal threading.Lock.
- PostgresStorage: uses transactions.
"""

import logging
import threading
import time
from typing import Literal

from engramia._context import get_scope
from engramia.analytics.models import EventKind, ROIEvent
from engramia.exceptions import ValidationError
from engramia.providers.base import StorageBackend

_log = logging.getLogger(__name__)

_EVENTS_KEY = "analytics/events"
_MAX_EVENTS = 10_000


class ROICollector:
    """Records learn and recall events for downstream ROI aggregation.

    Args:
        storage: The active StorageBackend instance shared with Memory.
    """

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage
        self._append_lock = threading.Lock()

    def record_learn(self, pattern_key: str, eval_score: float) -> None:
        """Append a learn event.

        Called by Memory.learn() just before returning LearnResult.
        Never raises — all exceptions are caught and logged so a collector
        failure cannot affect the learn path.

        Args:
            pattern_key: Storage key of the newly stored pattern.
            eval_score: The eval score passed to Memory.learn().
        """
        try:
            scope = get_scope()
            event = ROIEvent(
                kind=EventKind.LEARN,
                ts=time.time(),
                eval_score=eval_score,
                pattern_key=pattern_key,
                scope_tenant=scope.tenant_id,
                scope_project=scope.project_id,
            )
            self._append(event)
        except Exception:
            _log.warning("ROICollector.record_learn failed silently", exc_info=True)

    def record_recall(
        self,
        best_similarity: float | None,
        best_reuse_tier: Literal["duplicate", "adapt", "fresh"] | None,
        best_pattern_key: str,
    ) -> None:
        """Append a recall event.

        Called by Memory.recall() after the final result list is assembled.
        Uses the first element of the returned list as "best match".
        Never raises.

        Args:
            best_similarity: Cosine similarity of the top match, or None if no
                matches were returned.
            best_reuse_tier: Reuse tier of the top match, or None if no matches.
            best_pattern_key: Storage key of the top match, or "" if no matches.
        """
        try:
            scope = get_scope()
            event = ROIEvent(
                kind=EventKind.RECALL,
                ts=time.time(),
                similarity=best_similarity,
                reuse_tier=best_reuse_tier,
                pattern_key=best_pattern_key,
                scope_tenant=scope.tenant_id,
                scope_project=scope.project_id,
            )
            self._append(event)
        except Exception:
            _log.warning("ROICollector.record_recall failed silently", exc_info=True)

    def load_events(
        self,
        since_ts: float | None = None,
        tenant_id: str | None = None,
        project_id: str | None = None,
        admin_override: bool = False,
    ) -> list[ROIEvent]:
        """Load raw events with optional scope and time filtering.

        Args:
            since_ts: If set, only return events with ts >= since_ts.
            tenant_id: Filter to this tenant.  Pass ``"*"`` to skip tenant
                filtering (requires ``admin_override=True``).
            project_id: Filter to this project (None = all projects).
            admin_override: Must be explicitly set to ``True`` to perform an
                unscoped (all-tenant) read.  Prevents accidental cross-tenant
                data leakage when tenant_id is omitted.

        Returns:
            List of ROIEvent objects in chronological order.

        Raises:
            ValidationError: If tenant_id is None and admin_override is False.
                Pass admin_override=True to explicitly request an unscoped scan.
        """
        if tenant_id is None and not admin_override:
            raise ValidationError(
                "load_events() requires tenant_id to be specified. "
                "Omitting tenant_id would return events across all tenants, "
                "which is a cross-tenant data leak risk. "
                "Pass admin_override=True to explicitly request an unscoped scan."
            )
        raw = self._load_raw()
        events: list[ROIEvent] = []
        for item in raw:
            try:
                e = ROIEvent.model_validate(item)
            except Exception:
                continue
            if since_ts is not None and e.ts < since_ts:
                continue
            if tenant_id is not None and tenant_id != "*" and e.scope_tenant != tenant_id:
                continue
            if project_id is not None and project_id != "*" and e.scope_project != project_id:
                continue
            events.append(e)
        return events

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append(self, event: ROIEvent) -> None:
        with self._append_lock:
            raw = self._load_raw()
            raw.append(event.model_dump())
            raw = raw[-_MAX_EVENTS:]
            self._storage.save(_EVENTS_KEY, raw)

    def _load_raw(self) -> list:
        data = self._storage.load(_EVENTS_KEY)
        return data if isinstance(data, list) else []

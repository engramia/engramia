# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Usage metering — atomic monthly counters stored in PostgreSQL.

Uses INSERT ... ON CONFLICT DO UPDATE for lock-free atomic increments
(same pattern as the job queue's SKIP LOCKED approach: minimal locking,
predictable contention behaviour).
"""

import datetime
import logging

from sqlalchemy import text

from engramia.billing.models import METRIC_EVAL_RUNS

_log = logging.getLogger(__name__)


class UsageMeter:
    """Atomic monthly usage counters backed by the ``usage_counters`` table.

    All methods are no-ops when ``engine`` is None (dev / JSON-storage mode).

    Args:
        engine: SQLAlchemy engine pointing at the Engramia PostgreSQL DB.
    """

    def __init__(self, engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def increment(self, tenant_id: str, metric: str) -> int:
        """Atomically increment a counter and return the new value.

        Returns 0 when no engine is configured (no-op mode).
        """
        if self._engine is None:
            return 0
        year, month = self._current_period()
        try:
            with self._engine.begin() as conn:
                row = conn.execute(
                    text(
                        "INSERT INTO usage_counters (id, tenant_id, metric, year, month, count) "
                        "VALUES (gen_random_uuid()::text, :tid, :metric, :year, :month, 1) "
                        "ON CONFLICT (tenant_id, metric, year, month) "
                        "DO UPDATE SET count = usage_counters.count + 1 "
                        "RETURNING count"
                    ),
                    {"tid": tenant_id, "metric": metric, "year": year, "month": month},
                ).fetchone()
            return row[0] if row else 1
        except Exception:
            _log.warning("UsageMeter.increment failed for tenant=%s metric=%s", tenant_id, metric, exc_info=True)
            return 0

    def get_count(self, tenant_id: str, metric: str, year: int | None = None, month: int | None = None) -> int:
        """Return the current counter value for the given period (default: current month)."""
        if self._engine is None:
            return 0
        if year is None or month is None:
            year, month = self._current_period()
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT count FROM usage_counters "
                        "WHERE tenant_id = :tid AND metric = :metric "
                        "AND year = :year AND month = :month"
                    ),
                    {"tid": tenant_id, "metric": metric, "year": year, "month": month},
                ).fetchone()
            return row[0] if row else 0
        except Exception:
            _log.warning("UsageMeter.get_count failed for tenant=%s metric=%s", tenant_id, metric, exc_info=True)
            return 0

    def get_overage_units(self, tenant_id: str, metric: str, limit: int) -> int:
        """Return the number of completed overage units above ``limit`` for the current period.

        Returns 0 when the count is within the limit or no engine is configured.
        """
        count = self.get_count(tenant_id, metric)
        excess = max(0, count - limit)
        return excess

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _current_period() -> tuple[int, int]:
        now = datetime.datetime.now(datetime.UTC)
        return now.year, now.month

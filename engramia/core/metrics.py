# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Run and success metrics store.

Tracks aggregate statistics across all Engramia runs. Persisted as a single
JSON document per scope under the "metrics/<tenant>/<project>/_global" key.
The key is scope-derived rather than a global constant so that two tenants
on the same Postgres instance do not collide on the global ``key`` primary
key (legacy from migration 001).
"""

import logging
import time

from engramia._context import get_scope
from engramia.providers.base import StorageBackend
from engramia.types import Metrics

_log = logging.getLogger(__name__)

_KEY_PREFIX = "metrics"
_MAX_HISTORY = 100


def _scoped_key() -> str:
    scope = get_scope()
    return f"{_KEY_PREFIX}/{scope.tenant_id}/{scope.project_id}/_global"


class MetricsStore:
    """Persistent counter for Engramia run statistics.

    Args:
        storage: Storage backend to persist metrics.
    """

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record_run(
        self,
        success: bool,
        pipeline_reuse: bool = False,
        eval_score: float | None = None,
    ) -> None:
        """Record a single Engramia run.

        Args:
            success: Whether the run succeeded.
            pipeline_reuse: Whether an existing pattern was reused.
            eval_score: Optional eval score for this run.
        """
        data = self._load_raw()
        data["runs"] += 1
        if success:
            data["success"] += 1
        else:
            data["failures"] += 1
        if pipeline_reuse:
            data["pipeline_reuse"] += 1

        entry: dict = {"timestamp": time.time(), "success": success}
        if eval_score is not None:
            entry["eval_score"] = eval_score
        data["run_history"].append(entry)
        data["run_history"] = data["run_history"][-_MAX_HISTORY:]

        self._storage.save(_scoped_key(), data)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self) -> Metrics:
        """Return current aggregate metrics."""
        data = self._load_raw()
        runs = data["runs"]
        success_rate = round(data["success"] / runs, 3) if runs > 0 else 0.0
        return Metrics(
            runs=runs,
            success=data["success"],
            failures=data["failures"],
            pipeline_reuse=data["pipeline_reuse"],
            success_rate=success_rate,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_raw(self) -> dict:
        data = self._storage.load(_scoped_key())
        if data is None:
            return {
                "runs": 0,
                "success": 0,
                "failures": 0,
                "pipeline_reuse": 0,
                "run_history": [],
            }
        return data

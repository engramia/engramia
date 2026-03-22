"""Run and success metrics store.

Tracks aggregate statistics across all Brain runs. Persisted as a single
JSON document under the "metrics/_global" storage key.
"""

import time

from agent_brain.providers.base import StorageBackend
from agent_brain.types import Metrics

_KEY = "metrics/_global"
_MAX_HISTORY = 100


class MetricsStore:
    """Persistent counter for Brain run statistics.

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
        """Record a single Brain run.

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

        self._storage.save(_KEY, data)

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
        data = self._storage.load(_KEY)
        if data is None:
            return {
                "runs": 0,
                "success": 0,
                "failures": 0,
                "pipeline_reuse": 0,
                "run_history": [],
            }
        return data

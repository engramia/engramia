"""Evaluation results store.

Persists individual LLM evaluation results and provides quality-weighted
lookups. Used by Brain.recall() to boost high-quality patterns and by
Brain.metrics to report average eval scores.

Rolling window of MAX_EVALS=200 entries to avoid unbounded growth.
"""

import logging

from agent_brain._util import jaccard
from agent_brain.providers.base import StorageBackend

_log = logging.getLogger(__name__)

_KEY = "evals/_list"
_MAX_EVALS = 200


class EvalStore:
    """Stores and queries evaluation results.

    Args:
        storage: Storage backend to persist eval records.
    """

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save(self, agent_name: str, task: str, scores: dict) -> None:
        """Append an evaluation result.

        Args:
            agent_name: Identifier of the evaluated agent/pattern.
            task: Task description the agent was evaluated on.
            scores: Dict with at minimum an "overall" float key.
        """
        import time

        evals = self._load_raw()
        evals.append({"agent_name": agent_name, "task": task, "scores": scores, "timestamp": time.time()})
        evals = evals[-_MAX_EVALS:]
        self._storage.save(_KEY, evals)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_top_examples(
        self,
        limit: int = 3,
        min_score: float = 7.0,
    ) -> list[dict]:
        """Return the best scoring eval records.

        Args:
            limit: Maximum number of records to return.
            min_score: Minimum overall score threshold.

        Returns:
            List of eval records sorted by overall score descending.
        """
        evals = self._load_raw()
        qualified = [e for e in evals if e["scores"].get("overall", 0) >= min_score]
        qualified.sort(key=lambda e: e["scores"].get("overall", 0), reverse=True)
        return qualified[:limit]

    def get_agent_score(self, agent_name: str, task: str, min_jaccard: float = 0.15) -> float | None:
        """Look up the eval score for a specific agent on a similar task.

        Args:
            agent_name: Agent/pattern identifier.
            task: Task to match against stored eval tasks.
            min_jaccard: Minimum word-overlap to consider tasks related.

        Returns:
            Overall score if found, else None.
        """
        evals = self._load_raw()
        for e in reversed(evals):
            if e["agent_name"] == agent_name and jaccard(e["task"], task) >= min_jaccard:
                return e["scores"].get("overall")
        return None

    def get_average_score(self) -> float | None:
        """Average overall score across the most recent 10 evaluations.

        Returns:
            Average score, or None if no evals are stored.
        """
        evals = self._load_raw()
        if not evals:
            return None
        recent = evals[-10:]
        scores = [e["scores"].get("overall") for e in recent if e["scores"].get("overall") is not None]
        if not scores:
            return None
        return round(sum(scores) / len(scores), 2)

    def get_eval_multiplier(self, agent_name: str, task: str) -> float:
        """Return an eval-based quality multiplier for search result weighting.

        Maps eval score to a [0.5, 1.0] multiplier:
        - Score 10.0 → 1.0 (full weight)
        - Score 0.0  → 0.5 (half weight)
        - No eval    → 0.75 (neutral)

        Args:
            agent_name: Agent/pattern identifier.
            task: Task to match.

        Returns:
            Float multiplier in [0.5, 1.0].
        """
        score = self.get_agent_score(agent_name, task)
        if score is None:
            return 0.75
        return 0.5 + 0.5 * (score / 10.0)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_raw(self) -> list:
        data = self._storage.load(_KEY)
        return data if isinstance(data, list) else []

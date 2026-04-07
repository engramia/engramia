# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Evaluation results store.

Persists individual LLM evaluation results and provides quality-weighted
lookups. Used by Memory.recall() to boost high-quality patterns and by
Memory.metrics to report average eval scores.

Rolling window of MAX_EVALS=200 entries to avoid unbounded growth.

Scope isolation: every public method builds its storage key from explicit
tenant_id and project_id parameters so that eval history is always
segregated by scope — independent of the storage backend's context-var
scoping. This provides defense-in-depth: even if the storage backend's
scope context variable is unset or incorrect, EvalStore cannot mix data
across tenants or projects.
"""

import logging

from engramia._util import jaccard
from engramia.providers.base import StorageBackend

_log = logging.getLogger(__name__)

_MAX_EVALS = 200


class EvalStore:
    """Stores and queries evaluation results.

    Args:
        storage: Storage backend to persist eval records.
        tenant_id: Default tenant identifier for scope isolation.
            Must be a non-empty string. Defaults to ``"default"`` for
            backward compatibility with single-tenant deployments.
        project_id: Default project identifier for scope isolation.
            Must be a non-empty string. Defaults to ``"default"``.
    """

    def __init__(
        self,
        storage: StorageBackend,
        tenant_id: str = "default",
        project_id: str = "default",
    ) -> None:
        if not tenant_id:
            raise ValueError("EvalStore requires a non-empty tenant_id")
        if not project_id:
            raise ValueError("EvalStore requires a non-empty project_id")
        self._storage = storage
        self._tenant_id = tenant_id
        self._project_id = project_id

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save(
        self,
        agent_name: str,
        task: str,
        scores: dict,
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> None:
        """Append an evaluation result.

        Args:
            agent_name: Identifier of the evaluated agent/pattern.
            task: Task description the agent was evaluated on.
            scores: Dict with at minimum an "overall" float key.
            tenant_id: Scope override; defaults to the instance tenant_id.
            project_id: Scope override; defaults to the instance project_id.
        """
        import time

        key = self._scoped_key(tenant_id or self._tenant_id, project_id or self._project_id)
        evals = self._load_raw(key)
        evals.append({"agent_name": agent_name, "task": task, "scores": scores, "timestamp": time.time()})
        evals = evals[-_MAX_EVALS:]
        self._storage.save(key, evals)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_top_examples(
        self,
        limit: int = 3,
        min_score: float = 7.0,
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> list[dict]:
        """Return the best scoring eval records.

        Args:
            limit: Maximum number of records to return.
            min_score: Minimum overall score threshold.
            tenant_id: Scope override; defaults to the instance tenant_id.
            project_id: Scope override; defaults to the instance project_id.

        Returns:
            List of eval records sorted by overall score descending.
        """
        key = self._scoped_key(tenant_id or self._tenant_id, project_id or self._project_id)
        evals = self._load_raw(key)
        qualified = [e for e in evals if e["scores"].get("overall", 0) >= min_score]
        qualified.sort(key=lambda e: e["scores"].get("overall", 0), reverse=True)
        return qualified[:limit]

    def get_agent_score(
        self,
        agent_name: str,
        task: str,
        min_jaccard: float = 0.15,
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> float | None:
        """Look up the eval score for a specific agent on a similar task.

        Args:
            agent_name: Agent/pattern identifier.
            task: Task to match against stored eval tasks.
            min_jaccard: Minimum word-overlap to consider tasks related.
            tenant_id: Scope override; defaults to the instance tenant_id.
            project_id: Scope override; defaults to the instance project_id.

        Returns:
            Overall score if found, else None.
        """
        key = self._scoped_key(tenant_id or self._tenant_id, project_id or self._project_id)
        evals = self._load_raw(key)
        for e in reversed(evals):
            if e["agent_name"] == agent_name and jaccard(e["task"], task) >= min_jaccard:
                return e["scores"].get("overall")
        return None

    def get_average_score(
        self,
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> float | None:
        """Average overall score across the most recent 10 evaluations.

        Args:
            tenant_id: Scope override; defaults to the instance tenant_id.
            project_id: Scope override; defaults to the instance project_id.

        Returns:
            Average score, or None if no evals are stored.
        """
        key = self._scoped_key(tenant_id or self._tenant_id, project_id or self._project_id)
        evals = self._load_raw(key)
        if not evals:
            return None
        recent = evals[-10:]
        scores = [e["scores"].get("overall") for e in recent if e["scores"].get("overall") is not None]
        if not scores:
            return None
        return round(sum(scores) / len(scores), 2)

    def get_eval_multiplier(
        self,
        agent_name: str,
        task: str,
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> float:
        """Return an eval-based quality multiplier for search result weighting.

        Maps eval score to a [0.5, 1.0] multiplier:
        - Score 10.0 → 1.0 (full weight)
        - Score 0.0  → 0.5 (half weight)
        - No eval    → 0.75 (neutral)

        Args:
            agent_name: Agent/pattern identifier.
            task: Task to match.
            tenant_id: Scope override; defaults to the instance tenant_id.
            project_id: Scope override; defaults to the instance project_id.

        Returns:
            Float multiplier in [0.5, 1.0].
        """
        score = self.get_agent_score(agent_name, task, tenant_id=tenant_id, project_id=project_id)
        if score is None:
            return 0.75
        return 0.5 + 0.5 * (score / 10.0)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _scoped_key(self, tenant_id: str, project_id: str) -> str:
        """Build and validate the scoped storage key for eval records.

        Encoding scope in the key adds a defense-in-depth layer: even if the
        storage backend's context-var scope is wrong, reads and writes will
        land in the correct tenant/project namespace.

        Args:
            tenant_id: Tenant identifier — must be non-empty.
            project_id: Project identifier — must be non-empty.

        Returns:
            A storage key of the form ``evals/{tenant_id}/{project_id}/_list``.

        Raises:
            ValueError: If either identifier is empty.
        """
        if not tenant_id:
            raise ValueError("EvalStore: tenant_id must be a non-empty string")
        if not project_id:
            raise ValueError("EvalStore: project_id must be a non-empty string")
        return f"evals/{tenant_id}/{project_id}/_list"

    def _load_raw(self, key: str = "") -> list:
        if not key:
            key = self._scoped_key(self._tenant_id, self._project_id)
        data = self._storage.load(key)
        return data if isinstance(data, list) else []

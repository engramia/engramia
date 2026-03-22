"""Eval-weighted pattern matcher.

Extends raw semantic similarity with an eval quality multiplier so that
high-quality patterns rank above lower-quality ones with similar embeddings.

Effective score = cosine_similarity × eval_multiplier
where eval_multiplier ∈ [0.5, 1.0] based on stored eval score.
"""

import logging

from agent_brain._util import PATTERNS_PREFIX, reuse_tier
from agent_brain.core.eval_store import EvalStore
from agent_brain.providers.base import EmbeddingProvider, StorageBackend
from agent_brain.types import Match, Pattern

_log = logging.getLogger(__name__)


class PatternMatcher:
    """Finds relevant patterns using semantic search + eval quality weighting.

    Args:
        storage: Storage backend holding patterns and embeddings.
        embeddings: Embedding provider for query vectorisation.
        eval_store: Eval store for quality multiplier lookup.
    """

    def __init__(
        self,
        storage: StorageBackend,
        embeddings: EmbeddingProvider,
        eval_store: EvalStore,
    ) -> None:
        self._storage = storage
        self._embeddings = embeddings
        self._eval_store = eval_store

    def find(self, task: str, limit: int = 5) -> list[Match]:
        """Return the best-matching patterns for *task*, eval-weighted.

        Args:
            task: Task description to match against stored patterns.
            limit: Maximum number of results.

        Returns:
            List of Match objects sorted by effective (weighted) score descending.
        """
        embedding = self._embeddings.embed(task)
        raw_results = self._storage.search_similar(
            embedding,
            limit=limit * 3,
            prefix=PATTERNS_PREFIX,
        )

        weighted: list[tuple[float, Match]] = []
        for key, similarity in raw_results:
            data = self._storage.load(key)
            if data is None:
                continue
            try:
                pattern = Pattern.model_validate(data)
            except Exception as exc:
                _log.warning("Skipping corrupted pattern at %r: %s", key, exc)
                continue
            multiplier = self._eval_store.get_eval_multiplier(key, task)
            effective = similarity * multiplier
            match = Match(
                pattern=pattern,
                similarity=round(min(similarity, 1.0), 6),
                reuse_tier=reuse_tier(similarity),
                pattern_key=key,
            )
            weighted.append((effective, match))

        weighted.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in weighted[:limit]]

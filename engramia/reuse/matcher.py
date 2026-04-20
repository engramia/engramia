# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Eval-weighted pattern matcher.

Extends raw semantic similarity with an eval quality multiplier so that
high-quality patterns rank above lower-quality ones with similar embeddings.

Effective score = cosine_similarity * eval_multiplier
where eval_multiplier in [0.5, 1.0] based on stored eval score.
"""

import logging

from engramia._util import PATTERNS_PREFIX, reuse_tier
from engramia.core.eval_store import EvalStore
from engramia.providers.base import EmbeddingProvider, StorageBackend
from engramia.types import Match, Pattern

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
        embeddings: EmbeddingProvider | None,
        eval_store: EvalStore,
    ) -> None:
        self._storage = storage
        self._embeddings = embeddings
        self._eval_store = eval_store

    def find(self, task: str, limit: int = 5, fetch_multiplier: int = 1) -> list[Match]:
        """Return the best-matching patterns for *task*, eval-weighted.

        Args:
            task: Task description to match against stored patterns.
            limit: Maximum number of results to return.
            fetch_multiplier: Over-sampling factor for the underlying
                storage query. The matcher fetches ``limit * fetch_multiplier``
                raw candidates before eval-weighting and truncation so the
                eval-score reranker has room to promote high-score
                patterns that lost a few points of raw cosine. Callers
                that plan to also deduplicate the result should pass a
                value >= 3; callers that want the raw top-N should pass 1
                (default).

        Returns:
            List of Match objects sorted by effective (weighted) score descending.
        """
        if self._embeddings is None:
            return []
        embedding = self._embeddings.embed(task)
        raw_results = self._storage.search_similar(
            embedding,
            limit=limit * max(1, fetch_multiplier),
            prefix=PATTERNS_PREFIX,
        )

        weighted: list[tuple[float, Match]] = []
        for key, similarity in raw_results:
            data = self._storage.load(key)
            if data is None:
                continue
            try:
                pattern = Pattern.model_validate(data)
            except (ValueError, KeyError) as exc:
                _log.warning("Skipping corrupted pattern at %r: %s", key, exc)
                continue
            multiplier = self._eval_store.get_eval_multiplier(key, task)
            effective = similarity * multiplier

            # Cosine on unit vectors is bounded in [-1, 1] and the storage
            # layer clamps to [0, 1]. Hitting the ceiling here would mean
            # an upstream provider is returning non-normalised vectors or
            # a sum-of-products larger than the norm product — a real
            # correctness bug worth a loud warning instead of silent
            # clamping that happens to keep Pydantic validation quiet.
            sim_clamped = min(max(similarity, 0.0), 1.0)
            if abs(similarity - sim_clamped) > 1e-6:
                _log.warning(
                    "Similarity from %s returned %.6f — outside expected [0, 1] "
                    "range; clamping. This usually indicates an embedding "
                    "provider that does not normalise output vectors.",
                    self._embeddings.__class__.__name__,
                    similarity,
                )
            match = Match(
                pattern=pattern,
                similarity=round(sim_clamped, 6),
                reuse_tier=reuse_tier(sim_clamped),
                pattern_key=key,
                effective_score=round(min(max(effective, 0.0), 1.0), 6),
            )
            weighted.append((effective, match))

        weighted.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in weighted[:limit]]

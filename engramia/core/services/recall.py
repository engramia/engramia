# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""RecallService — finds stored patterns most relevant to a task."""

import logging
import time

from engramia._util import PATTERNS_PREFIX, jaccard, reuse_tier
from engramia.analytics.collector import ROICollector
from engramia.core.eval_store import EvalStore
from engramia.core.success_patterns import SuccessPatternStore
from engramia.exceptions import ProviderError
from engramia.providers.base import EmbeddingProvider, StorageBackend
from engramia.reuse.matcher import PatternMatcher
from engramia.telemetry import tracing as _tracing
from engramia.telemetry.metrics import inc_recall_hit, inc_recall_miss
from engramia.types import JACCARD_DEDUP_THRESHOLD, Match, Pattern

_log = logging.getLogger(__name__)

_DEDUP_FETCH_MULTIPLIER = 3
_SECONDS_PER_DAY = 86400.0


def _apply_recency_weight(
    matches: list[Match],
    weight: float,
    half_life_days: float,
    now: float | None = None,
) -> list[Match]:
    """Blend a recency decay factor into each match's ``effective_score``
    and re-sort the list in descending effective-score order.

    The factor is exponential half-life decay on the pattern's stored
    ``timestamp``::

        recency_factor = 0.5 ** (max(0, now - p.timestamp) / (H * 86400))
        new_effective  = base * (recency_factor ** weight)

    where ``base`` is the current ``effective_score`` if set (eval-
    weighted path), else the raw ``similarity`` (plain path). The
    ``max(0, …)`` clamp matches ``SuccessPatternStore.run_aging`` so
    future-dated timestamps (clock skew) cannot award a >1 boost.

    ``weight == 0.0`` is a no-op; callers should skip this function
    when they already know the weight is zero. Kept permissive for
    defensive use.
    """
    if weight <= 0.0:
        return matches
    if not matches:
        return matches
    now = now if now is not None else time.time()
    half_life_seconds = half_life_days * _SECONDS_PER_DAY
    out: list[Match] = []
    for m in matches:
        age = max(0.0, now - m.pattern.timestamp)
        recency_factor = 0.5 ** (age / half_life_seconds)
        base = m.effective_score if m.effective_score is not None else m.similarity
        blended = base * (recency_factor**weight)
        out.append(
            m.model_copy(update={"effective_score": round(min(max(blended, 0.0), 1.0), 6)})
        )
    out.sort(key=lambda mm: mm.effective_score if mm.effective_score is not None else 0.0, reverse=True)
    return out


def _deduplicate_matches(matches: list[Match]) -> list[Match]:
    """Keep only the best-scoring pattern per task group using union-find connected components.

    All matches transitively connected by Jaccard similarity > JACCARD_DEDUP_THRESHOLD
    (A similar to B, B similar to C → A, B, C in the same group) are reduced to the
    single highest-scoring pattern. This avoids the ordering-dependent behaviour of a
    greedy pairwise scan.
    """
    n = len(matches)
    if n == 0:
        return []

    parent = list(range(n))
    rank = [0] * n

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path-halving compression
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx == ry:
            return
        if rank[rx] < rank[ry]:
            rx, ry = ry, rx
        parent[ry] = rx
        if rank[rx] == rank[ry]:
            rank[rx] += 1

    for i in range(n):
        for j in range(i + 1, n):
            if jaccard(matches[i].pattern.task, matches[j].pattern.task) > JACCARD_DEDUP_THRESHOLD:
                union(i, j)

    # Pick the best representative per group by eval score, tracking the
    # earliest input position so we can preserve the caller's intended
    # ordering — PatternMatcher returns matches already sorted by the
    # eval-weighted effective score. Re-sorting here by raw similarity
    # silently discarded that ordering (Bug: knowledge_updates / temporal
    # dimensions on the LongMemEval suite regressed from ~93% to ~26-68%).
    best: dict[int, tuple[int, Match]] = {}
    for i, match in enumerate(matches):
        root = find(i)
        if root not in best or match.pattern.success_score > best[root][1].pattern.success_score:
            best[root] = (i, match)

    return [m for _, m in sorted(best.values(), key=lambda pair: pair[0])]


class RecallService:
    """Finds stored patterns most relevant to a task.

    Args:
        storage: Storage backend for persistence.
        embeddings: Embedding provider.
        eval_store: Shared EvalStore instance.
        pattern_store: Shared SuccessPatternStore instance.
        roi_collector: Shared ROICollector instance.
    """

    def __init__(
        self,
        storage: StorageBackend,
        embeddings: EmbeddingProvider | None,
        eval_store: EvalStore,
        pattern_store: SuccessPatternStore,
        roi_collector: ROICollector,
    ) -> None:
        self._storage = storage
        self._embeddings = embeddings
        self._eval_store = eval_store
        self._pattern_store = pattern_store
        self._roi_collector = roi_collector

    def _keyword_fallback(self, task: str, limit: int) -> list[Match]:
        """Brute-force keyword recall used when embeddings are unavailable.

        Scores all stored patterns using word-level Jaccard similarity and
        returns the top *limit* results sorted by score descending.

        Args:
            task: The query task string.
            limit: Maximum number of matches to return.

        Returns:
            List of Match objects, may be empty if no patterns are stored.
        """
        all_keys = self._storage.list_keys(prefix=PATTERNS_PREFIX)
        scored: list[tuple[float, str, Pattern]] = []
        for key in all_keys:
            data = self._storage.load(key)
            if data is None:
                continue
            try:
                pattern = Pattern.model_validate(data)
            except (ValueError, KeyError):
                continue
            score = jaccard(task, pattern.task)
            if score > 0.0:
                scored.append((score, key, pattern))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            Match(
                pattern=p,
                similarity=s,
                reuse_tier=reuse_tier(s),
                pattern_key=k,
            )
            for s, k, p in scored[:limit]
        ]

    @_tracing.traced("memory.recall")
    def recall(
        self,
        task: str,
        limit: int = 5,
        deduplicate: bool = True,
        eval_weighted: bool = True,
        recency_weight: float = 0.0,
        recency_half_life_days: float = 30.0,
        readonly: bool = False,
    ) -> list[Match]:
        """Find stored patterns most relevant to task.

        Falls back to keyword-based (Jaccard) search if the embedding
        provider raises an exception, enabling graceful degradation when
        the embedding API is unavailable.

        Args:
            task: Natural language description of the new task.
            limit: Maximum number of matches to return.
            deduplicate: Group near-duplicate tasks and return only the
                top-scoring pattern per group.
            eval_weighted: Boost patterns with high eval scores.
            recency_weight: Bias ranking toward recently-stored patterns
                via exponential half-life decay (``0.0`` = off,
                ``1.0`` = full decay). Multiplies with ``eval_weighted``.
                See ``_apply_recency_weight`` for the exact formula.
            recency_half_life_days: Half-life of the recency decay, in
                days. Ignored when ``recency_weight == 0``.
            readonly: When ``True``, skip the side-effect of marking
                returned patterns as reused (``mark_reused`` adds +0.1 to
                ``success_score`` on every recall). Use for benchmark
                runs, eval harnesses, or anything where reproducibility
                across repeated identical queries is required.
                Defaults to ``False`` (production behaviour).

        Returns:
            List of Match objects sorted by effective score descending.
        """
        # Dedup needs an over-sampled pool so the Jaccard grouping has a
        # chance to collapse near-duplicates before we truncate to `limit`.
        # `PatternMatcher` owns the over-sampling on the eval-weighted path
        # via `fetch_multiplier`, so we only pre-expand on the plain path
        # and keep a single `limit * 3` storage query end-to-end instead of
        # the old `limit * 9` that double-expanded in both layers.
        fetch_multiplier = _DEDUP_FETCH_MULTIPLIER if deduplicate else 1

        try:
            if self._embeddings is None:
                raise ProviderError("No embedding provider configured — using keyword fallback")
            if eval_weighted:
                matcher = PatternMatcher(self._storage, self._embeddings, self._eval_store)
                matches = matcher.find(task, limit=limit, fetch_multiplier=fetch_multiplier)
            else:
                embedding = self._embeddings.embed(task)
                results = self._storage.search_similar(
                    embedding, limit=limit * fetch_multiplier, prefix=PATTERNS_PREFIX
                )
                matches = []
                for key, similarity in results:
                    data = self._storage.load(key)
                    if data is None:
                        continue
                    pattern = Pattern.model_validate(data)
                    matches.append(
                        Match(
                            pattern=pattern,
                            similarity=min(similarity, 1.0),
                            reuse_tier=reuse_tier(similarity),
                            pattern_key=key,
                        )
                    )
        except (ProviderError, TimeoutError, ConnectionError) as exc:
            # Only degrade to the keyword fallback on provider / network
            # failures. Validation errors, authorization errors, and
            # programmer bugs (AttributeError, KeyError, TypeError) should
            # propagate so they surface in observability instead of
            # silently turning into a low-quality recall.
            _log.warning(
                "Embedding provider failed during recall, falling back to keyword search: %s",
                exc,
            )
            matches = self._keyword_fallback(task, limit * fetch_multiplier)

        if recency_weight > 0.0:
            matches = _apply_recency_weight(matches, recency_weight, recency_half_life_days)

        if deduplicate:
            matches = _deduplicate_matches(matches)

        result = matches[:limit]
        if not readonly:
            for m in result:
                self._pattern_store.mark_reused(m.pattern_key)

        if result:
            best = result[0]
            inc_recall_hit()
            self._roi_collector.record_recall(
                best_similarity=best.similarity,
                best_reuse_tier=best.reuse_tier,
                best_pattern_key=best.pattern_key,
            )
        else:
            inc_recall_miss()
            self._roi_collector.record_recall(
                best_similarity=None,
                best_reuse_tier=None,
                best_pattern_key="",
            )
        return result

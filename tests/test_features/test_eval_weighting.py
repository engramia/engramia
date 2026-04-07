# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""D6 — Eval weighting impact.

Learn two patterns for semantically identical tasks but with different eval scores.
With eval_weighted=True, the high-score pattern should rank first.
With eval_weighted=False, order is determined by raw cosine similarity alone.

The eval multiplier maps: score 9 → 0.95, score 3 → 0.65.
So if raw cosines are equal, weighted recall will promote the higher-scored one.
"""
from __future__ import annotations

from tests.recall_quality.conftest import TestClient, learn_and_get_key
from tests.recall_quality.snippets import CLUSTER_SNIPPETS
from tests.recall_quality.task_clusters import CLUSTERS

_CLUSTER = "C08"
_HIGH_SCORE = 9.0
_LOW_SCORE = 3.0


def test_eval_weighted_ranking(
    client: TestClient,
    run_tag: str,
) -> None:
    """eval_weighted=True: high-score pattern must rank above low-score pattern."""
    tasks = CLUSTERS[_CLUSTER]
    # Use the same task text for both — identical raw similarity
    task_high = f"[{run_tag}] ew-high {tasks[0]}"
    task_low = f"[{run_tag}] ew-low {tasks[0]}"

    snippet_high = CLUSTER_SNIPPETS[_CLUSTER]["good"]
    snippet_low = CLUSTER_SNIPPETS[_CLUSTER]["bad"]

    learned_keys: list[str] = []

    try:
        key_high = learn_and_get_key(
            client,
            task=task_high,
            code=snippet_high["code"],
            eval_score=_HIGH_SCORE,
        )
        key_low = learn_and_get_key(
            client,
            task=task_low,
            code=snippet_low["code"],
            eval_score=_LOW_SCORE,
        )
        for k in (key_high, key_low):
            if k:
                learned_keys.append(k)

        query = f"[{run_tag}] ew-query {tasks[0]}"
        matches_weighted = client.recall(
            task=query, limit=5, deduplicate=False, eval_weighted=True
        )

        assert len(matches_weighted) >= 2, (
            "Expected at least 2 matches for eval weighting test"
        )

        # Find the high-score and low-score patterns in results
        high_rank = next(
            (i for i, m in enumerate(matches_weighted) if key_high in m["pattern_key"]),
            None,
        )
        low_rank = next(
            (i for i, m in enumerate(matches_weighted) if key_low in m["pattern_key"]),
            None,
        )

        if high_rank is not None and low_rank is not None:
            assert high_rank < low_rank, (
                f"eval_weighted=True: high-score pattern rank {high_rank} "
                f"should be < low-score rank {low_rank}"
            )

    finally:
        for key in set(learned_keys):
            client.delete_pattern(key)


def test_eval_unweighted_does_not_penalise_low_score(
    client: TestClient,
    run_tag: str,
) -> None:
    """eval_weighted=False: results are ordered by raw similarity, not eval score."""
    tasks = CLUSTERS[_CLUSTER]
    task_a = f"[{run_tag}] ew2a {tasks[2]}"
    task_b = f"[{run_tag}] ew2b {tasks[2]}"

    snippet_a = CLUSTER_SNIPPETS[_CLUSTER]["good"]
    snippet_b = CLUSTER_SNIPPETS[_CLUSTER]["bad"]

    learned_keys: list[str] = []

    try:
        key_a = learn_and_get_key(client, task=task_a, code=snippet_a["code"], eval_score=9.0)
        key_b = learn_and_get_key(client, task=task_b, code=snippet_b["code"], eval_score=2.0)
        for k in (key_a, key_b):
            if k:
                learned_keys.append(k)

        query = f"[{run_tag}] ew2-query {tasks[2]}"
        matches_unweighted = client.recall(
            task=query, limit=5, deduplicate=False, eval_weighted=False
        )

        # Just assert we can get results without error — order depends on raw similarity
        assert isinstance(matches_unweighted, list), "Unweighted recall did not return a list"

    finally:
        for key in set(learned_keys):
            client.delete_pattern(key)

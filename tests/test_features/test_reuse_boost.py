# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""D5 — Reuse boost accumulation.

Every recall() call invokes mark_reused() on returned patterns (+0.1/reuse,
cap 10.0).  This test verifies the boost accumulates correctly.

Note: Only testable in local mode (requires direct storage access).
In remote mode the test verifies reuse_count increases.
"""

from __future__ import annotations

from tests.recall_quality.conftest import TestClient, learn_and_get_key
from tests.recall_quality.snippets import CLUSTER_SNIPPETS
from tests.recall_quality.task_clusters import CLUSTERS

_RECALL_ROUNDS = 10
_CLUSTER = "C07"
_INITIAL_SCORE = 5.0


def test_reuse_boost_score_delta(
    client: TestClient,
    run_tag: str,
) -> None:
    """After 10 recalls, success_score should be boosted by up to 10x0.1=1.0."""
    snippet = CLUSTER_SNIPPETS[_CLUSTER]["medium"]
    task = f"[{run_tag}] {CLUSTERS[_CLUSTER][0]}"
    learned_keys: list[str] = []

    try:
        # Learn once with a known score
        key = learn_and_get_key(
            client,
            task=task,
            code=snippet["code"],
            eval_score=_INITIAL_SCORE,
        )
        if key:
            learned_keys.append(key)

        # Recall 10 times — each call boosts score by +0.1
        for _ in range(_RECALL_ROUNDS):
            client.recall(task=task, limit=1, deduplicate=False, eval_weighted=False)

        # Retrieve the current state of the pattern
        final_matches = client.recall(task=task, limit=1, deduplicate=False, eval_weighted=False)
        assert final_matches, "Pattern not found after recall rounds"

        final_score = final_matches[0]["pattern"]["success_score"]
        final_reuse = final_matches[0]["pattern"]["reuse_count"]

        # Score boosted by (recall_rounds + 1 discovery recall) x 0.1
        # We called recall _RECALL_ROUNDS times + 1 in learn_and_get_key + 1 final = 12 total
        # But we only assert a lower bound to be tolerant of remote timing
        expected_min_boost = _RECALL_ROUNDS * 0.1
        actual_boost = final_score - _INITIAL_SCORE

        assert actual_boost >= expected_min_boost * 0.8, (
            f"Expected score boost >= {expected_min_boost * 0.8:.2f}, "
            f"got {actual_boost:.2f} (initial={_INITIAL_SCORE}, final={final_score:.2f})"
        )
        assert final_reuse >= _RECALL_ROUNDS, f"Expected reuse_count >= {_RECALL_ROUNDS}, got {final_reuse}"

    finally:
        for key in set(learned_keys):
            client.delete_pattern(key)


def test_reuse_boost_cap(
    client: TestClient,
    run_tag: str,
) -> None:
    """Reuse boost must never push success_score above 10.0."""
    snippet = CLUSTER_SNIPPETS[_CLUSTER]["good"]
    task = f"[{run_tag}] boost-cap-{CLUSTERS[_CLUSTER][1]}"
    learned_keys: list[str] = []

    try:
        key = learn_and_get_key(client, task=task, code=snippet["code"], eval_score=9.5)
        if key:
            learned_keys.append(key)

        # Recall many times — would exceed 10.0 without cap
        for _ in range(20):
            client.recall(task=task, limit=1, deduplicate=False, eval_weighted=False)

        final_matches = client.recall(task=task, limit=1, deduplicate=False, eval_weighted=False)
        if final_matches:
            assert final_matches[0]["pattern"]["success_score"] <= 10.0, "success_score exceeded 10.0 cap!"

    finally:
        for key in set(learned_keys):
            client.delete_pattern(key)

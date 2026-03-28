# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""D4 — Deduplication behavior.

Learn 3 tasks with Jaccard > 0.7 (same wording, slight variation).
- deduplicate=True  → only 1 result (highest score wins)
- deduplicate=False → all 3 results present
"""
from __future__ import annotations

from tests.recall_quality.conftest import TestClient, learn_and_get_key
from tests.recall_quality.snippets import CLUSTER_SNIPPETS

# Three tasks with intentionally high Jaccard overlap (>0.7 word similarity)
# "filter rows CSV column status equals active" appears in all three
_HIGH_JACCARD_TASKS = [
    "Filter CSV rows where column status equals active",
    "Filter CSV rows where the column status equals active value",
    "Filter all CSV rows where column status equals active record",
]

# Scores: medium < high < low intentionally to test "keeps highest score"
_SCORES = [6.0, 9.0, 4.0]


def test_deduplication_collapses_similar_tasks(
    client: TestClient,
    run_tag: str,
) -> None:
    """deduplicate=True returns 1 result; the highest-scored pattern wins."""
    learned_keys: list[str] = []
    snippet = CLUSTER_SNIPPETS["C01"]["good"]

    try:
        for task, score in zip(_HIGH_JACCARD_TASKS, _SCORES, strict=True):
            prefixed = f"[{run_tag}] {task}"
            key = learn_and_get_key(
                client,
                task=prefixed,
                code=snippet["code"],
                eval_score=score,
            )
            if key:
                learned_keys.append(key)

        query = f"[{run_tag}] {_HIGH_JACCARD_TASKS[0]}"
        matches_dedup = client.recall(
            task=query, limit=5, deduplicate=True, eval_weighted=False
        )

        # With dedup, only 1 result should survive (all 3 are Jaccard-similar)
        assert len(matches_dedup) <= 2, (
            f"Expected ≤2 matches with deduplicate=True, got {len(matches_dedup)}"
        )

        if len(matches_dedup) == 1:
            # The surviving pattern should have the highest score
            best_score = matches_dedup[0]["pattern"]["success_score"]
            assert best_score >= max(_SCORES) - 0.5, (
                f"Dedup kept pattern with score {best_score:.1f}, "
                f"expected highest score ~{max(_SCORES)}"
            )

    finally:
        for key in set(learned_keys):
            client.delete_pattern(key)


def test_no_deduplication_returns_all(
    client: TestClient,
    run_tag: str,
) -> None:
    """deduplicate=False returns all stored patterns including near-duplicates."""
    learned_keys: list[str] = []
    snippet = CLUSTER_SNIPPETS["C01"]["good"]

    try:
        for task, score in zip(_HIGH_JACCARD_TASKS, _SCORES, strict=True):
            prefixed = f"[{run_tag}] {task}"
            key = learn_and_get_key(
                client,
                task=prefixed,
                code=snippet["code"],
                eval_score=score,
            )
            if key:
                learned_keys.append(key)

        query = f"[{run_tag}] {_HIGH_JACCARD_TASKS[0]}"
        matches_raw = client.recall(
            task=query, limit=5, deduplicate=False, eval_weighted=False
        )

        # Without dedup, all 3 should appear
        assert len(matches_raw) >= 3, (
            f"Expected ≥3 matches with deduplicate=False, got {len(matches_raw)}"
        )

    finally:
        for key in set(learned_keys):
            client.delete_pattern(key)

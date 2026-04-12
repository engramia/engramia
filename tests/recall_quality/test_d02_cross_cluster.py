# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""D2 — Cross-cluster isolation.

For each cluster pair: learn cluster A patterns, recall with a cluster B query.
Assert that cross-cluster similarity is below cross_threshold.
"""

from __future__ import annotations

import pytest

from tests.recall_quality.conftest import QualityTracker, TestClient, learn_and_get_key
from tests.recall_quality.snippets import CLUSTER_SNIPPETS
from tests.recall_quality.task_clusters import CLUSTERS

# Test representative cross-cluster pairs (6 non-adjacent pairs)
_CROSS_PAIRS = [
    ("C01", "C07"),  # CSV vs Moving Average
    ("C02", "C09"),  # CSV Aggregate vs Async Batch
    ("C03", "C11"),  # TOML vs PG Upsert
    ("C04", "C10"),  # YAML Merge vs Email Regex
    ("C05", "C12"),  # HTTP Retry vs File Dedup
    ("C06", "C08"),  # Pagination vs Z-Score
]


@pytest.mark.parametrize("cluster_a,cluster_b", _CROSS_PAIRS)
def test_cross_cluster_isolation(
    client: TestClient,
    run_tag: str,
    thresholds: dict,
    quality_tracker: QualityTracker,
    cluster_a: str,
    cluster_b: str,
) -> None:
    """Patterns from cluster A should NOT match a cluster B query."""
    snippet_a = CLUSTER_SNIPPETS[cluster_a]["good"]
    tasks_a = CLUSTERS[cluster_a]
    learned_keys: list[str] = []

    try:
        # Learn 3 patterns from cluster A
        for task in tasks_a[:3]:
            prefixed = f"[{run_tag}] {task}"
            key = learn_and_get_key(
                client,
                task=prefixed,
                code=snippet_a["code"],
                eval_score=snippet_a["eval_score"],
            )
            if key:
                learned_keys.append(key)

        # Recall with a cluster B query
        query = f"[{run_tag}] {CLUSTERS[cluster_b][0]}"
        matches = client.recall(task=query, limit=5, deduplicate=False, eval_weighted=False)

        # Filter to only matches from cluster A (by checking task prefix and content)
        cross_matches = [
            m for m in matches if any(tasks_a[i][:30] in m["pattern"]["task"] for i in range(len(tasks_a)))
        ]

        if not cross_matches:
            # Perfect isolation — record zero cross-sim
            quality_tracker.record_d2(cluster_a, cluster_b, 0.0, passed=True)
            return

        max_cross_sim = max(m["similarity"] for m in cross_matches)
        threshold = thresholds.get("cross_threshold", 0.50)
        passed = max_cross_sim < threshold

        quality_tracker.record_d2(cluster_a, cluster_b, max_cross_sim, passed)

        assert passed, (
            f"{cluster_a}→{cluster_b}: cross-cluster max sim {max_cross_sim:.4f} "
            f">= cross_threshold {threshold:.4f}\n"
            f"  Query:   {CLUSTERS[cluster_b][0]}\n"
            f"  Matched: {cross_matches[0]['pattern']['task']}"
        )

    finally:
        for key in set(learned_keys):
            client.delete_pattern(key)

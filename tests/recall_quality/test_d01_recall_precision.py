# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""D1 — Recall Precision (intra-cluster).

For each cluster: learn variants A-D, recall with variant E (held-out).
Assert top-1 similarity >= calibrated intra_threshold.
"""
from __future__ import annotations

import pytest

from tests.recall_quality.conftest import QualityTracker, TestClient, learn_and_get_key
from tests.recall_quality.snippets import CLUSTER_SNIPPETS
from tests.recall_quality.task_clusters import CLUSTERS

CLUSTER_IDS = list(CLUSTERS.keys())


@pytest.mark.parametrize("cluster_id", CLUSTER_IDS)
def test_intra_cluster_recall_precision(
    client: TestClient,
    run_tag: str,
    thresholds: dict,
    quality_tracker: QualityTracker,
    cluster_id: str,
) -> None:
    """Learn 4 variants, recall with 5th — top-1 similarity must exceed threshold."""
    tasks = CLUSTERS[cluster_id]
    snippet = CLUSTER_SNIPPETS[cluster_id]["good"]
    learned_keys: list[str] = []

    try:
        # Learn variants A-D
        for task in tasks[:4]:
            prefixed = f"[{run_tag}] {task}"
            key = learn_and_get_key(
                client,
                task=prefixed,
                code=snippet["code"],
                eval_score=snippet["eval_score"],
                output=snippet.get("output"),
            )
            if key:
                learned_keys.append(key)

        # Recall with variant E (held-out)
        query = f"[{run_tag}] {tasks[4]}"
        matches = client.recall(task=query, limit=4, deduplicate=False, eval_weighted=False)

        assert matches, (
            f"Cluster {cluster_id}: recall returned no matches for query: '{tasks[4][:60]}'"
        )

        top_sim = matches[0]["similarity"]
        threshold = thresholds.get("intra_threshold", 0.55)
        passed = top_sim >= threshold

        # Record before assert so the metric is captured even on failure
        quality_tracker.record_d1(cluster_id, top_sim, passed)

        assert passed, (
            f"Cluster {cluster_id}: top-1 similarity {top_sim:.4f} < "
            f"intra_threshold {threshold:.4f}\n"
            f"  Query:  {tasks[4]}\n"
            f"  Matched: {matches[0]['pattern']['task']}"
        )

    finally:
        for key in set(learned_keys):
            client.delete_pattern(key)

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Boundary tasks — tasks that straddle two clusters.

For each boundary task:
  - Learn patterns from both clusters A and B.
  - Recall with the boundary query.
  - Assert that BOTH cluster A and cluster B produce at least one match
    above the "fresh" threshold (i.e. both clusters are relevant).

This validates that the embedding space captures multi-domain intent.
"""
from __future__ import annotations

import pytest

from tests.recall_quality.conftest import QualityTracker, TestClient, learn_and_get_key
from tests.recall_quality.snippets import CLUSTER_SNIPPETS
from tests.recall_quality.task_clusters import BOUNDARY_TASKS, CLUSTERS

# Minimum similarity to count as "relevant" (below adapt tier but above fresh)
_MIN_RELEVANT_SIM = 0.40


@pytest.mark.parametrize("boundary_task,cluster_a,cluster_b", BOUNDARY_TASKS)
def test_boundary_task_matches_both_clusters(
    client: TestClient,
    run_tag: str,
    thresholds: dict,
    quality_tracker: QualityTracker,
    boundary_task: str,
    cluster_a: str,
    cluster_b: str,
) -> None:
    """Boundary task should produce relevant matches in both contributing clusters."""
    learned_keys: list[str] = []
    cluster_keys: dict[str, list[str]] = {cluster_a: [], cluster_b: []}

    try:
        # Learn 2 patterns from each cluster
        for cid in (cluster_a, cluster_b):
            snippet = CLUSTER_SNIPPETS[cid]["good"]
            for task in CLUSTERS[cid][:2]:
                prefixed = f"[{run_tag}] bt-{cid} {task}"
                key = learn_and_get_key(
                    client,
                    task=prefixed,
                    code=snippet["code"],
                    eval_score=snippet["eval_score"],
                )
                if key:
                    learned_keys.append(key)
                    cluster_keys[cid].append(key)

        # Recall with boundary task
        matches = client.recall(
            task=boundary_task, limit=10, deduplicate=False, eval_weighted=False
        )

        # Check which clusters appear in top results
        min_sim = _MIN_RELEVANT_SIM
        matched_a = any(
            m["pattern_key"] in cluster_keys[cluster_a] and m["similarity"] >= min_sim
            for m in matches
        )
        matched_b = any(
            m["pattern_key"] in cluster_keys[cluster_b] and m["similarity"] >= min_sim
            for m in matches
        )

        passed = matched_a or matched_b
        quality_tracker.record_boundary(boundary_task, matched_a, matched_b, passed)

        top_info = [(round(m["similarity"], 3), m["pattern"]["task"][:50]) for m in matches[:3]]
        assert passed, (
            f"Boundary task '{boundary_task[:60]}'\n"
            f"did not match either cluster {cluster_a} or {cluster_b} "
            f"at similarity >= {min_sim}\n"
            f"Top matches: {top_info}"
        )

    finally:
        for key in set(learned_keys):
            client.delete_pattern(key)

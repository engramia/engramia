# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""D3 — Noise rejection.

Learn patterns from several clusters.  Recall with completely unrelated
noise tasks.  Assert max similarity stays below noise_threshold.
"""
from __future__ import annotations

import pytest

from tests.recall_quality.conftest import QualityTracker, TestClient, learn_and_get_key
from tests.recall_quality.snippets import CLUSTER_SNIPPETS
from tests.recall_quality.task_clusters import CLUSTERS, NOISE_TASKS

# Use a representative subset of clusters to populate the store
_POPULATE_CLUSTERS = ["C01", "C05", "C07", "C10"]


def test_noise_rejection(
    client: TestClient,
    run_tag: str,
    thresholds: dict,
    quality_tracker: QualityTracker,
) -> None:
    """Noise queries against a populated store should produce no strong matches."""
    learned_keys: list[str] = []

    try:
        # Populate store with patterns from a few clusters
        for cid in _POPULATE_CLUSTERS:
            snippet = CLUSTER_SNIPPETS[cid]["good"]
            for task in CLUSTERS[cid][:3]:
                prefixed = f"[{run_tag}] {task}"
                key = learn_and_get_key(
                    client,
                    task=prefixed,
                    code=snippet["code"],
                    eval_score=snippet["eval_score"],
                )
                if key:
                    learned_keys.append(key)

        threshold = thresholds.get("noise_threshold", 0.50)
        failures: list[str] = []
        all_max_sims: list[float] = []

        for noise_task in NOISE_TASKS:
            matches = client.recall(
                task=noise_task,
                limit=3,
                deduplicate=False,
                eval_weighted=False,
            )
            if matches:
                max_sim = max(m["similarity"] for m in matches)
                all_max_sims.append(max_sim)
                if max_sim >= threshold:
                    failures.append(
                        f"Noise task '{noise_task[:60]}' matched "
                        f"sim={max_sim:.4f} >= {threshold:.4f}"
                    )
            else:
                all_max_sims.append(0.0)

        overall_max = max(all_max_sims) if all_max_sims else 0.0
        quality_tracker.record_d3(
            noise_total=len(NOISE_TASKS),
            noise_failed=len(failures),
            max_noise_sim=overall_max,
        )

        assert not failures, (
            f"{len(failures)}/{len(NOISE_TASKS)} noise tasks exceeded threshold:\n"
            + "\n".join(f"  {f}" for f in failures)
        )

    finally:
        for key in set(learned_keys):
            client.delete_pattern(key)

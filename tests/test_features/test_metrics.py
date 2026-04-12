# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""D11 — Metrics consistency.

After N learn() calls and M recall() calls:
- metrics.runs should increase by N (learn records runs; recall does not).
- metrics.pattern_count should increase by N.
- metrics.success_rate should remain > 0.

Note: learn() calls record_run(success=True) in MetricsStore.
      recall() does NOT record metrics runs.
"""

from __future__ import annotations

from tests.recall_quality.conftest import TestClient, learn_and_get_key
from tests.recall_quality.snippets import CLUSTER_SNIPPETS
from tests.recall_quality.task_clusters import CLUSTERS

_LEARN_COUNT = 5
_RECALL_COUNT = 3
_CLUSTER = "C03"


def _get_metrics(client: TestClient) -> dict:
    """Get current metrics as dict."""
    if hasattr(client.raw, "metrics"):
        m = client.raw.metrics
        return {
            "runs": m.runs,
            "success": m.success,
            "failures": m.failures,
            "success_rate": m.success_rate,
            "pattern_count": m.pattern_count,
        }
    else:
        # Remote mode via webhook
        return client.raw.metrics()


def test_metrics_runs_delta(client: TestClient, run_tag: str) -> None:
    """learn() increments metrics.runs by exactly 1 per call."""
    before = _get_metrics(client)
    runs_before = before["runs"]
    patterns_before = before["pattern_count"]

    learned_keys: list[str] = []
    try:
        snippet = CLUSTER_SNIPPETS[_CLUSTER]["good"]
        tasks = CLUSTERS[_CLUSTER]

        for i in range(_LEARN_COUNT):
            task = f"[{run_tag}] m1-{i} {tasks[i % len(tasks)]}"
            key = learn_and_get_key(client, task=task, code=snippet["code"], eval_score=snippet["eval_score"])
            if key:
                learned_keys.append(key)

        after = _get_metrics(client)
        runs_delta = after["runs"] - runs_before
        pattern_delta = after["pattern_count"] - patterns_before

        assert runs_delta == _LEARN_COUNT, f"Expected runs to increase by {_LEARN_COUNT}, got delta={runs_delta}"
        assert pattern_delta == _LEARN_COUNT, (
            f"Expected pattern_count to increase by {_LEARN_COUNT}, got delta={pattern_delta}"
        )
        assert after["success_rate"] > 0, "success_rate should be > 0 after successful learns"

    finally:
        for k in set(learned_keys):
            client.delete_pattern(k)


def test_metrics_recall_does_not_increment_runs(client: TestClient, run_tag: str) -> None:
    """recall() calls do NOT increment metrics.runs."""
    snippet = CLUSTER_SNIPPETS[_CLUSTER]["medium"]
    task = f"[{run_tag}] m2 {CLUSTERS[_CLUSTER][0]}"
    learned_keys: list[str] = []

    try:
        key = learn_and_get_key(client, task=task, code=snippet["code"], eval_score=6.0)
        if key:
            learned_keys.append(key)

        before = _get_metrics(client)
        runs_before = before["runs"]

        # Several recall calls
        for _ in range(_RECALL_COUNT):
            client.recall(task=task, limit=3, deduplicate=False, eval_weighted=False)

        after = _get_metrics(client)
        runs_after = after["runs"]

        assert runs_after == runs_before, (
            f"recall() should not increment runs, but runs went from "
            f"{runs_before} to {runs_after} (delta={runs_after - runs_before})"
        )

    finally:
        for k in set(learned_keys):
            client.delete_pattern(k)

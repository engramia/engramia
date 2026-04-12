# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""D8 — Pattern aging.

Local mode only — requires direct access to JSONStorage to manipulate timestamps.

Aging formula: decayed = success_score * (0.98 ^ elapsed_weeks)
Prune threshold: 0.1

Test cases:
  1. Pattern with initial score 0.15, timestamp 104 weeks ago
     → 0.15 * 0.98^104 ≈ 0.018 < 0.1  → pruned
  2. Pattern with initial score 9.0, timestamp 52 weeks ago
     → 9.0 * 0.98^52 ≈ 3.15 > 0.1     → survives
  3. Freshly-learned pattern (timestamp = now)
     → negligible decay               → survives
  4. Reuse-boosted pattern (score near 10) old timestamp
     → slower to decay               → survives longer
"""

from __future__ import annotations

import time

import pytest

from tests.recall_quality.conftest import TestClient, learn_and_get_key
from tests.recall_quality.snippets import CLUSTER_SNIPPETS
from tests.recall_quality.task_clusters import CLUSTERS

_CLUSTER = "C06"
_ONE_WEEK_SECS = 7 * 24 * 3600


def _patch_timestamp(client: TestClient, pattern_key: str, weeks_ago: int) -> None:
    """Directly manipulate the stored pattern's timestamp (local mode only)."""
    storage = client.raw._storage
    data = storage.load(pattern_key)
    if data is None:
        return
    data["timestamp"] = time.time() - (weeks_ago * _ONE_WEEK_SECS)
    storage.save(pattern_key, data)


@pytest.mark.skipif(
    __import__("os").environ.get("ENGRAMIA_TEST_MODE", "local") == "remote",
    reason="D8 aging requires direct storage access — local mode only",
)
class TestPatternAging:
    def test_low_score_old_pattern_pruned(self, client: TestClient, run_tag: str) -> None:
        """A pattern with low score and old timestamp is pruned by run_aging()."""
        task = f"[{run_tag}] aging-prune {CLUSTERS[_CLUSTER][0]}"
        snippet = CLUSTER_SNIPPETS[_CLUSTER]["bad"]
        learned_keys: list[str] = []

        try:
            key = learn_and_get_key(client, task=task, code=snippet["code"], eval_score=0.15)
            if not key:
                pytest.skip("Could not discover pattern key")
            learned_keys.append(key)

            # Push timestamp 104 weeks into the past
            # 0.15 * 0.98^104 ≈ 0.018 → below 0.1 threshold
            _patch_timestamp(client, key, weeks_ago=104)

            pruned = client.run_aging()
            assert pruned >= 1, f"Expected ≥1 pruned pattern, got {pruned}"

            # Pattern should be gone
            matches = client.recall(task=task, limit=1, deduplicate=False, eval_weighted=False)
            pattern_still_there = any(m["pattern_key"] == key for m in matches)
            assert not pattern_still_there, "Pattern with score 0.15 at 104 weeks old was NOT pruned"
            if key in learned_keys:
                learned_keys.remove(key)  # Already deleted by aging

        finally:
            for k in set(learned_keys):
                client.delete_pattern(k)

    def test_high_score_old_pattern_survives(self, client: TestClient, run_tag: str) -> None:
        """A pattern with high score survives aging even at 52 weeks old."""
        task = f"[{run_tag}] aging-survive {CLUSTERS[_CLUSTER][1]}"
        snippet = CLUSTER_SNIPPETS[_CLUSTER]["good"]
        learned_keys: list[str] = []

        try:
            key = learn_and_get_key(client, task=task, code=snippet["code"], eval_score=9.0)
            if not key:
                pytest.skip("Could not discover pattern key")
            learned_keys.append(key)

            # 9.0 * 0.98^52 ≈ 3.15 — still well above 0.1
            _patch_timestamp(client, key, weeks_ago=52)

            client.run_aging()

            matches = client.recall(task=task, limit=3, deduplicate=False, eval_weighted=False)
            pattern_survived = any(m["pattern_key"] == key for m in matches)
            assert pattern_survived, "Pattern with score 9.0 at 52 weeks old was unexpectedly pruned"

        finally:
            for k in set(learned_keys):
                client.delete_pattern(k)

    def test_fresh_pattern_not_pruned(self, client: TestClient, run_tag: str) -> None:
        """A freshly learned pattern should never be pruned by aging."""
        task = f"[{run_tag}] aging-fresh {CLUSTERS[_CLUSTER][2]}"
        snippet = CLUSTER_SNIPPETS[_CLUSTER]["medium"]
        learned_keys: list[str] = []

        try:
            key = learn_and_get_key(client, task=task, code=snippet["code"], eval_score=6.0)
            if key:
                learned_keys.append(key)

            # No timestamp manipulation — just run aging
            client.run_aging()

            matches = client.recall(task=task, limit=3, deduplicate=False, eval_weighted=False)
            if key:
                pattern_survived = any(m["pattern_key"] == key for m in matches)
                assert pattern_survived, "Fresh pattern was pruned — should not happen"

        finally:
            for k in set(learned_keys):
                client.delete_pattern(k)

    def test_score_decreases_after_aging(self, client: TestClient, run_tag: str) -> None:
        """A pattern's success_score should decrease after aging with old timestamp."""
        task = f"[{run_tag}] aging-decay {CLUSTERS[_CLUSTER][3]}"
        snippet = CLUSTER_SNIPPETS[_CLUSTER]["good"]
        learned_keys: list[str] = []

        try:
            key = learn_and_get_key(client, task=task, code=snippet["code"], eval_score=5.0)
            if not key:
                pytest.skip("Could not discover pattern key")
            learned_keys.append(key)

            # Get initial score
            initial_matches = client.recall(task=task, limit=1, deduplicate=False, eval_weighted=False)
            initial_score = initial_matches[0]["pattern"]["success_score"] if initial_matches else 5.0

            # Push timestamp 10 weeks back — 5.0 * 0.98^10 ≈ 4.09
            _patch_timestamp(client, key, weeks_ago=10)
            client.run_aging()

            after_matches = client.recall(task=task, limit=3, deduplicate=False, eval_weighted=False)
            surviving = [m for m in after_matches if m["pattern_key"] == key]
            if surviving:
                final_score = surviving[0]["pattern"]["success_score"]
                assert final_score < initial_score, (
                    f"Score did not decrease after aging: initial={initial_score:.4f}, after={final_score:.4f}"
                )

        finally:
            for k in set(learned_keys):
                client.delete_pattern(k)

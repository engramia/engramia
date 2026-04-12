# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""D7 — Learning dynamics: warm-up curve.

Sequential learn/recall cycles within one cluster.
Context length (total chars of matched code) should be non-decreasing.

Note: NOT strictly monotonic — deduplication may suppress a new pattern
if it's too similar to an existing higher-scored one.
"""

from __future__ import annotations

from tests.recall_quality.conftest import TestClient, learn_and_get_key
from tests.recall_quality.snippets import CLUSTER_SNIPPETS
from tests.recall_quality.task_clusters import CLUSTERS

_CLUSTER = "C05"
_ROUNDS = 5


def _context_len(matches: list[dict]) -> int:
    """Total chars of code across all returned matches."""
    return sum(len(m["pattern"]["code"] or "") for m in matches)


def test_context_grows_with_more_patterns(
    client: TestClient,
    run_tag: str,
) -> None:
    """Recall context length should be non-decreasing after each learn round."""
    tasks = CLUSTERS[_CLUSTER]
    snippet = CLUSTER_SNIPPETS[_CLUSTER]["good"]
    learned_keys: list[str] = []
    context_lens: list[int] = []

    try:
        for i in range(min(_ROUNDS, len(tasks))):
            task = f"[{run_tag}] wc{i} {tasks[i]}"
            key = learn_and_get_key(
                client,
                task=task,
                code=snippet["code"],
                eval_score=snippet["eval_score"],
            )
            if key:
                learned_keys.append(key)

            # Recall with a stable query (variant 0 semantics)
            query = f"[{run_tag}] wc-query {tasks[0]}"
            matches = client.recall(task=query, limit=5, deduplicate=False, eval_weighted=False)
            context_lens.append(_context_len(matches))

        assert len(context_lens) >= 2, "Need at least 2 rounds to check growth"

        # Context should be non-decreasing (may plateau due to dedup)
        violations = [
            (i, context_lens[i], context_lens[i + 1])
            for i in range(len(context_lens) - 1)
            if context_lens[i + 1] < context_lens[i]
        ]
        assert not violations, f"Context length decreased in rounds: {violations}\nFull trajectory: {context_lens}"

        # At least one growth event expected over 5 rounds
        assert context_lens[-1] > 0, "Context never grew — no patterns were recalled"
        assert max(context_lens) > min(context_lens), f"Context never increased over {_ROUNDS} rounds: {context_lens}"

    finally:
        for key in set(learned_keys):
            client.delete_pattern(key)

"""Tests for B1 — mark_reused() called on recall()."""


def _get_reuse_count(brain, task: str) -> int:
    """Read reuse_count from storage for a pattern matching the task."""
    from engramia._util import PATTERNS_PREFIX

    for key in brain._storage.list_keys(prefix=PATTERNS_PREFIX):
        data = brain._storage.load(key)
        if data and data.get("task") == task:
            return data.get("reuse_count", 0)
    return -1


class TestMarkReusedOnRecall:
    def test_recall_increments_reuse_count(self, brain):
        brain.learn(task="Reuse test task", code="pass", eval_score=7.0)
        brain.recall(task="Reuse test task", limit=1)
        # mark_reused updates storage — check there, not the Match object
        assert _get_reuse_count(brain, "Reuse test task") == 1

    def test_multiple_recalls_increment_count(self, brain):
        brain.learn(task="Multi reuse task", code="pass", eval_score=7.0)
        brain.recall(task="Multi reuse task", limit=1)
        brain.recall(task="Multi reuse task", limit=1)
        brain.recall(task="Multi reuse task", limit=1)
        assert _get_reuse_count(brain, "Multi reuse task") == 3

    def test_no_recall_leaves_count_zero(self, brain):
        brain.learn(task="Unreused task", code="pass", eval_score=7.0)
        assert _get_reuse_count(brain, "Unreused task") == 0

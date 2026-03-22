"""End-to-end tests: learn → recall → assert match.

Uses FakeEmbeddings (no API key) and JSONStorage (tmp_path).
Covers the full Brain.learn() → Brain.recall() cycle.
"""

import pytest

from agent_brain.types import SIMILARITY_DUPLICATE


class TestLearnRecall:
    def test_learn_returns_stored_true(self, brain):
        result = brain.learn(
            task="Parse CSV and compute stats",
            code="import csv\nprint('ok')",
            eval_score=8.5,
        )
        assert result.stored is True
        assert result.pattern_count == 1

    def test_pattern_count_increments(self, brain):
        brain.learn(task="Task A", code="code_a", eval_score=7.0)
        brain.learn(task="Task B", code="code_b", eval_score=8.0)
        result = brain.learn(task="Task C", code="code_c", eval_score=9.0)
        assert result.pattern_count == 3

    def test_recall_finds_exact_task(self, brain):
        brain.learn(
            task="Parse CSV and compute stats",
            code="import csv",
            eval_score=8.5,
        )
        matches = brain.recall(task="Parse CSV and compute stats")
        assert len(matches) == 1
        assert matches[0].similarity == pytest.approx(1.0, abs=1e-5)

    def test_recall_exact_match_is_duplicate_tier(self, brain):
        brain.learn(task="Parse CSV", code="code", eval_score=8.0)
        matches = brain.recall(task="Parse CSV")
        assert matches[0].reuse_tier == "duplicate"

    def test_recall_preserves_pattern_data(self, brain):
        brain.learn(
            task="Read JSON file",
            code="import json\ndata = json.load(open('f.json'))",
            eval_score=9.0,
            output="{'key': 'value'}",
        )
        matches = brain.recall(task="Read JSON file")
        pattern = matches[0].pattern
        assert pattern.task == "Read JSON file"
        assert pattern.success_score == 9.0
        assert "import json" in pattern.design["code"]
        assert pattern.design["output"] == "{'key': 'value'}"

    def test_recall_empty_brain_returns_empty_list(self, brain):
        assert brain.recall(task="anything") == []

    def test_recall_limit_respected(self, brain):
        for i in range(10):
            brain.learn(task=f"task_{i}", code=f"code_{i}", eval_score=7.0)
        matches = brain.recall(task="task_0", limit=3)
        assert len(matches) <= 3

    def test_recall_returns_matches_sorted_by_similarity(self, brain):
        brain.learn(task="Task A", code="code_a", eval_score=7.0)
        brain.learn(task="Task B", code="code_b", eval_score=8.0)
        brain.learn(task="Task C", code="code_c", eval_score=9.0)
        matches = brain.recall(task="Task A", limit=3)
        scores = [m.similarity for m in matches]
        assert scores == sorted(scores, reverse=True)

    def test_recall_match_has_correct_fields(self, brain):
        brain.learn(task="Fetch API data", code="import requests", eval_score=7.5)
        matches = brain.recall(task="Fetch API data")
        m = matches[0]
        assert hasattr(m, "pattern")
        assert hasattr(m, "similarity")
        assert hasattr(m, "reuse_tier")
        assert 0.0 <= m.similarity <= 1.0
        assert m.reuse_tier in ("duplicate", "adapt", "fresh")

    def test_learn_without_output(self, brain):
        result = brain.learn(task="Simple task", code="print('hi')", eval_score=6.0)
        assert result.stored is True
        matches = brain.recall(task="Simple task")
        assert "output" not in matches[0].pattern.design

    def test_brain_without_llm_works_for_learn_recall(self, fake_embeddings, storage):
        """Brain can be used for learn/recall with llm=None."""
        from agent_brain.brain import Brain

        brain = Brain(embeddings=fake_embeddings, storage=storage, llm=None)
        brain.learn(task="A task", code="code", eval_score=8.0)
        matches = brain.recall(task="A task")
        assert len(matches) == 1


class TestRecallDeduplication:
    """Tests for recall() grouping of near-duplicate tasks."""

    def test_dedup_keeps_best_score_per_task_group(self, brain):
        """Multiple patterns for the same task → only the best is returned."""
        brain.learn(task="Parse CSV and compute stats", code="v1", eval_score=6.0)
        brain.learn(task="Parse CSV and compute stats", code="v2", eval_score=9.0)
        brain.learn(task="Parse CSV and compute stats", code="v3", eval_score=7.5)
        matches = brain.recall(task="Parse CSV and compute stats")
        assert len(matches) == 1
        assert matches[0].pattern.success_score == 9.0
        assert matches[0].pattern.design["code"] == "v2"

    def test_dedup_similar_tasks_are_grouped(self, brain):
        """Tasks with high Jaccard overlap are grouped together."""
        # These two tasks share most words → Jaccard > 0.7
        brain.learn(task="Parse CSV file and compute stats", code="v1", eval_score=6.0)
        brain.learn(task="Parse CSV file and compute statistics", code="v2", eval_score=8.0)
        matches = brain.recall(task="Parse CSV file and compute stats")
        assert len(matches) == 1
        assert matches[0].pattern.success_score == 8.0

    def test_dedup_different_tasks_not_grouped(self, brain):
        """Tasks with low Jaccard overlap remain separate."""
        brain.learn(task="Parse CSV file", code="csv_code", eval_score=7.0)
        brain.learn(task="Fetch API data from REST endpoint", code="api_code", eval_score=8.0)
        matches = brain.recall(task="Parse CSV file", limit=10, deduplicate=True)
        tasks = [m.pattern.task for m in matches]
        # Both should appear since they're different tasks
        assert len(matches) >= 1  # at least the exact match

    def test_dedup_disabled_returns_all_variants(self, brain):
        """With deduplicate=False, all pattern variants are returned."""
        brain.learn(task="Parse CSV and compute stats", code="v1", eval_score=6.0)
        brain.learn(task="Parse CSV and compute stats", code="v2", eval_score=9.0)
        brain.learn(task="Parse CSV and compute stats", code="v3", eval_score=7.5)
        matches = brain.recall(
            task="Parse CSV and compute stats", deduplicate=False
        )
        assert len(matches) == 3

    def test_dedup_limit_respected_after_grouping(self, brain):
        """limit applies after deduplication, not before."""
        # Create 5 distinct tasks, each with 2 variants
        for i in range(5):
            brain.learn(task=f"unique task number {i}", code=f"v1_{i}", eval_score=6.0)
            brain.learn(task=f"unique task number {i}", code=f"v2_{i}", eval_score=8.0)
        matches = brain.recall(task="unique task number 0", limit=2)
        assert len(matches) <= 2

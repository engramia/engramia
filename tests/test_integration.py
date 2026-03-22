"""Integration test: full learn → evaluate → feedback → recall → compose cycle.

Uses FakeEmbeddings + JSONStorage (no API keys).
LLM calls in evaluate() and compose() are mocked.
"""

import json
from unittest.mock import MagicMock

import pytest

from agent_brain.exceptions import ProviderError

from agent_brain import Brain
from agent_brain.types import EvalResult, Pipeline


EVAL_RESPONSE = json.dumps({
    "task_alignment": 8,
    "code_quality": 7,
    "workspace_usage": 8,
    "robustness": 6,
    "overall": 7.5,
    "feedback": "Add error handling for missing input files.",
})

COMPOSE_RESPONSE = json.dumps({
    "stages": [
        {"task": "Read CSV file", "reads": ["input.csv"], "writes": ["data.json"]},
        {"task": "Compute statistics from data", "reads": ["data.json"], "writes": ["report.txt"]},
    ]
})


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.call.return_value = EVAL_RESPONSE
    return llm


@pytest.fixture
def full_brain(fake_embeddings, storage, mock_llm):
    return Brain(embeddings=fake_embeddings, storage=storage, llm=mock_llm)


class TestFullCycle:
    def test_learn_then_recall(self, full_brain):
        full_brain.learn(task="Parse CSV file", code="import csv", eval_score=8.5)
        matches = full_brain.recall(task="Parse CSV file")
        assert len(matches) == 1
        assert matches[0].similarity == pytest.approx(1.0, abs=1e-4)

    def test_learn_increments_metrics(self, full_brain):
        full_brain.learn(task="Task A", code="code", eval_score=7.0)
        full_brain.learn(task="Task B", code="code", eval_score=8.0)
        m = full_brain.metrics
        assert m.runs == 2
        assert m.pattern_count == 2

    def test_evaluate_stores_feedback(self, full_brain):
        # Evaluate twice to push feedback past the "count >= 2" threshold
        full_brain.evaluate(task="Parse CSV", code="import csv", num_evals=1)
        full_brain.evaluate(task="Parse CSV", code="import csv", num_evals=1)
        feedback = full_brain.get_feedback()
        assert any("error handling" in f.lower() for f in feedback)

    def test_evaluate_returns_eval_result(self, full_brain):
        result = full_brain.evaluate(task="Parse CSV", code="import csv", num_evals=1)
        assert isinstance(result, EvalResult)
        assert result.median_score == pytest.approx(7.5)

    def test_metrics_avg_score_after_learn(self, full_brain):
        full_brain.learn(task="Task", code="code", eval_score=8.0)
        m = full_brain.metrics
        assert m.avg_eval_score == pytest.approx(8.0, abs=0.1)

    def test_run_aging_prunes_nothing_fresh(self, full_brain):
        full_brain.learn(task="Recent task", code="code", eval_score=9.0)
        pruned = full_brain.run_aging()
        assert pruned == 0

    def test_compose_returns_pipeline(self, full_brain, mock_llm):
        mock_llm.call.return_value = COMPOSE_RESPONSE
        full_brain.learn(task="Read CSV file", code="import csv", eval_score=8.0)
        pipeline = full_brain.compose(task="Read CSV and compute stats")
        assert isinstance(pipeline, Pipeline)
        assert len(pipeline.stages) >= 1

    def test_compose_without_llm_raises(self, fake_embeddings, storage):
        brain = Brain(embeddings=fake_embeddings, storage=storage, llm=None)
        with pytest.raises(ProviderError, match="compose()"):
            brain.compose("some task")

    def test_evaluate_without_llm_raises(self, fake_embeddings, storage):
        brain = Brain(embeddings=fake_embeddings, storage=storage, llm=None)
        with pytest.raises(ProviderError, match="evaluate()"):
            brain.evaluate("task", "code")

    def test_recall_eval_weighted(self, full_brain):
        """Higher eval score should boost recall ranking."""
        full_brain.learn(task="Parse CSV data", code="v1", eval_score=4.0)
        full_brain.learn(task="Parse CSV data", code="v2", eval_score=9.0)
        # With dedup, should return the 9.0 version
        matches = full_brain.recall(task="Parse CSV data")
        assert matches[0].pattern.success_score == pytest.approx(9.0)

    def test_full_cycle(self, full_brain, mock_llm):
        """Complete pipeline: learn → evaluate → feedback → recall → compose."""
        # 1. Learn two patterns
        full_brain.learn(task="Read CSV file", code="import csv\nprint('done')", eval_score=7.0)
        full_brain.learn(task="Compute stats from data", code="import statistics", eval_score=8.5)

        # 2. Evaluate and capture feedback
        full_brain.evaluate(task="Read CSV file", code="import csv", num_evals=1)
        full_brain.evaluate(task="Read CSV file", code="import csv", num_evals=1)

        # 3. Recall finds relevant patterns
        matches = full_brain.recall(task="Read CSV file")
        assert len(matches) >= 1

        # 4. Feedback is captured
        feedback = full_brain.get_feedback()
        assert isinstance(feedback, list)

        # 5. Compose builds a pipeline
        mock_llm.call.return_value = COMPOSE_RESPONSE
        pipeline = full_brain.compose("Read CSV and compute statistics")
        assert isinstance(pipeline, Pipeline)

        # 6. Metrics reflect all runs
        m = full_brain.metrics
        assert m.runs >= 2
        assert m.pattern_count == 2

"""Tests for MultiEvaluator (mocked LLM)."""

import json
from unittest.mock import MagicMock

import pytest

from agent_brain.eval.evaluator import MultiEvaluator, _check_adversarial, _extract_json


VALID_EVAL_JSON = json.dumps({
    "task_alignment": 8,
    "code_quality": 7,
    "workspace_usage": 9,
    "robustness": 6,
    "overall": 7.5,
    "feedback": "Add error handling for missing files.",
})


def _make_llm(response: str = VALID_EVAL_JSON) -> MagicMock:
    llm = MagicMock()
    llm.call.return_value = response
    return llm


class TestExtractJson:
    def test_raw_json(self):
        data = _extract_json('{"a": 1}')
        assert data == {"a": 1}

    def test_markdown_code_block(self):
        text = '```json\n{"a": 1}\n```'
        assert _extract_json(text) == {"a": 1}

    def test_embedded_json(self):
        text = 'Here is the result: {"a": 1} done.'
        assert _extract_json(text) == {"a": 1}

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _extract_json("no json here at all")


class TestAdversarialCheck:
    def test_hardcoded_output_detected(self):
        output = "result: 42.0 average"
        code = f'print("{output}")'
        assert _check_adversarial(code, output) is True

    def test_computed_output_not_flagged(self):
        code = "import csv\nresult = sum(row) / len(rows)"
        output = "42.0"
        assert _check_adversarial(code, "42.0") is False  # too short

    def test_none_output_returns_false(self):
        assert _check_adversarial("code", None) is False


class TestMultiEvaluator:
    def test_evaluate_returns_eval_result(self):
        llm = _make_llm()
        ev = MultiEvaluator(llm, num_evals=3)
        result = ev.evaluate("Parse CSV", "import csv", output="done")
        assert result.median_score == pytest.approx(7.5)
        assert len(result.scores) == 3

    def test_high_variance_detected(self):
        responses = [
            json.dumps({"task_alignment": 9, "code_quality": 9, "workspace_usage": 9, "robustness": 9, "overall": 9.0, "feedback": "good"}),
            json.dumps({"task_alignment": 4, "code_quality": 4, "workspace_usage": 4, "robustness": 4, "overall": 4.0, "feedback": "poor"}),
            json.dumps({"task_alignment": 7, "code_quality": 7, "workspace_usage": 7, "robustness": 7, "overall": 7.0, "feedback": "ok"}),
        ]
        llm = MagicMock()
        llm.call.side_effect = responses
        ev = MultiEvaluator(llm, num_evals=3)
        result = ev.evaluate("task", "code")
        assert result.high_variance is True
        assert result.variance == pytest.approx(5.0)

    def test_feedback_from_worst_run(self):
        responses = [
            json.dumps({"task_alignment": 9, "code_quality": 9, "workspace_usage": 9, "robustness": 9, "overall": 9.0, "feedback": "great"}),
            json.dumps({"task_alignment": 3, "code_quality": 3, "workspace_usage": 3, "robustness": 3, "overall": 3.0, "feedback": "needs work"}),
        ]
        llm = MagicMock()
        llm.call.side_effect = responses
        ev = MultiEvaluator(llm, num_evals=2)
        result = ev.evaluate("task", "code")
        assert result.feedback == "needs work"

    def test_raises_if_all_evals_fail(self):
        llm = MagicMock()
        llm.call.side_effect = Exception("LLM down")
        ev = MultiEvaluator(llm, num_evals=2)
        with pytest.raises(RuntimeError, match="All evaluation attempts failed"):
            ev.evaluate("task", "code")

    def test_partial_failure_uses_successful_evals(self):
        responses = [
            Exception("fail"),
            VALID_EVAL_JSON,
            VALID_EVAL_JSON,
        ]
        llm = MagicMock()
        llm.call.side_effect = responses
        ev = MultiEvaluator(llm, num_evals=3)
        result = ev.evaluate("task", "code")
        assert result.median_score > 0

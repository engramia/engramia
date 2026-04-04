# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Unit tests for engramia/mcp/server.py — MCP tool dispatch logic.

Tests the _dispatch() function with a mock Memory instance, covering:
- All 7 tools (learn, recall, evaluate, compose, feedback, metrics, aging)
- Argument extraction and type coercion
- Return value structure
- Unknown tool error
"""

import sys
from types import ModuleType
from unittest.mock import MagicMock, PropertyMock

import pytest

from engramia.types import (
    EvalResult,
    EvalScore,
    LearnResult,
    Match,
    Metrics,
    Pattern,
    Pipeline,
    PipelineStage,
)

# ---------------------------------------------------------------------------
# Stub the ``mcp`` package so we can import engramia.mcp.server without
# having the mcp SDK installed in the test environment.
# ---------------------------------------------------------------------------
_mcp_stub = ModuleType("mcp")
_mcp_server = ModuleType("mcp.server")
_mcp_server_stdio = ModuleType("mcp.server.stdio")
_mcp_server_models = ModuleType("mcp.server.models")
_mcp_types = ModuleType("mcp.types")

def _noop_decorator(*a, **kw):
    """No-op decorator that returns the function unchanged."""
    def _inner(fn):
        return fn
    return _inner

class _FakeServer:
    def __init__(self, *a, **kw):
        pass
    def list_tools(self):
        return _noop_decorator
    def call_tool(self):
        return _noop_decorator

_mcp_server.Server = _FakeServer
_mcp_server_models.InitializationOptions = MagicMock
_mcp_types.TextContent = MagicMock
_mcp_types.Tool = MagicMock

for name, mod in [
    ("mcp", _mcp_stub),
    ("mcp.server", _mcp_server),
    ("mcp.server.stdio", _mcp_server_stdio),
    ("mcp.server.models", _mcp_server_models),
    ("mcp.types", _mcp_types),
]:
    sys.modules.setdefault(name, mod)

from engramia.mcp.server import _dispatch  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mem():
    """Mock Memory with all methods used by _dispatch."""
    m = MagicMock()

    # learn()
    m.learn.return_value = LearnResult(stored=True, pattern_count=5)

    # recall()
    m.recall.return_value = [
        Match(
            pattern=Pattern(
                task="Parse CSV",
                design={"code": "import csv"},
                success_score=8.5,
                reuse_count=2,
            ),
            similarity=0.95,
            reuse_tier="duplicate",
            pattern_key="patterns/abc123",
        )
    ]

    # evaluate()
    score = EvalScore(
        task_alignment=8, code_quality=7, workspace_usage=8,
        robustness=6, overall=7.5, feedback="Add error handling.",
    )
    m.evaluate.return_value = EvalResult(
        scores=[score],
        median_score=7.5,
        variance=0.0,
        high_variance=False,
        feedback="Add error handling.",
        adversarial_detected=False,
    )

    # compose()
    m.compose.return_value = Pipeline(
        task="Process data end-to-end",
        stages=[
            PipelineStage(
                name="reader",
                task="Read CSV file",
                design={},
                reads=["input.csv"],
                writes=["data.json"],
                reuse_tier="adapt",
                similarity=0.85,
            ),
        ],
        valid=True,
        contract_errors=[],
    )

    # get_feedback()
    m.get_feedback.return_value = [
        {"pattern": "Add error handling", "count": 3, "score": 2.1}
    ]

    # metrics (property)
    type(m).metrics = PropertyMock(return_value=Metrics(
        runs=10, success=8, failures=2, pipeline_reuse=3,
        success_rate=0.8, pattern_count=5, avg_eval_score=7.2,
    ))

    # run_aging()
    m.run_aging.return_value = 2

    return m


# ---------------------------------------------------------------------------
# engramia_learn
# ---------------------------------------------------------------------------


class TestLearnDispatch:
    def test_learn_calls_memory_with_correct_args(self, mem):
        _dispatch(mem, "engramia_learn", {
            "task": "Parse CSV", "code": "import csv", "eval_score": "8.5",
        })
        mem.learn.assert_called_once_with(
            task="Parse CSV", code="import csv", eval_score=8.5, output=None,
        )

    def test_learn_returns_stored_and_count(self, mem):
        result = _dispatch(mem, "engramia_learn", {
            "task": "T", "code": "C", "eval_score": 7.0,
        })
        assert result == {"stored": True, "pattern_count": 5}

    def test_learn_passes_optional_output(self, mem):
        _dispatch(mem, "engramia_learn", {
            "task": "T", "code": "C", "eval_score": 7.0, "output": "stdout data",
        })
        assert mem.learn.call_args.kwargs["output"] == "stdout data"

    def test_learn_coerces_eval_score_to_float(self, mem):
        _dispatch(mem, "engramia_learn", {
            "task": "T", "code": "C", "eval_score": "9",
        })
        assert mem.learn.call_args.kwargs["eval_score"] == 9.0


# ---------------------------------------------------------------------------
# engramia_recall
# ---------------------------------------------------------------------------


class TestRecallDispatch:
    def test_recall_calls_memory_with_defaults(self, mem):
        _dispatch(mem, "engramia_recall", {"task": "Parse CSV"})
        mem.recall.assert_called_once_with(task="Parse CSV", limit=5)

    def test_recall_passes_custom_limit(self, mem):
        _dispatch(mem, "engramia_recall", {"task": "T", "limit": "10"})
        mem.recall.assert_called_once_with(task="T", limit=10)

    def test_recall_returns_match_list_with_expected_fields(self, mem):
        result = _dispatch(mem, "engramia_recall", {"task": "Parse CSV"})
        assert isinstance(result, list)
        assert len(result) == 1
        match = result[0]
        assert match["similarity"] == pytest.approx(0.95)
        assert match["reuse_tier"] == "duplicate"
        assert match["pattern_key"] == "patterns/abc123"
        assert match["task"] == "Parse CSV"
        assert match["success_score"] == 8.5
        assert match["code"] == "import csv"

    def test_recall_empty_store_returns_empty_list(self, mem):
        mem.recall.return_value = []
        result = _dispatch(mem, "engramia_recall", {"task": "anything"})
        assert result == []


# ---------------------------------------------------------------------------
# engramia_evaluate
# ---------------------------------------------------------------------------


class TestEvaluateDispatch:
    def test_evaluate_calls_memory_with_defaults(self, mem):
        _dispatch(mem, "engramia_evaluate", {"task": "T", "code": "C"})
        mem.evaluate.assert_called_once_with(task="T", code="C", output=None, num_evals=3)

    def test_evaluate_passes_custom_num_evals(self, mem):
        _dispatch(mem, "engramia_evaluate", {
            "task": "T", "code": "C", "num_evals": "5",
        })
        assert mem.evaluate.call_args.kwargs["num_evals"] == 5

    def test_evaluate_returns_expected_fields(self, mem):
        result = _dispatch(mem, "engramia_evaluate", {"task": "T", "code": "C"})
        assert result["median_score"] == 7.5
        assert result["variance"] == 0.0
        assert result["high_variance"] is False
        assert result["feedback"] == "Add error handling."
        assert result["adversarial_detected"] is False


# ---------------------------------------------------------------------------
# engramia_compose
# ---------------------------------------------------------------------------


class TestComposeDispatch:
    def test_compose_calls_memory(self, mem):
        _dispatch(mem, "engramia_compose", {"task": "Process data"})
        mem.compose.assert_called_once_with(task="Process data")

    def test_compose_returns_pipeline_structure(self, mem):
        result = _dispatch(mem, "engramia_compose", {"task": "Process data"})
        assert result["task"] == "Process data end-to-end"
        assert result["valid"] is True
        assert result["contract_errors"] == []
        assert len(result["stages"]) == 1
        stage = result["stages"][0]
        assert stage["name"] == "reader"
        assert stage["reads"] == ["input.csv"]
        assert stage["writes"] == ["data.json"]
        assert stage["reuse_tier"] == "adapt"


# ---------------------------------------------------------------------------
# engramia_feedback
# ---------------------------------------------------------------------------


class TestFeedbackDispatch:
    def test_feedback_calls_memory_with_defaults(self, mem):
        _dispatch(mem, "engramia_feedback", {})
        mem.get_feedback.assert_called_once_with(task_type=None, limit=4)

    def test_feedback_passes_custom_params(self, mem):
        _dispatch(mem, "engramia_feedback", {"task_type": "csv", "limit": "10"})
        mem.get_feedback.assert_called_once_with(task_type="csv", limit=10)

    def test_feedback_returns_wrapped_list(self, mem):
        result = _dispatch(mem, "engramia_feedback", {})
        assert "feedback" in result
        assert len(result["feedback"]) == 1


# ---------------------------------------------------------------------------
# engramia_metrics
# ---------------------------------------------------------------------------


class TestMetricsDispatch:
    def test_metrics_reads_property(self, mem):
        result = _dispatch(mem, "engramia_metrics", {})
        assert result["runs"] == 10
        assert result["success_rate"] == 0.8
        assert result["avg_eval_score"] == 7.2
        assert result["pattern_count"] == 5

    def test_metrics_computes_reuse_rate(self, mem):
        result = _dispatch(mem, "engramia_metrics", {})
        assert result["reuse_rate"] == pytest.approx(3 / 10)

    def test_metrics_reuse_rate_zero_when_no_runs(self, mem):
        type(mem).metrics = PropertyMock(return_value=Metrics())
        result = _dispatch(mem, "engramia_metrics", {})
        assert result["reuse_rate"] == 0.0
        assert result["runs"] == 0


# ---------------------------------------------------------------------------
# engramia_aging
# ---------------------------------------------------------------------------


class TestAgingDispatch:
    def test_aging_calls_run_aging(self, mem):
        _dispatch(mem, "engramia_aging", {})
        mem.run_aging.assert_called_once()

    def test_aging_returns_pruned_count(self, mem):
        result = _dispatch(mem, "engramia_aging", {})
        assert result == {"pruned": 2}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestDispatchErrors:
    def test_unknown_tool_raises_value_error(self, mem):
        with pytest.raises(ValueError, match="Unknown tool"):
            _dispatch(mem, "nonexistent_tool", {})

    def test_missing_required_arg_raises_key_error(self, mem):
        with pytest.raises(KeyError):
            _dispatch(mem, "engramia_learn", {"task": "T"})  # missing code, eval_score

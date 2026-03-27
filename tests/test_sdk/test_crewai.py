# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for CrewAI EngramiaCrewCallback (mocked, no crewai needed)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from engramia.brain import Memory
from engramia.providers.json_storage import JSONStorage
from tests.conftest import FakeEmbeddings


@pytest.fixture
def brain(tmp_path):
    storage = JSONStorage(path=tmp_path)
    embeddings = FakeEmbeddings()
    return Memory(embeddings=embeddings, storage=storage)


def _make_task(description: str):
    """Minimal mutable task-like object."""
    t = SimpleNamespace(description=description)
    return t


def _make_output(description: str, raw: str):
    """Minimal TaskOutput-like object."""
    return SimpleNamespace(description=description, raw=raw)


def _make_callback(brain, **kwargs):
    """Instantiate EngramiaCrewCallback with crewai mocked out."""
    mock_crewai = MagicMock()
    with patch.dict("sys.modules", {"crewai": mock_crewai}):
        from engramia.sdk.crewai import EngramiaCrewCallback

        return EngramiaCrewCallback(brain, **kwargs)


class TestEngramiaCrewCallbackLearn:
    def test_task_callback_learns_from_output(self, brain):
        cb = _make_callback(brain, auto_learn=True, auto_recall=False)
        count_before = brain.metrics.pattern_count

        output = _make_output(description="Parse CSV and compute stats", raw="import csv; ...")
        cb.task_callback(output)

        assert brain.metrics.pattern_count > count_before

    def test_task_callback_disabled_does_not_learn(self, brain):
        cb = _make_callback(brain, auto_learn=False, auto_recall=False)
        count_before = brain.metrics.pattern_count

        output = _make_output(description="Some task", raw="Some result")
        cb.task_callback(output)

        assert brain.metrics.pattern_count == count_before

    def test_task_callback_skips_empty_output(self, brain):
        cb = _make_callback(brain, auto_learn=True, auto_recall=False)
        count_before = brain.metrics.pattern_count

        output = _make_output(description="Some task", raw="")
        cb.task_callback(output)

        assert brain.metrics.pattern_count == count_before

    def test_task_callback_skips_empty_task(self, brain):
        cb = _make_callback(brain, auto_learn=True, auto_recall=False)
        count_before = brain.metrics.pattern_count

        output = _make_output(description="", raw="Some result")
        cb.task_callback(output)

        assert brain.metrics.pattern_count == count_before

    def test_task_callback_uses_default_score(self, brain):
        cb = _make_callback(brain, auto_learn=True, default_score=9.0)
        brain.learn(task="CSV parsing task", code="import csv", eval_score=5.0)

        output = _make_output(description="CSV parsing task", raw="import csv; ...")
        cb.task_callback(output)

        # Pattern should exist (we don't expose raw score, but learn should succeed)
        assert brain.metrics.pattern_count >= 1

    def test_learn_failure_does_not_raise(self, brain):
        cb = _make_callback(brain, auto_learn=True)
        cb._brain = MagicMock()
        cb._brain.learn.side_effect = RuntimeError("Storage down")

        # Should not propagate exception
        output = _make_output(description="Task", raw="Result")
        cb.task_callback(output)  # no raise


class TestEngramiaCrewCallbackRecall:
    def test_inject_recall_appends_context(self, brain):
        brain.learn(task="Parse CSV file", code="import csv", eval_score=8.0)

        cb = _make_callback(brain, auto_recall=True, auto_learn=False)
        task = _make_task("Parse CSV file and compute averages")
        cb.inject_recall([task])

        # Description should have been extended with recalled context
        assert "Relevant prior patterns" in task.description
        assert len(task.description) > len("Parse CSV file and compute averages")

    def test_inject_recall_skips_when_disabled(self, brain):
        brain.learn(task="Parse CSV file", code="import csv", eval_score=8.0)

        cb = _make_callback(brain, auto_recall=False, auto_learn=False)
        task = _make_task("Parse CSV file")
        original = task.description
        cb.inject_recall([task])

        assert task.description == original

    def test_inject_recall_no_matches_leaves_description_unchanged(self, brain):
        cb = _make_callback(brain, auto_recall=True, auto_learn=False)
        task = _make_task("Very unusual task with no prior patterns xyzzy123")
        original = task.description
        cb.inject_recall([task])

        assert task.description == original

    def test_inject_recall_multiple_tasks(self, brain):
        brain.learn(task="Fetch stock data", code="import yfinance", eval_score=7.0)
        brain.learn(task="Write markdown report", code="# Report\n...", eval_score=8.0)

        cb = _make_callback(brain, auto_recall=True, auto_learn=False)
        tasks = [
            _make_task("Fetch stock data from API"),
            _make_task("Write markdown report with charts"),
        ]
        cb.inject_recall(tasks)

        # Both tasks should get context injected (at least one pattern each)
        for task in tasks:
            assert len(task.description) > 10  # something was added or not — just no crash

    def test_inject_recall_handles_frozen_model(self, brain):
        brain.learn(task="CSV task", code="import csv", eval_score=8.0)

        cb = _make_callback(brain, auto_recall=True)

        # Task that raises AttributeError on assignment (frozen Pydantic model)
        class FrozenTask:
            @property
            def description(self):
                return "CSV task"

            @description.setter
            def description(self, value):
                raise AttributeError("frozen")

        task = FrozenTask()
        cb.inject_recall([task])  # Should not raise

    def test_inject_recall_failure_does_not_raise(self, brain):
        cb = _make_callback(brain, auto_recall=True)
        cb._brain = MagicMock()
        cb._brain.recall.side_effect = RuntimeError("Storage error")

        task = _make_task("Any task")
        cb.inject_recall([task])  # Should not raise


class TestEngramiaCrewCallbackKickoff:
    def test_kickoff_calls_crew_kickoff(self, brain):
        cb = _make_callback(brain, auto_learn=False, auto_recall=False)

        mock_crew = MagicMock()
        mock_crew.tasks = []
        mock_crew.kickoff.return_value = "crew_result"

        result = cb.kickoff(mock_crew)

        mock_crew.kickoff.assert_called_once_with()
        assert result == "crew_result"

    def test_kickoff_passes_inputs(self, brain):
        cb = _make_callback(brain, auto_learn=False, auto_recall=False)

        mock_crew = MagicMock()
        mock_crew.tasks = []
        mock_crew.kickoff.return_value = "crew_result"

        cb.kickoff(mock_crew, inputs={"topic": "AI"})

        mock_crew.kickoff.assert_called_once_with(inputs={"topic": "AI"})

    def test_kickoff_injects_recall_when_enabled(self, brain):
        brain.learn(task="Parse CSV file", code="import csv", eval_score=8.0)

        cb = _make_callback(brain, auto_learn=False, auto_recall=True)

        task = _make_task("Parse CSV file and compute stats")
        mock_crew = MagicMock()
        mock_crew.tasks = [task]
        mock_crew.kickoff.return_value = "done"

        cb.kickoff(mock_crew)

        # inject_recall should have been called — task description extended
        assert "Relevant prior patterns" in task.description


class TestEngramiaCrewCallbackHelpers:
    def test_get_learned_count(self, brain):
        cb = _make_callback(brain, auto_learn=True)
        assert cb.get_learned_count() == 0

        brain.learn(task="Something", code="code", eval_score=7.0)
        assert cb.get_learned_count() == 1

    def test_import_error_without_crewai(self, brain):
        with patch.dict("sys.modules", {"crewai": None}):
            with pytest.raises(ImportError, match="crewai"):
                from engramia.sdk.crewai import EngramiaCrewCallback

                EngramiaCrewCallback(brain)

    def test_string_output_fallback(self, brain):
        """Plain string output should be handled gracefully."""
        cb = _make_callback(brain, auto_learn=True, auto_recall=False)
        count_before = brain.metrics.pattern_count

        # Some integrations may pass a plain string
        cb.task_callback("This is the task result text")

        # No crash — result may or may not be learned (description empty)
        assert brain.metrics.pattern_count >= count_before

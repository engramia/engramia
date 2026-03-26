# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for EvalStore."""

import pytest

from engramia.core.eval_store import EvalStore


@pytest.fixture
def store(storage):
    return EvalStore(storage)


def test_save_and_retrieve(store):
    store.save("agent_a", "Parse CSV", {"overall": 8.5, "feedback": "good"})
    examples = store.get_top_examples(limit=5, min_score=7.0)
    assert len(examples) == 1
    assert examples[0]["agent_name"] == "agent_a"


def test_rolling_window(store):
    for i in range(210):
        store.save(f"agent_{i}", f"task {i}", {"overall": 7.0})
    from engramia.core.eval_store import _MAX_EVALS

    raw = store._load_raw()
    assert len(raw) <= _MAX_EVALS


def test_min_score_filter(store):
    store.save("a", "task", {"overall": 9.0})
    store.save("b", "task", {"overall": 5.0})
    examples = store.get_top_examples(min_score=7.0)
    assert all(e["scores"]["overall"] >= 7.0 for e in examples)


def test_get_agent_score_with_similar_task(store):
    store.save("agent_x", "Parse CSV file", {"overall": 8.0})
    score = store.get_agent_score("agent_x", "Parse CSV data")
    assert score == pytest.approx(8.0)


def test_get_agent_score_unrelated_task_returns_none(store):
    store.save("agent_x", "Parse CSV file", {"overall": 8.0})
    score = store.get_agent_score("agent_x", "Deploy Kubernetes cluster")
    assert score is None


def test_average_score(store):
    store.save("a", "t", {"overall": 8.0})
    store.save("b", "t", {"overall": 6.0})
    avg = store.get_average_score()
    assert avg == pytest.approx(7.0)


def test_average_score_empty_returns_none(store):
    assert store.get_average_score() is None


def test_eval_multiplier_high_score(store):
    store.save("agent_good", "Parse CSV", {"overall": 10.0})
    m = store.get_eval_multiplier("agent_good", "Parse CSV data")
    assert m == pytest.approx(1.0)


def test_eval_multiplier_no_eval_returns_neutral(store):
    m = store.get_eval_multiplier("unknown_agent", "any task")
    assert m == pytest.approx(0.75)

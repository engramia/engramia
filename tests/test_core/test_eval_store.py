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


# ---------------------------------------------------------------------------
# Aggregation window (0.6.7+)
# ---------------------------------------------------------------------------


def test_aggregation_latest_matches_legacy_behaviour(store):
    """`aggregation="latest"` returns the most recent record — the
    pre-0.6.7 default behaviour, preserved for callers that opted in."""
    for score in (9.0, 8.0, 7.0, 1.0):
        store.save("a", "task", {"overall": score})
    latest = store.get_agent_score("a", "task", min_jaccard=0.0, aggregation="latest")
    assert latest == pytest.approx(1.0)


def test_aggregation_median_smooths_single_outlier(store):
    """A single noisy refinement should not dominate the
    multiplier once median aggregation is active."""
    # Four consistently-high observations, then one bad one.
    for _ in range(4):
        store.save("a", "task", {"overall": 9.0})
    store.save("a", "task", {"overall": 1.0})
    latest = store.get_agent_score("a", "task", min_jaccard=0.0, aggregation="latest")
    median = store.get_agent_score("a", "task", min_jaccard=0.0, aggregation="median", window=5)
    assert latest == pytest.approx(1.0)
    assert median == pytest.approx(9.0)


def test_aggregation_median_window_caps(store):
    """Window clamps to ``min(window, available)``; a window larger
    than the record count uses every matching record."""
    for score in (2.0, 4.0, 6.0, 8.0):
        store.save("a", "task", {"overall": score})
    median_3 = store.get_agent_score("a", "task", min_jaccard=0.0, aggregation="median", window=3)
    median_100 = store.get_agent_score("a", "task", min_jaccard=0.0, aggregation="median", window=100)
    # Last 3 = [8, 6, 4] → median 6; last 4 = [8, 6, 4, 2] → median 5.
    assert median_3 == pytest.approx(6.0)
    assert median_100 == pytest.approx(5.0)


def test_aggregation_mean(store):
    for score in (4.0, 6.0, 8.0, 10.0):
        store.save("a", "task", {"overall": score})
    mean = store.get_agent_score("a", "task", min_jaccard=0.0, aggregation="mean", window=4)
    assert mean == pytest.approx(7.0)


def test_aggregation_median_single_record(store):
    """Median of a single matching record equals that record — strict
    generalisation of latest behaviour for the N=1 case."""
    store.save("a", "task", {"overall": 6.5})
    median = store.get_agent_score("a", "task", min_jaccard=0.0, aggregation="median")
    assert median == pytest.approx(6.5)


def test_aggregation_ignores_other_agents(store):
    """Median for agent A consults only agent A's records, even if
    agent B's records are interleaved and more recent."""
    store.save("a", "task", {"overall": 9.0})
    store.save("b", "task", {"overall": 1.0})
    store.save("a", "task", {"overall": 8.0})
    store.save("b", "task", {"overall": 1.0})
    median = store.get_agent_score("a", "task", min_jaccard=0.0, aggregation="median", window=5)
    # Agent A records are [9, 8] → median 8.5.
    assert median == pytest.approx(8.5)


def test_eval_multiplier_uses_median_by_default(store):
    """The public ``get_eval_multiplier`` defaults to median since 0.6.7,
    so a single outlier refinement does not tank the recall ranking."""
    for _ in range(4):
        store.save("stable_pattern", "task", {"overall": 9.0})
    store.save("stable_pattern", "task", {"overall": 1.0})  # one noisy outlier
    mult = store.get_eval_multiplier("stable_pattern", "task")
    # Median of [9, 9, 9, 9, 1] = 9 → multiplier 0.5 + 0.5 * 0.9 = 0.95.
    assert mult == pytest.approx(0.95)
    # Explicit latest aggregation reproduces the pre-0.6.7 behaviour.
    mult_latest = store.get_eval_multiplier("stable_pattern", "task", aggregation="latest")
    assert mult_latest == pytest.approx(0.55)


def test_aggregation_unknown_raises(store):
    store.save("a", "task", {"overall": 5.0})
    with pytest.raises(ValueError, match="Unknown aggregation"):
        store.get_agent_score("a", "task", min_jaccard=0.0, aggregation="mode")  # type: ignore[arg-type]

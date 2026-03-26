# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for EvalFeedbackStore."""

import pytest

from engramia.core.eval_feedback import EvalFeedbackStore


@pytest.fixture
def store(storage):
    return EvalFeedbackStore(storage)


def test_record_and_retrieve(store):
    store.record("Add error handling for file I/O operations.")
    store.record("Add error handling for file I/O operations.")
    top = store.get_top(n=5)
    assert len(top) == 1
    assert "error handling" in top[0].lower()


def test_single_occurrence_not_surfaced(store):
    store.record("Unique feedback that appears only once.")
    top = store.get_top()
    assert top == []


def test_similar_feedbacks_are_clustered(store):
    store.record("Add error handling for I/O.")
    store.record("Add better error handling for I/O operations.")
    top = store.get_top()
    # Should be clustered into one pattern (Jaccard > 0.4)
    assert len(top) <= 1


def test_different_feedbacks_not_clustered(store):
    store.record("Improve robustness for edge cases.")
    store.record("Improve robustness for edge cases.")
    store.record("Add type hints to all functions.")
    store.record("Add type hints to all functions.")
    top = store.get_top(n=10)
    assert len(top) == 2


def test_task_type_filter(store):
    store.record("Handle missing values in CSV parsing.")
    store.record("Handle missing values in CSV parsing.")
    store.record("Add retry logic for API calls.")
    store.record("Add retry logic for API calls.")
    csv_feedback = store.get_top(task_type="csv")
    assert all("csv" in f.lower() for f in csv_feedback)


def test_decay_reduces_scores(store):
    store.record("Some recurring feedback")
    store.record("Some recurring feedback")
    patterns_before = store._load_raw()
    score_before = patterns_before[0]["score"]
    store.run_decay()
    patterns_after = store._load_raw()
    score_after = patterns_after[0]["score"]
    assert score_after <= score_before


def test_decay_prunes_low_score(store):
    patterns = [
        {
            "pattern": "stale feedback",
            "count": 2,
            "score": 0.01,
            "last_seen": "2020-01-01T00:00:00",
            "last_decayed": "2020-01-01T00:00:00",
        }
    ]
    store._storage.save("feedback/_list", patterns)
    pruned = store.run_decay()
    assert pruned == 1
    assert store.get_top() == []

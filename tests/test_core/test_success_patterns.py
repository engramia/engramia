# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for SuccessPatternStore (aging and reuse tracking)."""

import time

import pytest

from engramia.core.success_patterns import SuccessPatternStore
from engramia.types import Pattern


def _store_pattern(storage, embeddings, task, score, ts=None):
    """Helper: store a pattern directly into storage."""
    import hashlib

    pattern = Pattern(task=task, design={"code": "pass"}, success_score=score)
    if ts is not None:
        pattern = pattern.model_copy(update={"timestamp": ts})
    key = f"patterns/{hashlib.md5(task.encode()).hexdigest()[:8]}_{int(time.time() * 1000)}"
    storage.save(key, pattern.model_dump())
    embedding = embeddings.embed(task)
    storage.save_embedding(key, embedding)
    return key


@pytest.fixture
def pattern_store(storage):
    return SuccessPatternStore(storage)


def test_aging_decays_score(storage, fake_embeddings, pattern_store):
    old_ts = time.time() - (10 * 7 * 24 * 3600)  # 10 weeks ago
    key = _store_pattern(storage, fake_embeddings, "Parse CSV", 8.0, ts=old_ts)

    pattern_store.run_aging()

    data = storage.load(key)
    if data is not None:
        assert data["success_score"] < 8.0  # score should have decayed


def test_aging_prunes_very_old_patterns(storage, fake_embeddings, pattern_store):
    old_ts = time.time() - (500 * 7 * 24 * 3600)  # ~500 weeks, score will hit 0
    key = _store_pattern(storage, fake_embeddings, "Very old task", 1.0, ts=old_ts)

    pruned = pattern_store.run_aging()

    assert pruned >= 1
    assert storage.load(key) is None


def test_aging_preserves_recent_patterns(storage, fake_embeddings, pattern_store):
    key = _store_pattern(storage, fake_embeddings, "Recent task", 9.0)

    pruned = pattern_store.run_aging()

    assert pruned == 0
    assert storage.load(key) is not None


def test_mark_reused_increments_count(storage, fake_embeddings, pattern_store):
    key = _store_pattern(storage, fake_embeddings, "Task A", 7.0)

    pattern_store.mark_reused(key)

    data = storage.load(key)
    assert data["reuse_count"] == 1


def test_mark_reused_boosts_score(storage, fake_embeddings, pattern_store):
    key = _store_pattern(storage, fake_embeddings, "Task B", 7.0)
    pattern_store.mark_reused(key)
    data = storage.load(key)
    assert data["success_score"] > 7.0


def test_mark_reused_capped_at_10(storage, fake_embeddings, pattern_store):
    key = _store_pattern(storage, fake_embeddings, "Task C", 9.95)
    pattern_store.mark_reused(key)
    data = storage.load(key)
    assert data["success_score"] <= 10.0


def test_mark_reused_missing_key_is_noop(pattern_store):
    pattern_store.mark_reused("patterns/nonexistent")  # should not raise


def test_get_count(storage, fake_embeddings, pattern_store):
    _store_pattern(storage, fake_embeddings, "Task 1", 7.0)
    _store_pattern(storage, fake_embeddings, "Task 2", 8.0)
    assert pattern_store.get_count() == 2


def test_aging_boundary_score_at_threshold(storage, fake_embeddings, pattern_store):
    """A pattern with score just above MIN_SCORE=0.1 should survive one aging cycle."""
    key = _store_pattern(storage, fake_embeddings, "Boundary task", 0.11)
    pruned = pattern_store.run_aging()
    assert pruned == 0
    data = storage.load(key)
    assert data is not None
    assert data["success_score"] <= 0.11


def test_aging_boundary_score_below_threshold_pruned(storage, fake_embeddings, pattern_store):
    """A pattern with score below MIN_SCORE=0.1 after decay should be pruned."""
    one_week = 7 * 24 * 3600
    key = _store_pattern(storage, fake_embeddings, "Low score task", 0.1, ts=time.time() - one_week)
    # 0.1 * 0.98^1 = 0.098 < 0.1 → pruned
    pruned = pattern_store.run_aging()
    assert pruned == 1
    assert storage.load(key) is None


def test_aging_future_timestamp_no_inflation(storage, fake_embeddings, pattern_store):
    """Pattern with a future timestamp should not get an inflated score."""
    key = _store_pattern(storage, fake_embeddings, "Future task", 5.0, ts=time.time() + 10000)
    pruned = pattern_store.run_aging()
    assert pruned == 0
    data = storage.load(key)
    assert data is not None
    assert data["success_score"] <= 5.0


def test_mark_reused_at_max_score_stays_at_10(storage, fake_embeddings, pattern_store):
    """Reuse boost at score=10.0 should not exceed 10.0."""
    key = _store_pattern(storage, fake_embeddings, "Perfect task", 10.0)
    pattern_store.mark_reused(key)
    data = storage.load(key)
    assert data["success_score"] == 10.0

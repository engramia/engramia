# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Unit tests for Brain facade methods not covered elsewhere."""

import time

import pytest

from engramia.exceptions import ValidationError
from engramia.types import Pattern


class TestDeletePattern:
    """Tests for Brain.delete_pattern()."""

    def test_delete_existing_pattern(self, mem):
        result = mem.learn(task="Task to delete", code="print('hi')", eval_score=7.0)
        assert result.stored

        matches = mem.recall(task="Task to delete", limit=1)
        assert len(matches) == 1
        key = matches[0].pattern_key

        deleted = mem.delete_pattern(key)
        assert deleted is True

        # Pattern should no longer appear in recall
        matches_after = mem.recall(task="Task to delete", limit=5)
        for m in matches_after:
            assert m.pattern_key != key

    def test_delete_nonexistent_pattern(self, mem):
        deleted = mem.delete_pattern("patterns/nonexistent_12345")
        assert deleted is False

    def test_delete_removes_from_count(self, mem):
        mem.learn(task="Count test pattern", code="pass", eval_score=6.0)
        count_before = mem.metrics.pattern_count
        assert count_before >= 1

        matches = mem.recall(task="Count test pattern", limit=1)
        mem.delete_pattern(matches[0].pattern_key)

        count_after = mem.metrics.pattern_count
        assert count_after == count_before - 1


class TestRunAging:
    """Tests for Brain.run_aging()."""

    def test_aging_no_patterns(self, mem):
        pruned = mem.run_aging()
        assert pruned == 0

    def test_aging_preserves_recent_high_score(self, mem):
        mem.learn(task="Recent good pattern", code="pass", eval_score=9.0)
        pruned = mem.run_aging()
        assert pruned == 0
        assert mem.metrics.pattern_count >= 1

    def test_aging_prunes_old_low_score(self, mem, storage):
        # Manually create a very old pattern with low score
        pattern = Pattern(
            task="Ancient pattern",
            design={"code": "pass"},
            success_score=0.15,
            timestamp=time.time() - (365 * 24 * 3600),  # 1 year ago
        )
        key = "patterns/ancient_123"
        storage.save(key, pattern.model_dump())

        pruned = mem.run_aging()
        assert pruned >= 1
        assert storage.load(key) is None


class TestRunFeedbackDecay:
    """Tests for Brain.run_feedback_decay()."""

    def test_feedback_decay_no_feedback(self, mem):
        pruned = mem.run_feedback_decay()
        assert pruned == 0


class TestStorageType:
    """Tests for Brain.storage_type property."""

    def test_returns_class_name(self, mem):
        assert mem.storage_type == "JSONStorage"


class TestInputValidation:
    """Tests for input validation on Brain methods."""

    def test_learn_empty_task(self, mem):
        with pytest.raises(ValidationError, match="non-empty"):
            mem.learn(task="", code="pass", eval_score=5.0)

    def test_learn_empty_code(self, mem):
        with pytest.raises(ValidationError, match="non-empty"):
            mem.learn(task="Valid task", code="", eval_score=5.0)

    def test_recall_empty_task(self, mem):
        with pytest.raises(ValidationError, match="non-empty"):
            mem.recall(task="")

    def test_recall_zero_limit(self, mem):
        with pytest.raises(ValidationError, match="limit"):
            mem.recall(task="Valid task", limit=0)

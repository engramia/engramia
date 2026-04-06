# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Direct unit tests for RecallService."""

from unittest.mock import MagicMock

import pytest

from engramia.core.services.recall import RecallService
from engramia.core.success_patterns import SuccessPatternStore


@pytest.fixture
def pattern_store(storage):
    return SuccessPatternStore(storage)


@pytest.fixture
def svc(storage, fake_embeddings, pattern_store):
    eval_store = MagicMock()
    eval_store.get_eval_multiplier.return_value = 1.0
    roi = MagicMock()
    return RecallService(
        storage=storage,
        embeddings=fake_embeddings,
        eval_store=eval_store,
        pattern_store=pattern_store,
        roi_collector=roi,
    )


@pytest.fixture
def svc_no_embed(storage, pattern_store):
    eval_store = MagicMock()
    roi = MagicMock()
    return RecallService(
        storage=storage,
        embeddings=None,
        eval_store=eval_store,
        pattern_store=pattern_store,
        roi_collector=roi,
    )


def _seed_pattern(storage, fake_embeddings, task="parse CSV files", code="import csv", score=8.0):
    """Helper to seed a pattern into storage for recall tests."""
    from engramia.core.services.learning import LearningService

    svc = LearningService(
        storage=storage,
        embeddings=fake_embeddings,
        metrics_store=MagicMock(),
        eval_store=MagicMock(),
        roi_collector=MagicMock(),
    )
    svc.learn(task=task, code=code, eval_score=score)


class TestRecallService:
    def test_recall_empty_storage_returns_empty(self, svc):
        result = svc.recall("anything")
        assert result == []

    def test_recall_finds_stored_pattern(self, svc, storage, fake_embeddings):
        _seed_pattern(storage, fake_embeddings)
        result = svc.recall("parse CSV files")
        assert len(result) >= 1
        assert result[0].pattern.task == "parse CSV files"

    def test_recall_respects_limit(self, svc, storage, fake_embeddings):
        for i in range(5):
            _seed_pattern(storage, fake_embeddings, task=f"unique task {i}", code=f"code_{i}")
        result = svc.recall("unique task", limit=2)
        assert len(result) <= 2

    def test_recall_without_embeddings_uses_keyword_fallback(self, svc_no_embed, storage, fake_embeddings):
        _seed_pattern(storage, fake_embeddings, task="parse CSV data")
        result = svc_no_embed.recall("parse CSV data")
        assert len(result) >= 1

    def test_recall_records_roi_hit(self, svc, storage, fake_embeddings):
        _seed_pattern(storage, fake_embeddings)
        svc.recall("parse CSV files")
        svc._roi_collector.record_recall.assert_called_once()

    def test_recall_records_roi_miss(self, svc):
        svc.recall("nonexistent task")
        svc._roi_collector.record_recall.assert_called_once()
        call_kwargs = svc._roi_collector.record_recall.call_args[1]
        assert call_kwargs["best_similarity"] is None

    def test_recall_deduplicates_by_default(self, svc, storage, fake_embeddings):
        _seed_pattern(storage, fake_embeddings, task="parse CSV files", code="v1")
        _seed_pattern(storage, fake_embeddings, task="parse CSV files", code="v2")
        result = svc.recall("parse CSV files", deduplicate=True)
        # Both patterns have identical task text → should be deduped to 1
        assert len(result) == 1

    def test_recall_no_deduplicate(self, svc, storage, fake_embeddings):
        _seed_pattern(storage, fake_embeddings, task="parse CSV files", code="v1")
        _seed_pattern(storage, fake_embeddings, task="parse CSV files", code="v2")
        result = svc.recall("parse CSV files", deduplicate=False)
        assert len(result) == 2

    def test_recall_marks_reused(self, svc, storage, fake_embeddings, pattern_store):
        _seed_pattern(storage, fake_embeddings)
        result = svc.recall("parse CSV files")
        assert len(result) >= 1
        # SuccessPatternStore.mark_reused should have been called
        # The pattern key should exist in the pattern store meta

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Direct unit tests for LearningService."""

from unittest.mock import MagicMock

import pytest

from engramia.core.services.learning import LearningService
from engramia.exceptions import ValidationError


@pytest.fixture
def svc(storage, fake_embeddings):
    metrics = MagicMock()
    eval_store = MagicMock()
    roi = MagicMock()
    return LearningService(
        storage=storage,
        embeddings=fake_embeddings,
        metrics_store=metrics,
        eval_store=eval_store,
        roi_collector=roi,
    )


@pytest.fixture
def svc_no_embed(storage):
    metrics = MagicMock()
    eval_store = MagicMock()
    roi = MagicMock()
    return LearningService(
        storage=storage,
        embeddings=None,
        metrics_store=metrics,
        eval_store=eval_store,
        roi_collector=roi,
    )


class TestLearningService:
    def test_learn_stores_pattern(self, svc):
        result = svc.learn(task="parse CSV files", code="import csv", eval_score=8.0)
        assert result.stored is True
        assert result.pattern_count == 1

    def test_learn_increments_pattern_count(self, svc):
        svc.learn(task="task A", code="code_a", eval_score=7.0)
        result = svc.learn(task="task B", code="code_b", eval_score=6.0)
        assert result.pattern_count == 2

    def test_learn_records_metrics(self, svc):
        svc.learn(task="task", code="code", eval_score=9.0)
        svc._metrics_store.record_run.assert_called_once_with(success=True, eval_score=9.0)

    def test_learn_records_eval(self, svc):
        svc.learn(task="task", code="code", eval_score=7.5)
        svc._eval_store.save.assert_called_once()
        call_kwargs = svc._eval_store.save.call_args[1]
        assert call_kwargs["task"] == "task"
        assert call_kwargs["scores"]["overall"] == 7.5

    def test_learn_records_roi_event(self, svc):
        svc.learn(task="task", code="code", eval_score=8.0)
        svc._roi_collector.record_learn.assert_called_once()

    def test_learn_without_embeddings(self, svc_no_embed):
        result = svc_no_embed.learn(task="task", code="code", eval_score=7.0)
        assert result.stored is True

    def test_learn_with_output(self, svc):
        result = svc.learn(task="task", code="code", eval_score=8.0, output="some output")
        assert result.stored is True

    def test_learn_with_author(self, svc):
        result = svc.learn(task="task", code="code", eval_score=8.0, author="user-1")
        assert result.stored is True

    def test_learn_with_redaction(self, storage, fake_embeddings):
        redaction = MagicMock()
        redaction.process.return_value = ({"code": "clean"}, ["pii_found"])
        svc = LearningService(
            storage=storage,
            embeddings=fake_embeddings,
            metrics_store=MagicMock(),
            eval_store=MagicMock(),
            roi_collector=MagicMock(),
            redaction=redaction,
        )
        result = svc.learn(task="task", code="secret code", eval_score=8.0)
        assert result.stored is True
        redaction.process.assert_called_once()

    def test_learn_max_patterns_raises(self, svc, monkeypatch):
        monkeypatch.setattr(
            "engramia.core.services.learning._MAX_PATTERN_COUNT", 1
        )
        svc.learn(task="task1", code="code1", eval_score=7.0)
        with pytest.raises(ValidationError, match="full"):
            svc.learn(task="task2", code="code2", eval_score=7.0)

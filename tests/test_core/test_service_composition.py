# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Direct unit tests for CompositionService."""

import json
from unittest.mock import MagicMock

import pytest

from engramia.core.services.composition import CompositionService


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.call.return_value = json.dumps(
        {
            "stages": [
                {
                    "name": "data_loader",
                    "task": "load CSV data from disk",
                    "reads": ["input.csv"],
                    "writes": ["data.json"],
                },
                {
                    "name": "processor",
                    "task": "process the loaded data",
                    "reads": ["data.json"],
                    "writes": ["output.json"],
                },
            ]
        }
    )
    return llm


@pytest.fixture
def svc(mock_llm, storage, fake_embeddings):
    eval_store = MagicMock()
    eval_store.get_eval_multiplier.return_value = 1.0
    return CompositionService(
        llm=mock_llm,
        storage=storage,
        embeddings=fake_embeddings,
        eval_store=eval_store,
    )


@pytest.fixture
def svc_no_embed(mock_llm, storage):
    eval_store = MagicMock()
    eval_store.get_eval_multiplier.return_value = 1.0
    return CompositionService(
        llm=mock_llm,
        storage=storage,
        embeddings=None,
        eval_store=eval_store,
    )


class TestCompositionService:
    def test_compose_returns_pipeline(self, svc):
        pipeline = svc.compose("load and process CSV data")
        assert len(pipeline.stages) == 2
        assert pipeline.stages[0].task == "load CSV data from disk"
        assert pipeline.stages[1].task == "process the loaded data"

    def test_compose_populates_reads_writes(self, svc):
        pipeline = svc.compose("load and process CSV data")
        assert "data.json" in pipeline.stages[0].writes
        assert "data.json" in pipeline.stages[1].reads

    def test_compose_detects_contract_violations(self, mock_llm, storage, fake_embeddings):
        mock_llm.call.return_value = json.dumps(
            {
                "stages": [
                    {
                        "name": "step1",
                        "task": "produce output",
                        "reads": [],
                        "writes": ["a.json"],
                    },
                    {
                        "name": "step2",
                        "task": "consume different input",
                        "reads": ["missing.json"],
                        "writes": ["b.json"],
                    },
                ]
            }
        )
        eval_store = MagicMock()
        eval_store.get_eval_multiplier.return_value = 1.0
        svc = CompositionService(
            llm=mock_llm, storage=storage, embeddings=fake_embeddings, eval_store=eval_store
        )
        pipeline = svc.compose("task with broken chain")
        assert pipeline.valid is False
        assert len(pipeline.contract_errors) > 0

    def test_compose_without_embeddings(self, svc_no_embed):
        pipeline = svc_no_embed.compose("load and process data")
        assert len(pipeline.stages) == 2

    def test_compose_calls_llm(self, svc, mock_llm):
        svc.compose("some task")
        mock_llm.call.assert_called_once()

    def test_compose_single_stage(self, mock_llm, storage, fake_embeddings):
        mock_llm.call.return_value = json.dumps(
            {"stages": [{"name": "solo", "task": "do everything", "reads": [], "writes": ["result.json"]}]}
        )
        eval_store = MagicMock()
        eval_store.get_eval_multiplier.return_value = 1.0
        svc = CompositionService(
            llm=mock_llm, storage=storage, embeddings=fake_embeddings, eval_store=eval_store
        )
        pipeline = svc.compose("simple task")
        assert len(pipeline.stages) == 1
        assert pipeline.valid is True

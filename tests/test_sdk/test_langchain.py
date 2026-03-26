# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for LangChain EngramiaCallback (mocked, no langchain needed)."""

from unittest.mock import MagicMock, patch

import pytest

from engramia.brain import Memory
from engramia.providers.json_storage import JSONStorage
from tests.conftest import FakeEmbeddings


@pytest.fixture
def brain_with_llm(tmp_path):
    storage = JSONStorage(path=tmp_path)
    embeddings = FakeEmbeddings()
    # Use a simple mock LLM
    mock_llm = MagicMock()
    mock_llm.call.return_value = '{"task_alignment": 8, "code_quality": 8, "workspace_usage": 8, "robustness": 8, "overall": 8.0, "feedback": "Good"}'
    return Memory(embeddings=embeddings, storage=storage, llm=mock_llm)


class TestEngramiaCallback:
    """Tests for the LangChain integration callback."""

    def _make_callback(self, brain, **kwargs):
        # Mock langchain_core so import works
        mock_lccore = MagicMock()
        with patch.dict(
            "sys.modules", {"langchain_core": mock_lccore, "langchain_core.callbacks": mock_lccore.callbacks}
        ):
            from engramia.sdk.langchain import EngramiaCallback

            return EngramiaCallback(brain, **kwargs)

    def test_on_chain_start_recalls_context(self, brain_with_llm):
        brain = brain_with_llm
        # Store a pattern first
        brain.learn(task="Parse CSV file", code="import csv", eval_score=8.0)

        callback = self._make_callback(brain, auto_recall=True, auto_learn=False)
        callback.on_chain_start(
            serialized={},
            inputs={"input": "Parse CSV file"},
            run_id="test-run-1",
        )

        context = callback.get_recalled_context("test-run-1")
        assert context is not None
        assert len(context) >= 1
        assert context[0]["task"] == "Parse CSV file"

    def test_on_chain_end_learns(self, brain_with_llm):
        brain = brain_with_llm
        count_before = brain.metrics.pattern_count

        callback = self._make_callback(brain, auto_learn=True, auto_recall=False)
        callback.on_chain_start(
            serialized={},
            inputs={"input": "Generate report"},
            run_id="test-run-2",
        )
        callback.on_chain_end(
            outputs={"output": "Report generated successfully"},
            run_id="test-run-2",
        )

        count_after = brain.metrics.pattern_count
        assert count_after > count_before

    def test_on_chain_error_cleans_up(self, brain_with_llm):
        brain = brain_with_llm
        callback = self._make_callback(brain)
        callback.on_chain_start(
            serialized={},
            inputs={"input": "Will fail"},
            run_id="test-run-3",
        )
        callback.on_chain_error(error=RuntimeError("boom"), run_id="test-run-3")
        # Should not crash and should clean up
        assert callback.get_recalled_context("test-run-3") is None

    def test_disabled_auto_learn(self, brain_with_llm):
        brain = brain_with_llm
        count_before = brain.metrics.pattern_count

        callback = self._make_callback(brain, auto_learn=False, auto_recall=False)
        callback.on_chain_start(
            serialized={},
            inputs={"input": "Test task"},
            run_id="test-run-4",
        )
        callback.on_chain_end(
            outputs={"output": "Done"},
            run_id="test-run-4",
        )

        assert brain.metrics.pattern_count == count_before

    def test_disabled_auto_recall(self, brain_with_llm):
        brain = brain_with_llm
        callback = self._make_callback(brain, auto_recall=False, auto_learn=False)
        callback.on_chain_start(
            serialized={},
            inputs={"input": "Something"},
            run_id="test-run-5",
        )
        # No recalled context since auto_recall is off
        chain_info = callback._active_chains.get("test-run-5", {})
        assert "recalled" not in chain_info

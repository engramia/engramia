# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for AutoGen integration (mocked, no autogen-agentchat needed)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engramia.memory import Memory
from engramia.providers.json_storage import JSONStorage
from tests.conftest import FakeEmbeddings


@pytest.fixture
def mem(tmp_path):
    storage = JSONStorage(path=tmp_path)
    embeddings = FakeEmbeddings()
    mock_llm = MagicMock()
    mock_llm.call.return_value = '{"overall": 8.0, "feedback": "Good"}'
    return Memory(embeddings=embeddings, storage=storage, llm=mock_llm)


def _mock_autogen():
    """Create mock autogen_core module."""
    mock_core = MagicMock()

    # Create real classes for MemoryContent and friends
    class MemoryContent:
        def __init__(self, content="", mime_type="text/plain"):
            self.content = content
            self.mime_type = mime_type

    class MemoryQueryResult:
        def __init__(self, results=None):
            self.results = results or []

    class UpdateContextResult:
        def __init__(self, memories=None):
            self.memories = memories

    class SystemMessage:
        def __init__(self, content=""):
            self.content = content

    mock_core.memory.MemoryContent = MemoryContent
    mock_core.memory.MemoryQueryResult = MemoryQueryResult
    mock_core.memory.UpdateContextResult = UpdateContextResult
    mock_core.models.SystemMessage = SystemMessage

    return {
        "autogen_core": mock_core,
        "autogen_core.memory": mock_core.memory,
        "autogen_core.models": mock_core.models,
    }


def _make_memory(mem, **kwargs):
    with patch.dict("sys.modules", _mock_autogen()):
        from engramia.sdk.autogen import EngramiaMemory

        return EngramiaMemory(mem, **kwargs)


class TestEngramiaMemory:
    @pytest.mark.asyncio
    async def test_update_context_injects_patterns(self, mem):
        mem.learn(task="Parse CSV files", code="import csv", eval_score=8.0)
        ag_mem = _make_memory(mem, recall_limit=3)

        # Mock model_context
        user_msg = MagicMock()
        user_msg.content = "Parse CSV files"
        model_context = AsyncMock()
        model_context.get_messages = AsyncMock(return_value=[user_msg])
        model_context.add_message = AsyncMock()

        with patch.dict("sys.modules", _mock_autogen()):
            result = await ag_mem.update_context(model_context)

        # Should have added a system message
        model_context.add_message.assert_called_once()
        added_msg = model_context.add_message.call_args[0][0]
        assert "Relevant patterns" in added_msg.content
        assert result.memories is not None
        assert len(result.memories.results) >= 1

    @pytest.mark.asyncio
    async def test_update_context_no_patterns(self, mem):
        ag_mem = _make_memory(mem)

        user_msg = MagicMock()
        user_msg.content = "Completely unique xyz task"
        model_context = AsyncMock()
        model_context.get_messages = AsyncMock(return_value=[user_msg])
        model_context.add_message = AsyncMock()

        with patch.dict("sys.modules", _mock_autogen()):
            result = await ag_mem.update_context(model_context)

        model_context.add_message.assert_not_called()
        assert len(result.memories.results) == 0

    @pytest.mark.asyncio
    async def test_update_context_empty_messages(self, mem):
        ag_mem = _make_memory(mem)

        model_context = AsyncMock()
        model_context.get_messages = AsyncMock(return_value=[])

        with patch.dict("sys.modules", _mock_autogen()):
            result = await ag_mem.update_context(model_context)

        assert len(result.memories.results) == 0

    @pytest.mark.asyncio
    async def test_update_context_recall_error(self, mem):
        ag_mem = _make_memory(mem)

        user_msg = MagicMock()
        user_msg.content = "Some task"
        model_context = AsyncMock()
        model_context.get_messages = AsyncMock(return_value=[user_msg])

        with (
            patch.dict("sys.modules", _mock_autogen()),
            patch.object(mem, "recall", side_effect=RuntimeError("down")),
        ):
            result = await ag_mem.update_context(model_context)

        assert len(result.memories.results) == 0

    @pytest.mark.asyncio
    async def test_query_returns_results(self, mem):
        mem.learn(task="Parse CSV files", code="import csv", eval_score=8.0)
        ag_mem = _make_memory(mem)

        with patch.dict("sys.modules", _mock_autogen()):
            result = await ag_mem.query("Parse CSV files")

        assert len(result.results) >= 1

    @pytest.mark.asyncio
    async def test_query_empty(self, mem):
        ag_mem = _make_memory(mem)

        with patch.dict("sys.modules", _mock_autogen()):
            result = await ag_mem.query("unknown")

        assert len(result.results) == 0

    @pytest.mark.asyncio
    async def test_add_learns(self, mem):
        ag_mem = _make_memory(mem)

        count_before = mem.metrics.pattern_count

        content = MagicMock()
        content.content = "Parse CSV files with pandas"

        await ag_mem.add(content)

        assert mem.metrics.pattern_count > count_before

    @pytest.mark.asyncio
    async def test_add_empty_skips(self, mem):
        ag_mem = _make_memory(mem)

        count_before = mem.metrics.pattern_count

        content = MagicMock()
        content.content = None

        await ag_mem.add(content)

        assert mem.metrics.pattern_count == count_before

    @pytest.mark.asyncio
    async def test_clear_is_noop(self, mem):
        mem.learn(task="Parse CSV files", code="import csv", eval_score=8.0)
        ag_mem = _make_memory(mem)

        await ag_mem.clear()

        # Patterns should still exist
        assert mem.metrics.pattern_count > 0

    @pytest.mark.asyncio
    async def test_close_is_noop(self, mem):
        ag_mem = _make_memory(mem)
        await ag_mem.close()  # Should not crash

    def test_name_property(self, mem):
        ag_mem = _make_memory(mem, name="my-engramia")
        assert ag_mem.name == "my-engramia"


class TestLearnFromResult:
    def test_learns_from_task_result(self, mem):
        with patch.dict("sys.modules", _mock_autogen()):
            from engramia.sdk.autogen import learn_from_result

        count_before = mem.metrics.pattern_count

        last_msg = MagicMock()
        last_msg.content = "Here is the CSV parser implementation"
        result = MagicMock()
        result.messages = [MagicMock(), last_msg]

        learn_from_result(mem, task="Build CSV parser", result=result)

        assert mem.metrics.pattern_count > count_before

    def test_empty_result_skips(self, mem):
        with patch.dict("sys.modules", _mock_autogen()):
            from engramia.sdk.autogen import learn_from_result

        count_before = mem.metrics.pattern_count

        result = MagicMock()
        result.messages = []

        learn_from_result(mem, task="Build CSV parser", result=result)

        assert mem.metrics.pattern_count == count_before

    def test_learn_error_does_not_raise(self, mem):
        with patch.dict("sys.modules", _mock_autogen()):
            from engramia.sdk.autogen import learn_from_result

        last_msg = MagicMock()
        last_msg.content = "output"
        result = MagicMock()
        result.messages = [last_msg]

        with patch.object(mem, "learn", side_effect=RuntimeError("boom")):
            learn_from_result(mem, task="task", result=result)
            # Should not raise

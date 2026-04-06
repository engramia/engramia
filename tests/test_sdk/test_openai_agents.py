# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for OpenAI Agents SDK integration (mocked, no openai-agents needed)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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


def _mock_agents_module():
    """Create a mock 'agents' module so imports succeed without openai-agents."""
    return {"agents": MagicMock()}


def _make_hooks(mem, **kwargs):
    with patch.dict("sys.modules", _mock_agents_module()):
        from engramia.sdk.openai_agents import EngramiaRunHooks

        return EngramiaRunHooks(mem, **kwargs)


def _make_instructions(mem, **kwargs):
    with patch.dict("sys.modules", _mock_agents_module()):
        from engramia.sdk.openai_agents import engramia_instructions

        return engramia_instructions(mem, **kwargs)


class TestEngramiaRunHooks:
    @pytest.mark.asyncio
    async def test_on_agent_end_learns(self, mem):
        hooks = _make_hooks(mem, auto_learn=True)
        agent = MagicMock()
        agent.name = "coder"
        context = MagicMock()
        context.input = "Parse CSV files"

        count_before = mem.metrics.pattern_count

        await hooks.on_agent_start(context, agent)
        await hooks.on_agent_end(context, agent, "import csv\nwith open('data.csv') as f: ...")

        assert mem.metrics.pattern_count > count_before

    @pytest.mark.asyncio
    async def test_on_agent_end_disabled_auto_learn(self, mem):
        hooks = _make_hooks(mem, auto_learn=False)
        agent = MagicMock()
        agent.name = "coder"
        context = MagicMock()
        context.input = "Parse CSV files"

        count_before = mem.metrics.pattern_count

        await hooks.on_agent_start(context, agent)
        await hooks.on_agent_end(context, agent, "output text")

        assert mem.metrics.pattern_count == count_before

    @pytest.mark.asyncio
    async def test_on_agent_end_no_task_captured(self, mem):
        hooks = _make_hooks(mem, auto_learn=True)
        agent = MagicMock()
        agent.name = "coder"
        context = MagicMock()
        context.input = None
        context.context = None

        count_before = mem.metrics.pattern_count
        await hooks.on_agent_end(context, agent, "output text")
        assert mem.metrics.pattern_count == count_before

    @pytest.mark.asyncio
    async def test_on_agent_end_none_output(self, mem):
        hooks = _make_hooks(mem, auto_learn=True)
        agent = MagicMock()
        agent.name = "coder"
        context = MagicMock()
        context.input = "Some task"

        await hooks.on_agent_start(context, agent)
        await hooks.on_agent_end(context, agent, None)
        # Should not crash

    @pytest.mark.asyncio
    async def test_on_llm_start_captures_task_from_input_items(self, mem):
        hooks = _make_hooks(mem, auto_learn=True)
        agent = MagicMock()
        agent.name = "coder"
        context = MagicMock()
        context.input = None
        context.context = None

        input_items = [{"role": "user", "content": "Build a web scraper"}]
        await hooks.on_llm_start(context, agent, "system prompt", input_items)

        assert hooks._agent_tasks.get("coder") == "Build a web scraper"

    @pytest.mark.asyncio
    async def test_task_extracted_from_context_dict(self, mem):
        hooks = _make_hooks(mem, auto_learn=True)
        agent = MagicMock()
        agent.name = "coder"
        context = MagicMock()
        context.input = None
        context.context = {"task": "Build a parser"}

        await hooks.on_agent_start(context, agent)
        assert hooks._agent_tasks.get("coder") == "Build a parser"

    @pytest.mark.asyncio
    async def test_task_extracted_from_context_string(self, mem):
        hooks = _make_hooks(mem, auto_learn=True)
        agent = MagicMock()
        agent.name = "coder"
        context = MagicMock()
        context.input = None
        context.context = "Build a parser"

        await hooks.on_agent_start(context, agent)
        assert hooks._agent_tasks.get("coder") == "Build a parser"

    @pytest.mark.asyncio
    async def test_noop_hooks_do_not_crash(self, mem):
        hooks = _make_hooks(mem)
        agent = MagicMock()
        context = MagicMock()

        await hooks.on_tool_start(context, agent, MagicMock())
        await hooks.on_tool_end(context, agent, MagicMock(), "result")
        await hooks.on_handoff(context, agent, agent)
        await hooks.on_llm_end(context, agent, MagicMock())


class TestEngramiaInstructions:
    @pytest.mark.asyncio
    async def test_instructions_without_patterns(self, mem):
        fn = _make_instructions(mem, base="You are a coder.", recall_limit=3)
        context = MagicMock()
        context.input = "Brand new unique task xyz"
        context.context = None

        result = await fn(context, MagicMock())
        assert result == "You are a coder."

    @pytest.mark.asyncio
    async def test_instructions_with_recalled_patterns(self, mem):
        mem.learn(task="Parse CSV files", code="import csv", eval_score=8.0)

        fn = _make_instructions(mem, base="You are a coder.", recall_limit=3)
        context = MagicMock()
        context.input = "Parse CSV files"
        context.context = None

        result = await fn(context, MagicMock())
        assert "You are a coder." in result
        assert "Relevant patterns" in result

    @pytest.mark.asyncio
    async def test_instructions_no_base(self, mem):
        mem.learn(task="Parse CSV files", code="import csv", eval_score=8.0)

        fn = _make_instructions(mem, base="", recall_limit=3)
        context = MagicMock()
        context.input = "Parse CSV files"
        context.context = None

        result = await fn(context, MagicMock())
        assert "Relevant patterns" in result

    @pytest.mark.asyncio
    async def test_instructions_no_task(self, mem):
        fn = _make_instructions(mem, base="You are a coder.", recall_limit=3)
        context = MagicMock()
        context.input = None
        context.context = None

        result = await fn(context, MagicMock())
        assert result == "You are a coder."

    @pytest.mark.asyncio
    async def test_instructions_recall_error_returns_base(self, mem):
        fn = _make_instructions(mem, base="Base prompt.", recall_limit=3)
        context = MagicMock()
        context.input = "Some task"
        context.context = None

        with patch.object(mem, "recall", side_effect=RuntimeError("API down")):
            result = await fn(context, MagicMock())

        assert result == "Base prompt."

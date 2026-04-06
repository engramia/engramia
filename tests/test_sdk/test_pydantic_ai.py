# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for Pydantic AI integration (mocked, no pydantic-ai needed)."""

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


def _mock_pydantic_ai():
    """Create mock pydantic_ai module."""
    mock = MagicMock()
    # Create message types for before_model_request tests
    mock.messages = MagicMock()
    return {"pydantic_ai": mock, "pydantic_ai.messages": mock.messages}


def _make_capability(mem, **kwargs):
    with patch.dict("sys.modules", _mock_pydantic_ai()):
        from engramia.sdk.pydantic_ai import EngramiaCapability

        return EngramiaCapability(mem, **kwargs)


class TestEngramiaCapability:
    @pytest.mark.asyncio
    async def test_before_run_recalls_patterns(self, mem):
        mem.learn(task="Parse CSV files", code="import csv", eval_score=8.0)
        cap = _make_capability(mem, auto_recall=True)

        ctx = MagicMock()
        ctx.prompt = "Parse CSV files"
        ctx.deps = None

        await cap.before_run(ctx)

        assert cap._recalled_context != ""
        assert "Relevant patterns" in cap._recalled_context

    @pytest.mark.asyncio
    async def test_before_run_no_patterns(self, mem):
        cap = _make_capability(mem, auto_recall=True)

        ctx = MagicMock()
        ctx.prompt = "Completely unique never seen task xyz"
        ctx.deps = None

        await cap.before_run(ctx)

        assert cap._recalled_context == ""

    @pytest.mark.asyncio
    async def test_before_run_disabled(self, mem):
        mem.learn(task="Parse CSV files", code="import csv", eval_score=8.0)
        cap = _make_capability(mem, auto_recall=False)

        ctx = MagicMock()
        ctx.prompt = "Parse CSV files"
        ctx.deps = None

        await cap.before_run(ctx)

        assert cap._recalled_context == ""

    @pytest.mark.asyncio
    async def test_after_run_learns(self, mem):
        cap = _make_capability(mem, auto_learn=True)
        cap._current_task = "Parse CSV files"

        result = MagicMock()
        result.output = "import csv\nwith open('data.csv') as f: ..."

        count_before = mem.metrics.pattern_count

        ctx = MagicMock()
        returned = await cap.after_run(ctx, result=result)

        assert mem.metrics.pattern_count > count_before
        assert returned is result

    @pytest.mark.asyncio
    async def test_after_run_disabled(self, mem):
        cap = _make_capability(mem, auto_learn=False)
        cap._current_task = "Parse CSV files"

        result = MagicMock()
        result.output = "some output"

        count_before = mem.metrics.pattern_count

        ctx = MagicMock()
        await cap.after_run(ctx, result=result)

        assert mem.metrics.pattern_count == count_before

    @pytest.mark.asyncio
    async def test_after_run_no_task(self, mem):
        cap = _make_capability(mem, auto_learn=True)
        # No current_task set

        result = MagicMock()
        result.output = "some output"

        count_before = mem.metrics.pattern_count

        ctx = MagicMock()
        await cap.after_run(ctx, result=result)

        assert mem.metrics.pattern_count == count_before

    @pytest.mark.asyncio
    async def test_after_run_clears_state(self, mem):
        cap = _make_capability(mem, auto_learn=True)
        cap._current_task = "Some task"
        cap._recalled_context = "Some context"

        result = MagicMock()
        result.output = "output"

        ctx = MagicMock()
        await cap.after_run(ctx, result=result)

        assert cap._current_task == ""
        assert cap._recalled_context == ""

    @pytest.mark.asyncio
    async def test_for_run_returns_fresh_instance(self, mem):
        cap = _make_capability(mem, auto_learn=True, recall_limit=5)
        cap._current_task = "stale task"

        ctx = MagicMock()
        with patch.dict("sys.modules", _mock_pydantic_ai()):
            fresh = await cap.for_run(ctx)

        assert fresh is not cap
        assert fresh._current_task == ""
        assert fresh._recall_limit == 5
        assert fresh._auto_learn is True

    @pytest.mark.asyncio
    async def test_task_from_deps_dict(self, mem):
        cap = _make_capability(mem, auto_recall=True)

        ctx = MagicMock()
        ctx.prompt = None
        ctx.deps = {"task": "Build a web scraper"}
        ctx.messages = None

        await cap.before_run(ctx)

        assert cap._current_task == "Build a web scraper"

    @pytest.mark.asyncio
    async def test_task_from_deps_string(self, mem):
        cap = _make_capability(mem, auto_recall=True)

        ctx = MagicMock()
        ctx.prompt = None
        ctx.deps = "Build a parser"
        ctx.messages = None

        await cap.before_run(ctx)

        assert cap._current_task == "Build a parser"


class TestEngramiaSystemPrompt:
    def test_with_patterns(self, mem):
        mem.learn(task="Parse CSV files", code="import csv", eval_score=8.0)

        with patch.dict("sys.modules", _mock_pydantic_ai()):
            from engramia.sdk.pydantic_ai import engramia_system_prompt

            ctx = MagicMock()
            ctx.prompt = "Parse CSV files"
            ctx.deps = None
            result = engramia_system_prompt(mem, ctx, base="You are a coder.")

        assert "You are a coder." in result
        assert "Relevant patterns" in result

    def test_without_patterns(self, mem):
        with patch.dict("sys.modules", _mock_pydantic_ai()):
            from engramia.sdk.pydantic_ai import engramia_system_prompt

            ctx = MagicMock()
            ctx.prompt = "Unique task"
            ctx.deps = None
            result = engramia_system_prompt(mem, ctx, base="Base.")

        assert result == "Base."

    def test_recall_error_returns_base(self, mem):
        with patch.dict("sys.modules", _mock_pydantic_ai()):
            from engramia.sdk.pydantic_ai import engramia_system_prompt

            ctx = MagicMock()
            ctx.prompt = "Task"
            ctx.deps = None

            with patch.object(mem, "recall", side_effect=RuntimeError("down")):
                result = engramia_system_prompt(mem, ctx, base="Fallback.")

        assert result == "Fallback."

    def test_no_task_returns_base(self, mem):
        with patch.dict("sys.modules", _mock_pydantic_ai()):
            from engramia.sdk.pydantic_ai import engramia_system_prompt

            ctx = MagicMock()
            ctx.prompt = None
            ctx.deps = None
            ctx.messages = None
            result = engramia_system_prompt(mem, ctx, base="Base.")

        assert result == "Base."

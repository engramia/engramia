# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for Anthropic Agent SDK integration (mocked, no claude-agent-sdk needed)."""

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


def _mock_claude_sdk():
    """Create mock claude_agent_sdk module so imports succeed."""
    mock = MagicMock()
    mock.ClaudeAgentOptions = type("ClaudeAgentOptions", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)})
    mock.HookMatcher = MagicMock()

    class _ResultMessage:
        pass

    mock.ResultMessage = _ResultMessage
    return {"claude_agent_sdk": mock}, _ResultMessage


class TestRecallSystemPrompt:
    def test_recall_with_stored_patterns(self, mem):
        mem.learn(task="Parse CSV files", code="import csv", eval_score=8.0)
        mods, _ = _mock_claude_sdk()

        with patch.dict("sys.modules", mods):
            from engramia.sdk.anthropic_agents import recall_system_prompt

            result = recall_system_prompt(mem, task="Parse CSV files", base="You are a coder.")

        assert "You are a coder." in result
        assert "Relevant patterns" in result
        assert "Parse CSV" in result

    def test_recall_without_patterns(self, mem):
        mods, _ = _mock_claude_sdk()

        with patch.dict("sys.modules", mods):
            from engramia.sdk.anthropic_agents import recall_system_prompt

            result = recall_system_prompt(mem, task="Brand new task", base="Base prompt.")

        assert result == "Base prompt."

    def test_recall_empty_base(self, mem):
        mem.learn(task="Parse CSV files", code="import csv", eval_score=8.0)
        mods, _ = _mock_claude_sdk()

        with patch.dict("sys.modules", mods):
            from engramia.sdk.anthropic_agents import recall_system_prompt

            result = recall_system_prompt(mem, task="Parse CSV files", base="")

        assert "Relevant patterns" in result

    def test_recall_error_returns_base(self, mem):
        mods, _ = _mock_claude_sdk()

        with patch.dict("sys.modules", mods):
            from engramia.sdk.anthropic_agents import recall_system_prompt

            with patch.object(mem, "recall", side_effect=RuntimeError("API down")):
                result = recall_system_prompt(mem, task="anything", base="Fallback.")

        assert result == "Fallback."


class TestEngramiaQuery:
    @pytest.mark.asyncio
    async def test_query_recalls_and_yields_messages(self, mem):
        mem.learn(task="Parse CSV files", code="import csv", eval_score=8.0)

        mods, ResultMessage = _mock_claude_sdk()

        # Create a ResultMessage instance
        result_msg = ResultMessage()
        result_msg.result = "Here is the CSV parser code"

        async def mock_query(prompt, options):
            yield MagicMock()  # SystemMessage
            yield MagicMock()  # AssistantMessage
            yield result_msg  # ResultMessage

        mods["claude_agent_sdk"].query = mock_query

        with patch.dict("sys.modules", mods):
            from engramia.sdk.anthropic_agents import engramia_query

            messages = []
            async for msg in engramia_query(
                mem,
                prompt="Parse CSV files",
                auto_learn=True,
                min_score=7.0,
            ):
                messages.append(msg)

        assert len(messages) == 3

    @pytest.mark.asyncio
    async def test_query_without_auto_learn(self, mem):
        mods, _ = _mock_claude_sdk()

        async def mock_query(prompt, options):
            yield MagicMock()

        mods["claude_agent_sdk"].query = mock_query
        count_before = mem.metrics.pattern_count

        with patch.dict("sys.modules", mods):
            from engramia.sdk.anthropic_agents import engramia_query

            async for _ in engramia_query(mem, prompt="test", auto_learn=False):
                pass

        assert mem.metrics.pattern_count == count_before

    @pytest.mark.asyncio
    async def test_query_with_custom_options(self, mem):
        mods, _ = _mock_claude_sdk()
        captured_options = []

        async def mock_query(prompt, options):
            captured_options.append(options)
            yield MagicMock()

        mods["claude_agent_sdk"].query = mock_query

        with patch.dict("sys.modules", mods):
            from engramia.sdk.anthropic_agents import engramia_query

            async for _ in engramia_query(mem, prompt="test", auto_learn=False):
                pass

        assert len(captured_options) == 1


class TestEngramiaHooks:
    def test_hooks_returns_dict_with_post_tool_use(self, mem):
        mods, _ = _mock_claude_sdk()

        with patch.dict("sys.modules", mods):
            from engramia.sdk.anthropic_agents import engramia_hooks

            hooks = engramia_hooks(mem)

        assert "PostToolUse" in hooks
        assert isinstance(hooks["PostToolUse"], list)
        assert len(hooks["PostToolUse"]) == 1

    def test_hooks_disabled_auto_learn(self, mem):
        mods, _ = _mock_claude_sdk()

        with patch.dict("sys.modules", mods):
            from engramia.sdk.anthropic_agents import engramia_hooks

            hooks = engramia_hooks(mem, auto_learn=False)

        # Hooks should still be returned even if auto_learn is off
        assert "PostToolUse" in hooks

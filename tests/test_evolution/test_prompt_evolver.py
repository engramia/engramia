"""Tests for PromptEvolver."""

import json
from unittest.mock import MagicMock

import pytest

from agent_brain.core.eval_feedback import EvalFeedbackStore
from agent_brain.evolution.prompt_evolver import PromptEvolver
from agent_brain.providers.json_storage import JSONStorage


@pytest.fixture
def feedback_store(storage):
    return EvalFeedbackStore(storage)


class FakeLLM:
    def __init__(self, response: str):
        self._response = response

    def call(self, prompt, system=None, role="default"):
        return self._response


class TestPromptEvolver:
    """Tests for prompt evolution engine."""

    def test_no_issues_returns_original(self, feedback_store):
        llm = FakeLLM("{}")
        evolver = PromptEvolver(llm, feedback_store)

        result = evolver.evolve("coder", "You are a coder.")
        assert result.improved_prompt == "You are a coder."
        assert result.accepted is False
        assert result.reason == "no_issues"

    def test_generates_improved_prompt(self, feedback_store):
        # Record recurring feedback so there are issues to address
        for _ in range(3):
            feedback_store.record("Always add error handling for file I/O")
        for _ in range(2):
            feedback_store.record("Validate input before processing")

        llm_response = json.dumps({
            "improved_prompt": "You are a coder. Always handle file I/O errors. Validate inputs.",
            "changes": ["Added file I/O error handling", "Added input validation"],
        })
        llm = FakeLLM(llm_response)
        evolver = PromptEvolver(llm, feedback_store)

        result = evolver.evolve("coder", "You are a coder.")
        assert result.accepted is True
        assert "error handling" in result.improved_prompt.lower() or "file I/O" in result.improved_prompt
        assert len(result.changes) == 2
        assert len(result.issues_addressed) >= 1

    def test_llm_failure_returns_original(self, feedback_store):
        # Record feedback so evolve actually calls LLM
        for _ in range(3):
            feedback_store.record("Some recurring issue")

        llm = FakeLLM("This is not JSON")
        evolver = PromptEvolver(llm, feedback_store)

        result = evolver.evolve("coder", "Original prompt.")
        assert result.improved_prompt == "Original prompt."
        assert result.accepted is False
        assert "llm_error" in result.reason

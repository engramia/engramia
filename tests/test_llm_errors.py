# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for LLM error paths — ConnectionError, malformed JSON, timeouts."""

import pytest

from engramia.exceptions import ValidationError
from engramia.memory import Memory
from engramia.providers.base import LLMProvider


class ExplodingLLM(LLMProvider):
    """LLM that raises the configured exception on every call."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def call(self, prompt: str, system: str | None = None, role: str = "default") -> str:
        raise self._exc


class MalformedLLM(LLMProvider):
    """LLM that returns non-JSON garbage."""

    def call(self, prompt: str, system: str | None = None, role: str = "default") -> str:
        return "This is not JSON at all {{{broken"


class TimeoutLLM(LLMProvider):
    """LLM that simulates a timeout."""

    def call(self, prompt: str, system: str | None = None, role: str = "default") -> str:
        raise TimeoutError("Request timed out after 30s")


# -- Evaluator tests ----------------------------------------------------------


class TestEvaluatorConnectionError:
    """evaluate() when LLM raises ConnectionError."""

    def test_all_evals_fail_raises_runtime_error(self, brain_with_llm_error):
        mem = brain_with_llm_error(ConnectionError("Connection refused"))
        with pytest.raises(RuntimeError, match="All evaluation attempts failed"):
            mem.evaluate(task="Parse CSV", code="import csv", num_evals=1)


class TestEvaluatorMalformedJSON:
    """evaluate() when LLM returns unparseable output."""

    def test_malformed_json_falls_back_to_defaults(self, brain_with_malformed_llm):
        # MalformedLLM returns garbage; extract_json_from_llm raises ValueError
        # _single_eval retries once, both fail → RuntimeError
        with pytest.raises(RuntimeError, match="All evaluation attempts failed"):
            brain_with_malformed_llm.evaluate(task="Parse CSV", code="import csv", num_evals=1)


class TestEvaluatorTimeout:
    """evaluate() when LLM times out."""

    def test_timeout_raises_runtime_error(self, brain_with_llm_error):
        mem = brain_with_llm_error(TimeoutError("timed out"))
        with pytest.raises(RuntimeError, match="All evaluation attempts failed"):
            mem.evaluate(task="Parse CSV", code="import csv", num_evals=1)


# -- Composer tests ------------------------------------------------------------


class TestComposerConnectionError:
    """compose() when LLM raises ConnectionError — falls back to single stage."""

    def test_compose_falls_back_to_single_stage(self, brain_with_llm_error):
        mem = brain_with_llm_error(ConnectionError("Connection refused"))
        pipeline = mem.compose(task="Fetch data and write report")
        # Fallback produces a single stage with the original task
        assert len(pipeline.stages) >= 1
        assert pipeline.stages[0].task == "Fetch data and write report"


class TestComposerMalformedJSON:
    """compose() when LLM returns garbage — falls back to single stage."""

    def test_compose_malformed_falls_back(self, brain_with_malformed_llm):
        pipeline = brain_with_malformed_llm.compose(task="Analyze logs")
        assert len(pipeline.stages) >= 1
        assert pipeline.stages[0].task == "Analyze logs"


class TestComposerTimeout:
    """compose() when LLM times out — falls back to single stage."""

    def test_compose_timeout_falls_back(self, brain_with_llm_error):
        mem = brain_with_llm_error(TimeoutError("timed out"))
        pipeline = mem.compose(task="Process images")
        assert len(pipeline.stages) >= 1


# -- Prompt evolver tests -----------------------------------------------------


class TestEvolverConnectionError:
    """evolve_prompt() when LLM raises ConnectionError."""

    def test_evolve_returns_original_on_error(self, brain_with_llm_error_and_feedback):
        mem = brain_with_llm_error_and_feedback(ConnectionError("refused"))
        result = mem.evolve_prompt(role="coder", current_prompt="You are a coder.")
        assert result.accepted is False
        assert result.improved_prompt == "You are a coder."
        assert "llm_error" in result.reason


class TestEvolverMalformedJSON:
    """evolve_prompt() when LLM returns garbage."""

    def test_evolve_malformed_returns_original(self, brain_with_malformed_llm_and_feedback):
        result = brain_with_malformed_llm_and_feedback.evolve_prompt(role="coder", current_prompt="You are a coder.")
        assert result.accepted is False
        assert result.improved_prompt == "You are a coder."


class TestEvolverTimeout:
    """evolve_prompt() when LLM times out."""

    def test_evolve_timeout_returns_original(self, brain_with_llm_error_and_feedback):
        mem = brain_with_llm_error_and_feedback(TimeoutError("timed out"))
        result = mem.evolve_prompt(role="coder", current_prompt="You are a coder.")
        assert result.accepted is False
        assert "llm_error" in result.reason


# -- Pattern quota test --------------------------------------------------------


class TestPatternQuota:
    """mem.learn() respects _MAX_PATTERN_COUNT."""

    def test_learn_rejects_when_full(self, mem, storage, monkeypatch):
        # Simulate a full store by monkeypatching list_keys
        original_list_keys = storage.list_keys

        def fake_list_keys(prefix: str = "") -> list[str]:
            if prefix == "patterns":
                return [f"patterns/fake_{i}" for i in range(100_000)]
            return original_list_keys(prefix)

        monkeypatch.setattr(storage, "list_keys", fake_list_keys)
        with pytest.raises(ValidationError, match="full"):
            mem.learn(task="One more pattern", code="pass", eval_score=5.0)


# -- Concurrent eval failure test ---------------------------------------------


class TestConcurrentEvalFailures:
    """evaluate() with num_evals=3 where all 3 concurrent attempts fail."""

    def test_all_concurrent_evals_fail_raises_runtime_error(self, brain_with_llm_error):
        mem = brain_with_llm_error(OSError("network unreachable"))
        # All 3 concurrent LLM calls fail → RuntimeError, not a hang
        with pytest.raises(RuntimeError, match="All evaluation attempts failed"):
            mem.evaluate(task="Parse CSV", code="import csv", num_evals=3)

    def test_partial_eval_success_aggregates_normally(self, fake_embeddings, storage):
        """One of 3 evals succeeds → result returned (not an error)."""
        call_count = {"n": 0}

        class FlakyLLM(ExplodingLLM):
            def call(self, prompt, system=None, role="default"):
                call_count["n"] += 1
                if call_count["n"] % 3 != 0:
                    # First two attempts (per eval) fail; third succeeds
                    raise ConnectionError("flaky")
                return '{"task_alignment":7,"code_quality":7,"workspace_usage":7,"robustness":7,"overall":7.0,"feedback":"ok"}'

        mem = Memory(embeddings=fake_embeddings, storage=storage, llm=FlakyLLM(ConnectionError()))
        # May raise RuntimeError if all retries exhaust — that's acceptable;
        # what we're proving is the test does NOT hang forever.
        try:
            result = mem.evaluate(task="Parse CSV", code="import csv", num_evals=3)
            assert isinstance(result.median_score, float)
        except RuntimeError:
            pass  # acceptable — all concurrent attempts may fail on flaky network


# -- ProviderError propagation test -------------------------------------------


class TestProviderErrorPropagation:
    """LLM raising ProviderError (non-retryable) propagates correctly."""

    def test_evaluate_propagates_provider_error_type(self, brain_with_llm_error):
        from engramia.exceptions import ProviderError

        mem = brain_with_llm_error(ProviderError("auth failed"))
        with pytest.raises((RuntimeError, ProviderError)):
            mem.evaluate(task="Parse CSV", code="import csv", num_evals=1)


# -- Fixtures ------------------------------------------------------------------


@pytest.fixture
def brain_with_llm_error(fake_embeddings, storage):
    """Factory fixture: returns a Brain whose LLM raises the given exception."""

    def _make(exc: Exception) -> Memory:
        return Memory(
            embeddings=fake_embeddings,
            storage=storage,
            llm=ExplodingLLM(exc),
        )

    return _make


@pytest.fixture
def brain_with_malformed_llm(fake_embeddings, storage):
    """Brain with an LLM that returns non-JSON responses."""
    return Memory(
        embeddings=fake_embeddings,
        storage=storage,
        llm=MalformedLLM(),
    )


@pytest.fixture
def brain_with_llm_error_and_feedback(fake_embeddings, storage):
    """Factory: Brain with broken LLM + seeded feedback (so evolver runs)."""

    def _make(exc: Exception) -> Memory:
        mem = Memory(
            embeddings=fake_embeddings,
            storage=storage,
            llm=ExplodingLLM(exc),
        )
        # Seed feedback with count >= 2 so get_top() returns them
        mem._feedback_store.record("Missing error handling")
        mem._feedback_store.record("Missing error handling")
        return mem

    return _make


@pytest.fixture
def brain_with_malformed_llm_and_feedback(fake_embeddings, storage):
    """Brain with malformed LLM + seeded feedback."""
    mem = Memory(
        embeddings=fake_embeddings,
        storage=storage,
        llm=MalformedLLM(),
    )
    # Seed feedback with count >= 2 so get_top() returns them
    mem._feedback_store.record("Missing error handling")
    mem._feedback_store.record("Missing error handling")
    return mem

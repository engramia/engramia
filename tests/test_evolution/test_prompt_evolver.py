# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for PromptEvolver."""

import json

import pytest

from engramia.core.eval_feedback import EvalFeedbackStore
from engramia.evolution.prompt_evolver import PromptEvolver


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

        llm_response = json.dumps(
            {
                "improved_prompt": "You are a coder. Always handle file I/O errors. Validate inputs.",
                "changes": ["Added file I/O error handling", "Added input validation"],
            }
        )
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


# ---------------------------------------------------------------------------
# evolve_with_eval — A/B evaluation flow
# ---------------------------------------------------------------------------


class RoleAwareFakeLLM:
    """Fake LLM that returns different responses based on the 'role' parameter.

    Routes architect (evolve) calls separately from eval calls so we can
    control the A/B evaluation flow precisely.
    """

    def __init__(self, evolve_response: str, eval_response: str) -> None:
        self._evolve = evolve_response
        self._eval = eval_response

    def call(self, prompt: str, system: str | None = None, role: str = "default") -> str:
        if role == "architect":
            return self._evolve
        return self._eval


def _make_eval_json(score: float) -> str:
    return json.dumps(
        {
            "task_alignment": int(score),
            "code_quality": int(score),
            "workspace_usage": int(score),
            "robustness": int(score),
            "overall": score,
            "feedback": "test feedback",
        }
    )


class TestEvolveWithEval:
    def test_no_issues_returns_early_without_running_evals(self, feedback_store):
        """When there are no feedback issues, evolve_with_eval() must not call the evaluator."""
        llm = FakeLLM("{}")
        evolver = PromptEvolver(llm, feedback_store)

        result = evolver.evolve_with_eval(
            role="coder",
            current_prompt="Original prompt.",
            test_task="Parse CSV",
            test_code="import csv",
        )

        assert result.accepted is False
        assert result.reason == "no_issues"
        assert result.improved_prompt == "Original prompt."
        assert result.current_score is None
        assert result.candidate_score is None

    def test_candidate_same_as_current_returns_early(self, feedback_store):
        """When the improved prompt equals the current prompt, skip A/B evaluation."""
        for _ in range(3):
            feedback_store.record("Add error handling")

        current = "You are a coder."
        evolve_resp = json.dumps({"improved_prompt": current, "changes": []})
        llm = FakeLLM(evolve_resp)
        evolver = PromptEvolver(llm, feedback_store)

        result = evolver.evolve_with_eval(
            role="coder",
            current_prompt=current,
            test_task="Task",
            test_code="pass",
        )

        # evolve() accepted=True but prompt unchanged → early return, no A/B scores set
        assert result.improved_prompt == current
        assert result.current_score is None

    def test_accepted_when_candidate_within_tolerance(self, feedback_store):
        """Candidate is accepted when candidate_score >= current_score - TOLERANCE (0.2)."""
        for _ in range(3):
            feedback_store.record("Add error handling")

        evolve_resp = json.dumps(
            {"improved_prompt": "Better prompt with error handling.", "changes": ["Added error handling"]}
        )
        # Both current and candidate score 8.0 → 8.0 >= 8.0 - 0.2 → accepted
        llm = RoleAwareFakeLLM(evolve_resp, _make_eval_json(8.0))
        evolver = PromptEvolver(llm, feedback_store)

        result = evolver.evolve_with_eval(
            role="coder",
            current_prompt="Original prompt.",
            test_task="Parse CSV",
            test_code="import csv",
            num_evals=1,
        )

        assert result.accepted is True
        assert result.improved_prompt == "Better prompt with error handling."
        assert isinstance(result.current_score, float)
        assert isinstance(result.candidate_score, float)
        assert "accepted" in result.reason

    def test_rejected_when_candidate_below_tolerance(self, feedback_store):
        """Candidate is rejected when candidate_score < current_score - TOLERANCE."""
        for _ in range(3):
            feedback_store.record("Add error handling")

        evolve_resp = json.dumps({"improved_prompt": "Worse prompt.", "changes": ["Something changed"]})

        # current = 9.0, candidate = 5.0 → 5.0 < 9.0 - 0.2 = 8.8 → rejected
        # evolve_with_eval makes 4 non-architect calls:
        # 1) code gen (current prompt), 2) eval (current), 3) code gen (candidate), 4) eval (candidate)
        non_architect_responses = iter(
            [
                "import csv",  # code gen with current prompt
                _make_eval_json(9.0),  # eval of current code → score 9.0
                "import csv",  # code gen with candidate prompt
                _make_eval_json(5.0),  # eval of candidate code → score 5.0
            ]
        )

        class SequentialLLM:
            def call(self_, prompt: str, system: str | None = None, role: str = "default") -> str:
                if role == "architect":
                    return evolve_resp
                return next(non_architect_responses)

        evolver = PromptEvolver(SequentialLLM(), feedback_store)

        result = evolver.evolve_with_eval(
            role="coder",
            current_prompt="Original prompt.",
            test_task="Parse CSV",
            test_code="import csv",
            num_evals=1,
        )

        assert result.accepted is False
        assert result.improved_prompt == "Original prompt."  # reverted to current
        assert "rejected" in result.reason

    def test_current_eval_failure_returns_eval_error(self, feedback_store):
        """When the current-prompt evaluation fails, return with eval_error reason."""
        for _ in range(3):
            feedback_store.record("Add error handling")

        evolve_resp = json.dumps({"improved_prompt": "Better prompt.", "changes": ["x"]})

        class EvalFailingLLM:
            def call(self_, prompt: str, system: str | None = None, role: str = "default") -> str:
                if role == "architect":
                    return evolve_resp
                raise RuntimeError("LLM temporarily unavailable")

        evolver = PromptEvolver(EvalFailingLLM(), feedback_store)

        result = evolver.evolve_with_eval(
            role="coder",
            current_prompt="Original prompt.",
            test_task="Task",
            test_code="pass",
            num_evals=1,
        )

        assert result.accepted is False
        assert "eval_error" in result.reason

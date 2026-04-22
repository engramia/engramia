# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""EvaluationService — multi-evaluator scoring for agent code."""

import hashlib
import logging

from engramia.core.eval_feedback import EvalFeedbackStore
from engramia.core.eval_store import EvalStore
from engramia.eval.evaluator import MultiEvaluator
from engramia.providers.base import LLMProvider
from engramia.telemetry import tracing as _tracing
from engramia.types import EvalResult

_log = logging.getLogger(__name__)

_MAX_NUM_EVALS = 10


class EvaluationService:
    """Runs multi-evaluator LLM scoring on agent code.

    Args:
        llm: LLM provider used for evaluations.
        eval_store: Shared EvalStore instance.
        feedback_store: Shared EvalFeedbackStore instance.
    """

    def __init__(
        self,
        llm: LLMProvider,
        eval_store: EvalStore,
        feedback_store: EvalFeedbackStore,
    ) -> None:
        self._llm = llm
        self._eval_store = eval_store
        self._feedback_store = feedback_store

    @_tracing.traced("memory.evaluate")
    def evaluate(
        self,
        task: str,
        code: str,
        output: str | None = None,
        num_evals: int = 3,
        *,
        pattern_key: str | None = None,
    ) -> EvalResult:
        """Run multi-evaluator scoring.

        Runs num_evals independent LLM evaluations concurrently, aggregates
        by median, and records results for future quality-weighted recall.

        Args:
            task: Task the code is meant to solve.
            code: Agent source code.
            output: Optional captured output.
            num_evals: Number of independent evaluator runs.
            pattern_key: When set, the eval record's ``agent_name`` is the
                caller-supplied pattern key — so the result flows into
                ``eval_weighted`` recall for that specific pattern. When
                ``None`` (default, pre-0.6.8 behaviour), the agent name
                falls back to a SHA-256 digest of the code, which keeps
                ``evaluate()`` usable on free-floating code that is not
                tied to a stored pattern.

        Returns:
            EvalResult with median score, variance, and feedback.
        """
        num_evals = min(num_evals, _MAX_NUM_EVALS)
        evaluator = MultiEvaluator(self._llm, num_evals=num_evals)
        result = evaluator.evaluate(task, code, output)

        agent_key = pattern_key if pattern_key is not None else hashlib.sha256(code.encode()).hexdigest()[:12]
        self._eval_store.save(
            agent_name=agent_key,
            task=task,
            scores={
                "overall": result.median_score,
                "task_alignment": result.scores[0].task_alignment if result.scores else 0,
                "code_quality": result.scores[0].code_quality if result.scores else 0,
                "workspace_usage": result.scores[0].workspace_usage if result.scores else 0,
                "robustness": result.scores[0].robustness if result.scores else 0,
                "feedback": result.feedback,
            },
        )
        if result.feedback:
            self._feedback_store.record(result.feedback)

        return result

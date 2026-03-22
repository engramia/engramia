"""Multi-evaluator scoring engine.

Runs N independent LLM evaluations concurrently, aggregates by median,
and detects high variance (evaluators disagree) and adversarial outputs
(hardcoded results).

Evaluation dimensions:
- task_alignment:   Does the code solve the stated task?
- code_quality:     Clarity, correctness, style.
- workspace_usage:  Correct reads/writes/tool usage.
- robustness:       Error handling, edge cases.
- overall:          Weighted composite (0–10).
"""

import json
import re
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent_brain.providers.base import LLMProvider
from agent_brain.types import EvalResult, EvalScore

_DEFAULT_NUM_EVALS = 3
_HIGH_VARIANCE_THRESHOLD = 1.5
_ADVERSARIAL_MIN_LEN = 10  # minimum output length to run adversarial check

_EVAL_SYSTEM = """\
You are an expert code evaluator for AI agents.
Evaluate the provided code against the given task on four dimensions (0–10 scale).
Respond ONLY with valid JSON matching this exact schema — no extra text:

{
  "task_alignment": <int 0-10>,
  "code_quality": <int 0-10>,
  "workspace_usage": <int 0-10>,
  "robustness": <int 0-10>,
  "overall": <float 0-10>,
  "feedback": "<one concrete, actionable improvement suggestion>"
}"""

_EVAL_USER = """\
Task: {task}

Code:
```python
{code}
```

Output:
{output}

Evaluate the code against the task. Be strict — scores above 8 require excellent handling of edge cases."""


def _extract_json(text: str) -> dict:
    """Extract a JSON object from LLM response text.

    Handles raw JSON, markdown code blocks, and embedded JSON objects.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Markdown code block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # Any JSON object in the text
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"No valid JSON found in LLM response: {text[:300]}")


def _parse_score(raw: dict) -> EvalScore:
    def _clamp(v, lo=0.0, hi=10.0) -> float:
        return max(lo, min(hi, float(v)))

    return EvalScore(
        task_alignment=_clamp(raw.get("task_alignment", 5)),
        code_quality=_clamp(raw.get("code_quality", 5)),
        workspace_usage=_clamp(raw.get("workspace_usage", 5)),
        robustness=_clamp(raw.get("robustness", 5)),
        overall=_clamp(raw.get("overall", 5)),
        feedback=str(raw.get("feedback", "")),
    )


def _check_adversarial(code: str, output: str | None) -> bool:
    """Return True if the output appears verbatim in the code (hardcoded result)."""
    if not output:
        return False
    snippet = output.strip()[:_ADVERSARIAL_MIN_LEN]
    if len(snippet) < _ADVERSARIAL_MIN_LEN:
        return False
    return snippet in code


class MultiEvaluator:
    """Runs N concurrent LLM evaluations and aggregates by median.

    Args:
        llm: LLM provider to use for evaluations.
        num_evals: Number of independent evaluation runs (default 3).
    """

    def __init__(self, llm: LLMProvider, num_evals: int = _DEFAULT_NUM_EVALS) -> None:
        self._llm = llm
        self._num_evals = num_evals

    def evaluate(
        self,
        task: str,
        code: str,
        output: str | None = None,
    ) -> EvalResult:
        """Run multi-evaluator scoring.

        Runs num_evals LLM calls concurrently, takes the median overall score,
        and returns feedback from the lowest-scoring run (most critical feedback).

        Args:
            task: Natural language task description.
            code: Agent source code being evaluated.
            output: Optional captured stdout/output from running the code.

        Returns:
            EvalResult with aggregated scores, variance, and feedback.

        Raises:
            RuntimeError: If all evaluation attempts fail.
        """
        prompt = _EVAL_USER.format(task=task, code=code, output=output or "(no output captured)")

        scores: list[EvalScore] = []
        with ThreadPoolExecutor(max_workers=self._num_evals) as executor:
            futures = [executor.submit(self._single_eval, prompt) for _ in range(self._num_evals)]
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    scores.append(result)

        if not scores:
            raise RuntimeError("All evaluation attempts failed — check LLM provider.")

        overall_scores = [s.overall for s in scores]
        median = statistics.median(overall_scores)
        variance = max(overall_scores) - min(overall_scores)

        # Feedback from the lowest-scoring run: most critical perspective
        worst = min(scores, key=lambda s: s.overall)

        return EvalResult(
            scores=scores,
            median_score=round(median, 2),
            variance=round(variance, 2),
            high_variance=variance > _HIGH_VARIANCE_THRESHOLD,
            feedback=worst.feedback,
            adversarial_detected=_check_adversarial(code, output),
        )

    def _single_eval(self, prompt: str) -> EvalScore | None:
        """Run one evaluation. Returns None on failure (retried by caller)."""
        for attempt in range(2):
            try:
                raw_text = self._llm.call(prompt=prompt, system=_EVAL_SYSTEM, role="eval")
                raw = _extract_json(raw_text)
                return _parse_score(raw)
            except Exception:
                if attempt == 1:
                    return None
        return None

"""Public data models for Agent Brain.

All types are Pydantic v2 models. These form the public API contract —
other modules import from here, never define their own ad-hoc dicts.
"""

import time
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Thresholds (single source of truth)
# ---------------------------------------------------------------------------

SIMILARITY_DUPLICATE = 0.92   # use agent as-is
SIMILARITY_ADAPT = 0.70       # adapt to new task
# below SIMILARITY_ADAPT → "fresh" (generate new agent)

JACCARD_DEDUP_THRESHOLD = 0.7  # task word overlap to consider "same task" in recall grouping


# ---------------------------------------------------------------------------
# Learn / Recall
# ---------------------------------------------------------------------------

class Pattern(BaseModel):
    """A successful agent design stored in Brain memory.

    Args:
        task: Natural language description of what the agent does.
        design: Free-form dict with agent design (code, files, reads/writes, ...).
        success_score: Quality score, 0.0–10.0. Subject to time-based decay.
        reuse_count: Number of times this pattern was reused. Boosts ranking.
        timestamp: Unix timestamp of when the pattern was stored.
    """

    task: str
    design: dict[str, Any]
    success_score: float = Field(default=1.0, ge=0.0, le=10.0)
    reuse_count: int = Field(default=0, ge=0)
    timestamp: float = Field(default_factory=time.time)


class Match(BaseModel):
    """A pattern returned from brain.recall().

    Args:
        pattern: The matched Pattern.
        similarity: Cosine similarity of task embeddings, 0.0–1.0.
        reuse_tier: How to treat the match.
            - "duplicate": similarity >= 0.92, use as-is.
            - "adapt": similarity 0.70–0.92, adapt prompt/code for new task.
            - "fresh": similarity < 0.70, generate new agent (pattern is context only).
        pattern_key: Storage key for this pattern. Pass to ``brain.delete_pattern()``
            to permanently remove it.
    """

    pattern: Pattern
    similarity: float = Field(ge=0.0, le=1.0)
    reuse_tier: Literal["duplicate", "adapt", "fresh"]
    pattern_key: str = ""


class LearnResult(BaseModel):
    """Confirmation returned from brain.learn().

    Args:
        stored: True if pattern was saved (may be False if score below threshold).
        pattern_count: Total number of patterns currently in storage.
    """

    stored: bool
    pattern_count: int


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------

class EvalScore(BaseModel):
    """Scores from a single LLM evaluator run.

    Args:
        task_alignment: How well the agent solves the given task (0–10).
        code_quality: Code clarity, correctness, style (0–10).
        workspace_usage: Correct use of reads/writes/tools (0–10).
        robustness: Error handling, edge cases (0–10).
        overall: Weighted overall score (0–10).
        feedback: Short text explanation of the main quality issues.
    """

    task_alignment: float = Field(ge=0.0, le=10.0)
    code_quality: float = Field(ge=0.0, le=10.0)
    workspace_usage: float = Field(ge=0.0, le=10.0)
    robustness: float = Field(ge=0.0, le=10.0)
    overall: float = Field(ge=0.0, le=10.0)
    feedback: str


class EvalResult(BaseModel):
    """Aggregated result from brain.evaluate() (N independent LLM evaluators).

    Args:
        scores: Individual scores from each evaluator run.
        median_score: Median of overall scores — robust against outliers.
        variance: Max–min spread across overall scores.
        high_variance: True if variance > 1.5 (evaluators disagree — review manually).
        feedback: Feedback string from the run closest to the median score.
        adversarial_detected: True if a hardcoded/trivial output was detected.
    """

    scores: list[EvalScore]
    median_score: float = Field(ge=0.0, le=10.0)
    variance: float = Field(ge=0.0)
    high_variance: bool
    feedback: str
    adversarial_detected: bool = False


# ---------------------------------------------------------------------------
# Compose
# ---------------------------------------------------------------------------

class PipelineStage(BaseModel):
    """One stage in a composed multi-agent pipeline.

    Args:
        name: Agent name / identifier.
        task: What this stage is responsible for.
        design: Agent design dict (same structure as Pattern.design).
        reads: Files/resources this stage reads from the workspace.
        writes: Files/resources this stage writes to the workspace.
        reuse_tier: How the pattern was matched (duplicate / adapt / fresh).
        similarity: Cosine similarity of the matched pattern.
    """

    name: str
    task: str
    design: dict[str, Any]
    reads: list[str] = Field(default_factory=list)
    writes: list[str] = Field(default_factory=list)
    reuse_tier: Literal["duplicate", "adapt", "fresh"]
    similarity: float = Field(ge=0.0, le=1.0)


class Pipeline(BaseModel):
    """A multi-agent pipeline returned from brain.compose().

    Args:
        task: The original high-level task passed to compose().
        stages: Ordered list of pipeline stages.
        valid: True if contract validation passed (reads/writes chain is consistent).
        contract_errors: List of data-flow violations found during validation.
    """

    task: str
    stages: list[PipelineStage]
    valid: bool
    contract_errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Feedback & Evolution
# ---------------------------------------------------------------------------

class FeedbackPattern(BaseModel):
    """A recurring quality issue tracked by Brain.

    Args:
        pattern: Normalized feedback text (used as injection into prompts).
        count: How many times this issue appeared across evaluations.
        score: Weighted relevance score (decays 10%/week).
        last_seen: When this feedback was last recorded.
    """

    pattern: str
    count: int = Field(ge=0)
    score: float = Field(ge=0.0)
    last_seen: datetime


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class Metrics(BaseModel):
    """Aggregate runtime statistics from brain.metrics.

    Args:
        runs: Total number of runs recorded.
        success: Successful runs.
        failures: Failed runs.
        pipeline_reuse: Runs where an existing pattern was reused.
        success_rate: success / runs (0.0 if runs == 0).
        pattern_count: Number of patterns currently in storage.
        avg_eval_score: Average overall eval score across all stored evals, or None.
    """

    runs: int = 0
    success: int = 0
    failures: int = 0
    pipeline_reuse: int = 0
    success_rate: float = 0.0
    pattern_count: int = 0
    avg_eval_score: float | None = None


# ---------------------------------------------------------------------------
# Model Routing
# ---------------------------------------------------------------------------

class ModelRoutingRecommendation(BaseModel):
    """A data-driven model routing recommendation.

    Args:
        role: Agent role this recommendation applies to (e.g. "coder", "eval").
        task_type: Task category (e.g. "csv", "api", "generic").
        recommended_model: Model ID to use.
        recommended_provider: Provider name ("openai" / "anthropic").
        avg_eval_score: Average eval score achieved by this model on this role/task.
        avg_cost_usd: Average cost per call in USD.
        savings_pct: Percentage cost saving vs the most expensive option.
    """

    role: str
    task_type: str
    recommended_model: str
    recommended_provider: str
    avg_eval_score: float
    avg_cost_usd: float
    savings_pct: float = 0.0

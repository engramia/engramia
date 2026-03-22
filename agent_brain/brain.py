"""Brain — the central facade for Agent Brain.

Users interact exclusively with this class. All internal modules
(storage, embeddings, LLM, eval, reuse, metrics) are wired here.
"""

import hashlib
import time
from typing import Any, Literal

from agent_brain.core.eval_feedback import EvalFeedbackStore
from agent_brain.core.eval_store import EvalStore
from agent_brain.core.metrics import MetricsStore
from agent_brain.core.success_patterns import SuccessPatternStore
from agent_brain.eval.evaluator import MultiEvaluator
from agent_brain.providers.base import EmbeddingProvider, LLMProvider, StorageBackend
from agent_brain.reuse.composer import PipelineComposer
from agent_brain.reuse.matcher import PatternMatcher
from agent_brain.types import (
    JACCARD_DEDUP_THRESHOLD,
    EvalResult,
    LearnResult,
    Match,
    Metrics,
    Pattern,
    Pipeline,
    SIMILARITY_ADAPT,
    SIMILARITY_DUPLICATE,
)

_PATTERNS_PREFIX = "patterns"
_DEDUP_FETCH_MULTIPLIER = 3


def _reuse_tier(similarity: float) -> Literal["duplicate", "adapt", "fresh"]:
    if similarity >= SIMILARITY_DUPLICATE:
        return "duplicate"
    if similarity >= SIMILARITY_ADAPT:
        return "adapt"
    return "fresh"


def _jaccard(a: str, b: str) -> float:
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _deduplicate_matches(matches: list[Match]) -> list[Match]:
    """Keep only the best-scoring pattern per task group (Jaccard > threshold)."""
    groups: list[Match] = []
    for match in matches:
        merged = False
        for i, best in enumerate(groups):
            if _jaccard(match.pattern.task, best.pattern.task) > JACCARD_DEDUP_THRESHOLD:
                if match.pattern.success_score > best.pattern.success_score:
                    groups[i] = match
                merged = True
                break
        if not merged:
            groups.append(match)
    groups.sort(key=lambda m: m.similarity, reverse=True)
    return groups


class Brain:
    """Self-learning memory layer for AI agent frameworks.

    .. code-block:: python

        from agent_brain import Brain
        from agent_brain.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage

        brain = Brain(
            llm=OpenAIProvider(model="gpt-4.1"),
            embeddings=OpenAIEmbeddings(),
            storage=JSONStorage(path="./brain_data"),
        )

    Args:
        embeddings: Embedding provider for semantic search.
        storage: Storage backend for persistence and vector search.
        llm: LLM provider for evaluate(), compose(), and evolve_prompt().
            May be ``None`` if you only need learn() and recall().
    """

    def __init__(
        self,
        embeddings: EmbeddingProvider,
        storage: StorageBackend,
        llm: LLMProvider | None = None,
    ) -> None:
        self._llm = llm
        self._embeddings = embeddings
        self._storage = storage

        # Internal stores — all share the same storage backend via key prefixes
        self._metrics_store = MetricsStore(storage)
        self._eval_store = EvalStore(storage)
        self._feedback_store = EvalFeedbackStore(storage)
        self._pattern_store = SuccessPatternStore(storage)

    # ------------------------------------------------------------------
    # Learn
    # ------------------------------------------------------------------

    def learn(
        self,
        task: str,
        code: str,
        eval_score: float,
        output: str | None = None,
    ) -> LearnResult:
        """Record a successful agent run and store it as a reusable pattern.

        Args:
            task: Natural language description of what the agent does.
            code: Agent source code (the solution).
            eval_score: Quality score 0.0–10.0 (from evaluate() or manual).
            output: Optional captured stdout/output for reference.

        Returns:
            LearnResult with ``stored=True`` and the current pattern count.
        """
        design: dict[str, Any] = {"code": code}
        if output is not None:
            design["output"] = output

        pattern = Pattern(task=task, design=design, success_score=eval_score)
        key = self._pattern_key(task)

        self._storage.save(key, pattern.model_dump())
        embedding = self._embeddings.embed(task)
        self._storage.save_embedding(key, embedding)

        # Record in eval store for quality-weighted recall
        self._eval_store.save(
            agent_name=key,
            task=task,
            scores={"overall": eval_score, "feedback": ""},
        )
        self._metrics_store.record_run(success=True, eval_score=eval_score)

        pattern_count = len(self._storage.list_keys(prefix=_PATTERNS_PREFIX))
        return LearnResult(stored=True, pattern_count=pattern_count)

    # ------------------------------------------------------------------
    # Recall
    # ------------------------------------------------------------------

    def recall(
        self,
        task: str,
        limit: int = 5,
        deduplicate: bool = True,
        eval_weighted: bool = True,
    ) -> list[Match]:
        """Find stored patterns most relevant to *task*.

        Args:
            task: Natural language description of the new task.
            limit: Maximum number of matches to return.
            deduplicate: Group near-duplicate tasks and return only the
                top-scoring pattern per group (default True).
            eval_weighted: Boost patterns with high eval scores (default True).

        Returns:
            List of Match objects sorted by (weighted) similarity descending.
        """
        fetch_limit = limit * _DEDUP_FETCH_MULTIPLIER if deduplicate else limit

        if eval_weighted:
            matcher = PatternMatcher(self._storage, self._embeddings, self._eval_store)
            matches = matcher.find(task, limit=fetch_limit)
        else:
            embedding = self._embeddings.embed(task)
            results = self._storage.search_similar(embedding, limit=fetch_limit, prefix=_PATTERNS_PREFIX)
            matches = []
            for key, similarity in results:
                data = self._storage.load(key)
                if data is None:
                    continue
                pattern = Pattern.model_validate(data)
                matches.append(Match(pattern=pattern, similarity=min(similarity, 1.0), reuse_tier=_reuse_tier(similarity)))

        if deduplicate:
            matches = _deduplicate_matches(matches)

        return matches[:limit]

    # ------------------------------------------------------------------
    # Evaluate
    # ------------------------------------------------------------------

    def evaluate(
        self,
        task: str,
        code: str,
        output: str | None = None,
        num_evals: int = 3,
    ) -> EvalResult:
        """Run multi-evaluator scoring on agent code.

        Runs *num_evals* independent LLM evaluations concurrently, aggregates
        by median, and records results for future quality-weighted recall.

        Args:
            task: Task the code is meant to solve.
            code: Agent source code.
            output: Optional captured output from running the code.
            num_evals: Number of independent evaluator runs.

        Returns:
            EvalResult with median score, variance, and feedback.

        Raises:
            RuntimeError: If no LLM provider was configured.
        """
        self._require_llm("evaluate")
        evaluator = MultiEvaluator(self._llm, num_evals=num_evals)  # type: ignore[arg-type]
        result = evaluator.evaluate(task, code, output)

        agent_key = hashlib.md5(code.encode()).hexdigest()[:12]
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

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self, task: str) -> Pipeline:
        """Build a multi-agent pipeline for *task* from stored patterns.

        Decomposes the task into stages via LLM, finds best matching pattern
        per stage, and validates data-flow contracts.

        Args:
            task: High-level task description.

        Returns:
            Pipeline with stages and contract validation result.

        Raises:
            RuntimeError: If no LLM provider was configured.
        """
        self._require_llm("compose")
        matcher = PatternMatcher(self._storage, self._embeddings, self._eval_store)
        composer = PipelineComposer(self._llm, matcher)  # type: ignore[arg-type]
        return composer.compose(task)

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    def get_feedback(self, task_type: str | None = None, limit: int = 5) -> list[str]:
        """Return top recurring quality issues for prompt injection.

        Args:
            task_type: Optional filter (e.g. "csv", "api"). Only feedback
                patterns containing this string are returned.
            limit: Maximum number of feedback strings.

        Returns:
            List of feedback strings sorted by relevance (score × count).
        """
        return self._feedback_store.get_top(n=limit, task_type=task_type)

    # ------------------------------------------------------------------
    # Aging
    # ------------------------------------------------------------------

    def run_aging(self) -> int:
        """Apply time-based decay to all stored patterns.

        Patterns decay at 2% per week. Those below score 0.1 are pruned.
        Call periodically (e.g. weekly) to keep the pattern store fresh.

        Returns:
            Number of patterns pruned.
        """
        return self._pattern_store.run_aging()

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @property
    def metrics(self) -> Metrics:
        """Aggregate run statistics."""
        m = self._metrics_store.get()
        m.pattern_count = self._pattern_store.get_count()
        m.avg_eval_score = self._eval_store.get_average_score()
        return m

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_llm(self, method: str) -> None:
        if self._llm is None:
            raise RuntimeError(
                f"Brain.{method}() requires an LLM provider. "
                "Pass llm=OpenAIProvider(...) or llm=AnthropicProvider(...) to Brain()."
            )

    @staticmethod
    def _pattern_key(task: str) -> str:
        task_hash = hashlib.md5(task.encode()).hexdigest()[:8]
        ts = int(time.time() * 1000)
        return f"{_PATTERNS_PREFIX}/{task_hash}_{ts}"

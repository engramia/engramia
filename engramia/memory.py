# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Memory — thin facade for Engramia.

Users interact exclusively with this class. All business logic lives in
the service layer (engramia.core.services.*). Memory wires the shared
stores and providers together and delegates each public operation to the
appropriate service.
"""

import hashlib
import logging
import time
from typing import Any

from engramia._util import PATTERNS_PREFIX
from engramia.analytics.collector import ROICollector
from engramia.core.eval_feedback import EvalFeedbackStore
from engramia.core.eval_store import EvalStore
from engramia.core.metrics import MetricsStore
from engramia.core.services import (
    CompositionService,
    EvaluationService,
    LearningService,
    RecallService,
)
from engramia.core.skill_registry import SkillRegistry
from engramia.core.success_patterns import SuccessPatternStore
from engramia.evolution.failure_cluster import FailureCluster, FailureClusterer
from engramia.evolution.prompt_evolver import EvolutionResult, PromptEvolver
from engramia.exceptions import ProviderError, ValidationError
from engramia.governance.redaction import RedactionPipeline
from engramia.providers.base import EmbeddingProvider, LLMProvider, StorageBackend
from engramia.types import (
    DataClassification,
    EvalResult,
    LearnResult,
    Match,
    Metrics,
    Pattern,
    Pipeline,
)

_MAX_EVAL_SCORE = 10.0
_MIN_EVAL_SCORE = 0.0

# Re-exported for backward compatibility (used by tests and external tooling)
from engramia.core.services.evaluation import _MAX_NUM_EVALS  # noqa: E402

_log = logging.getLogger(__name__)

_MAX_TASK_LEN = 10_000
_MAX_CODE_LEN = 500_000  # 500 KB


class Memory:
    """Reusable execution memory and evaluation infrastructure for AI agent frameworks.

    .. code-block:: python

        from engramia import Memory
        from engramia.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage

        mem = Memory(
            llm=OpenAIProvider(model="gpt-4.1"),
            embeddings=OpenAIEmbeddings(),
            storage=JSONStorage(path="./engramia_data"),
        )

    Args:
        embeddings: Embedding provider for semantic search.
        storage: Storage backend for persistence and vector search.
        llm: LLM provider for evaluate(), compose(), and evolve_prompt().
            May be ``None`` if you only need learn() and recall().
        redaction: Optional redaction pipeline for PII/secrets stripping.
    """

    def __init__(
        self,
        embeddings: EmbeddingProvider,
        storage: StorageBackend,
        llm: LLMProvider | None = None,
        redaction: RedactionPipeline | None = None,
    ) -> None:
        self._llm = llm
        self._embeddings = embeddings
        self._storage = storage
        self._redaction = redaction

        # Shared stores — all share the same storage backend via key prefixes
        self._metrics_store = MetricsStore(storage)
        self._eval_store = EvalStore(storage)
        self._feedback_store = EvalFeedbackStore(storage)
        self._pattern_store = SuccessPatternStore(storage)
        self._skill_registry = SkillRegistry(storage)
        self._roi_collector = ROICollector(storage)

        # Service layer — each service owns one domain
        self._learning = LearningService(
            storage=storage,
            embeddings=embeddings,
            metrics_store=self._metrics_store,
            eval_store=self._eval_store,
            roi_collector=self._roi_collector,
            redaction=redaction,
        )
        self._recall_svc = RecallService(
            storage=storage,
            embeddings=embeddings,
            eval_store=self._eval_store,
            pattern_store=self._pattern_store,
            roi_collector=self._roi_collector,
        )

    # ------------------------------------------------------------------
    # Provider accessors (read-only, used by deep health check)
    # ------------------------------------------------------------------

    @property
    def storage(self) -> StorageBackend:
        """The active storage backend."""
        return self._storage

    @property
    def llm(self) -> LLMProvider | None:
        """The active LLM provider, or None if not configured."""
        return self._llm

    @property
    def embeddings(self) -> EmbeddingProvider:
        """The active embedding provider."""
        return self._embeddings

    # ------------------------------------------------------------------
    # Learn
    # ------------------------------------------------------------------

    def learn(
        self,
        task: str,
        code: str,
        eval_score: float,
        output: str | None = None,
        *,
        run_id: str | None = None,
        classification: str = DataClassification.INTERNAL,
        source: str = "api",
        author: str | None = None,
    ) -> LearnResult:
        """Record a successful agent run and store it as a reusable pattern.

        Args:
            task: Natural language description of what the agent does.
            code: Agent source code (the solution).
            eval_score: Quality score 0.0-10.0 (from evaluate() or manual).
            output: Optional captured stdout/output for reference.
            run_id: Optional caller-supplied correlation ID for this agent run.
            classification: Data sensitivity level (``'public'``, ``'internal'``,
                ``'confidential'``). Defaults to ``'internal'``.
            source: Origin of the pattern (``'api'``, ``'sdk'``, ``'cli'``, ``'import'``).
            author: Identifier of the creator (key_id, service name, or email).

        Returns:
            LearnResult with ``stored=True`` and the current pattern count.
        """
        self._validate_task(task)
        self._validate_code(code)
        self._validate_eval_score(eval_score)
        return self._learning.learn(
            task=task,
            code=code,
            eval_score=eval_score,
            output=output,
            run_id=run_id,
            classification=classification,
            source=source,
            author=author,
        )

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
        self._validate_task(task)
        self._validate_limit(limit)
        return self._recall_svc.recall(
            task=task,
            limit=limit,
            deduplicate=deduplicate,
            eval_weighted=eval_weighted,
        )

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
        self._validate_task(task)
        self._validate_code(code)
        self._require_llm("evaluate")
        svc = EvaluationService(
            llm=self._llm,  # type: ignore[arg-type]
            eval_store=self._eval_store,
            feedback_store=self._feedback_store,
        )
        return svc.evaluate(task=task, code=code, output=output, num_evals=num_evals)

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
        self._validate_task(task)
        self._require_llm("compose")
        svc = CompositionService(
            llm=self._llm,  # type: ignore[arg-type]
            storage=self._storage,
            embeddings=self._embeddings,
            eval_store=self._eval_store,
        )
        return svc.compose(task)

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
            List of feedback strings sorted by relevance (score * count).
        """
        return self._feedback_store.get_top(n=limit, task_type=task_type)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_pattern(self, pattern_key: str) -> bool:
        """Permanently delete a stored pattern by its key.

        Removes the pattern data, its embedding, and its eval history.
        Useful for removing low-quality or irrelevant patterns manually.

        Args:
            pattern_key: Full storage key (e.g. ``"patterns/abc12345_1234567890"``).
                Keys are returned in the ``pattern.key`` field of Match objects
                (not currently exposed on Pattern — use ``recall()`` to find keys).

        Returns:
            ``True`` if the pattern existed and was deleted, ``False`` if not found.

        Raises:
            ValidationError: If pattern_key does not start with the patterns/ prefix.
        """
        if not pattern_key.startswith(f"{PATTERNS_PREFIX}/") or ".." in pattern_key:
            raise ValidationError(f"pattern_key must start with '{PATTERNS_PREFIX}/' and must not contain '..'")
        if self._storage.load(pattern_key) is None:
            return False
        self._storage.delete(pattern_key)
        _log.info("Deleted pattern %r", pattern_key)
        return True

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

    def run_feedback_decay(self) -> int:
        """Apply time-based decay to feedback patterns.

        Feedback decays at 10% per week. Those below score 0.15 are pruned.

        Returns:
            Number of feedback patterns pruned.
        """
        return self._feedback_store.run_decay()

    # ------------------------------------------------------------------
    # Prompt Evolution (Phase 3)
    # ------------------------------------------------------------------

    def evolve_prompt(
        self,
        role: str,
        current_prompt: str,
        num_issues: int = 5,
    ) -> EvolutionResult:
        """Generate an improved prompt based on recurring feedback.

        Analyzes top failure patterns and produces a candidate prompt
        that addresses them. Does NOT run A/B evaluation.

        Args:
            role: Agent role (e.g. "coder", "eval", "architect").
            current_prompt: The current system prompt to improve.
            num_issues: Number of top issues to address.

        Returns:
            EvolutionResult with the candidate prompt and changes.

        Raises:
            RuntimeError: If no LLM provider was configured.
        """
        self._require_llm("evolve_prompt")
        evolver = PromptEvolver(self._llm, self._feedback_store)  # type: ignore[arg-type]
        return evolver.evolve(role, current_prompt, num_issues=num_issues)

    # ------------------------------------------------------------------
    # Failure Analysis (Phase 3)
    # ------------------------------------------------------------------

    def analyze_failures(self, min_count: int = 1) -> list[FailureCluster]:
        """Cluster failure patterns to identify systemic issues.

        Args:
            min_count: Minimum occurrence count for inclusion.

        Returns:
            List of FailureCluster objects sorted by total count descending.
        """
        clusterer = FailureClusterer(self._feedback_store)
        return clusterer.analyze(min_count=min_count)

    # ------------------------------------------------------------------
    # Skill Registry (Phase 3)
    # ------------------------------------------------------------------

    def register_skills(self, pattern_key: str, skills: list[str]) -> None:
        """Associate skill tags with a stored pattern.

        Args:
            pattern_key: Storage key of the pattern.
            skills: List of skill tags (e.g. ["csv_parsing", "statistics"]).
        """
        self._skill_registry.register(pattern_key, skills)

    def find_by_skills(
        self,
        required: list[str],
        match_all: bool = True,
    ) -> list[Match]:
        """Find patterns that have the required skills.

        Args:
            required: Skill tags to search for.
            match_all: If True, pattern must have ALL required skills.

        Returns:
            List of Match objects for patterns with matching skills.
        """
        keys = self._skill_registry.find_by_skills(required, match_all=match_all)
        matches: list[Match] = []
        for key in keys:
            data = self._storage.load(key)
            if data is None:
                continue
            try:
                pattern = Pattern.model_validate(data)
            except (ValueError, KeyError):
                continue
            matches.append(
                Match(
                    pattern=pattern,
                    similarity=1.0,
                    reuse_tier="duplicate",
                    pattern_key=key,
                )
            )
        return matches

    # ------------------------------------------------------------------
    # Export / Import
    # ------------------------------------------------------------------

    def export(self) -> list[dict]:
        """Export all stored patterns as a list of dicts (JSONL-compatible).

        Each record has ``"key"`` (the storage key) and ``"data"`` (the
        pattern dict). Pass to :meth:`import_data` to restore.

        Returns:
            List of ``{"key": str, "data": dict}`` records for all patterns.
        """
        keys = self._storage.list_keys(prefix=PATTERNS_PREFIX)
        records = []
        for key in keys:
            data = self._storage.load(key)
            if data is not None:
                records.append({"version": 1, "key": key, "data": data})
        return records

    def import_data(self, records: list[dict], overwrite: bool = False) -> int:
        """Import patterns from previously exported data.

        Args:
            records: List of ``{"key": str, "data": dict}`` records as
                returned by :meth:`export`.
            overwrite: If ``False`` (default), skip patterns whose key
                already exists. If ``True``, overwrite existing patterns.

        Returns:
            Number of patterns successfully imported.
        """
        imported = 0
        for record in records:
            key = record.get("key")
            data = record.get("data")
            if not key or not isinstance(data, dict):
                _log.warning("Skipping malformed import record: %r", record)
                continue
            if not key.startswith(f"{PATTERNS_PREFIX}/") or ".." in key:
                _log.warning(
                    "Skipping import record with invalid key %r — "
                    "only patterns/ keys without path traversal are allowed",
                    key,
                )
                continue
            if not overwrite and self._storage.load(key) is not None:
                continue
            self._storage.save(key, data)
            imported += 1
        _log.info("Imported %d patterns (overwrite=%s)", imported, overwrite)
        return imported

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @property
    def storage_type(self) -> str:
        """Return the class name of the active storage backend."""
        return type(self._storage).__name__

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
            raise ProviderError(
                f"Memory.{method}() requires an LLM provider. "
                "Pass llm=OpenAIProvider(...) or llm=AnthropicProvider(...) to Memory()."
            )

    @staticmethod
    def _validate_task(task: str) -> None:
        if not task or not task.strip():
            raise ValidationError("task must be a non-empty string")
        if len(task) > _MAX_TASK_LEN:
            raise ValidationError(f"task exceeds maximum length of {_MAX_TASK_LEN} characters")

    @staticmethod
    def _validate_code(code: str) -> None:
        if not code or not code.strip():
            raise ValidationError("code must be a non-empty string")
        if len(code) > _MAX_CODE_LEN:
            raise ValidationError(f"code exceeds maximum length of {_MAX_CODE_LEN} characters")

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if limit < 1:
            raise ValidationError(f"limit must be >= 1, got {limit}")

    @staticmethod
    def _validate_eval_score(score: float) -> None:
        if not (_MIN_EVAL_SCORE <= score <= _MAX_EVAL_SCORE):
            raise ValidationError(
                f"eval_score must be between {_MIN_EVAL_SCORE} and {_MAX_EVAL_SCORE}, got {score}"
            )

    @staticmethod
    def _pattern_key(task: str) -> str:
        # SHA-256 (first 8 hex chars) — MD5 is cryptographically broken
        task_hash = hashlib.sha256(task.encode()).hexdigest()[:8]
        ts = int(time.time() * 1000)
        return f"{PATTERNS_PREFIX}/{task_hash}_{ts}"

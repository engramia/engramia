# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""LearningService — stores a successful agent run as a reusable pattern."""

import logging
from typing import Any, Literal

from engramia._util import PATTERNS_PREFIX, _pattern_key, jaccard
from engramia.analytics.collector import ROICollector
from engramia.core.eval_store import EvalStore
from engramia.core.metrics import MetricsStore
from engramia.governance.redaction import RedactionPipeline
from engramia.providers.base import EmbeddingProvider, StorageBackend
from engramia.telemetry import metrics as _metrics
from engramia.telemetry import tracing as _tracing
from engramia.types import LearnResult, Pattern

_log = logging.getLogger(__name__)

_MAX_PATTERN_COUNT = 100_000

# Tasks whose Jaccard similarity meets this threshold are treated as the
# same pattern by `learn()`'s dedup logic. Chosen to match the
# `SIMILARITY_DUPLICATE` constant that recall uses when labelling the
# "duplicate" reuse tier — above 0.92 the two tasks are essentially the
# same intent, not just related.
JACCARD_LEARN_DEDUP_THRESHOLD = 0.92

OnDuplicate = Literal["replace_with_better", "keep_both", "skip"]


class LearningService:
    """Stores a successful agent run as a reusable pattern.

    Args:
        storage: Storage backend for persistence.
        embeddings: Embedding provider.
        metrics_store: Shared MetricsStore instance.
        eval_store: Shared EvalStore instance.
        roi_collector: Shared ROICollector instance.
        redaction: Optional redaction pipeline.
    """

    def __init__(
        self,
        storage: StorageBackend,
        embeddings: EmbeddingProvider | None,
        metrics_store: MetricsStore,
        eval_store: EvalStore,
        roi_collector: ROICollector,
        redaction: RedactionPipeline | None = None,
    ) -> None:
        self._storage = storage
        self._embeddings = embeddings
        self._metrics_store = metrics_store
        self._eval_store = eval_store
        self._roi_collector = roi_collector
        self._redaction = redaction

    def _find_duplicate(self, task: str) -> tuple[str | None, dict | None]:
        """Return ``(key, data)`` of the first pattern whose task is a
        near-duplicate of *task* at word-level Jaccard >= 0.92, else (None, None).

        Scans the full pattern store. For realistic pattern counts
        (< 100k) this is a bounded O(n) walk once per ``learn()``; the
        storage backend keeps the key list in memory.
        """
        candidate_keys = self._storage.list_keys(prefix=PATTERNS_PREFIX)
        for existing_key in candidate_keys:
            existing = self._storage.load(existing_key)
            if not isinstance(existing, dict):
                continue
            existing_task = existing.get("task")
            if not isinstance(existing_task, str):
                continue
            if jaccard(existing_task, task) >= JACCARD_LEARN_DEDUP_THRESHOLD:
                return existing_key, existing
        return None, None

    @_tracing.traced("memory.learn")
    def learn(
        self,
        task: str,
        code: str,
        eval_score: float,
        output: str | None = None,
        *,
        run_id: str | None = None,
        classification: str = "internal",
        source: str = "api",
        author: str | None = None,
        on_duplicate: OnDuplicate = "replace_with_better",
    ) -> LearnResult:
        """Record a successful agent run.

        Args:
            task: Natural language description of what the agent does.
            code: Agent source code (the solution).
            eval_score: Quality score 0.0-10.0.
            output: Optional captured stdout/output.
            run_id: Optional caller-supplied correlation ID.
            classification: Data sensitivity level.
            source: Origin of the pattern.
            author: Identifier of the creator.
            on_duplicate: What to do when a near-duplicate pattern
                (Jaccard >= 0.92 on the task text) is already stored.

                - ``"replace_with_better"`` (default): overwrite the
                  existing record when the incoming ``eval_score`` beats
                  its stored ``success_score``. Otherwise keep the
                  existing record and return ``stored=False``.
                - ``"keep_both"``: persist the new pattern under a fresh
                  key alongside the existing one. Pre-0.6.7 behaviour.
                - ``"skip"``: never overwrite; always return
                  ``stored=False`` when a duplicate is present.

        Returns:
            LearnResult with ``stored``, ``pattern_count`` and
            ``pattern_key`` reflecting the final outcome.
        """
        from engramia.exceptions import ValidationError

        current_count = len(self._storage.list_keys(prefix=PATTERNS_PREFIX))
        if current_count >= _MAX_PATTERN_COUNT:
            raise ValidationError(
                f"Pattern store is full ({current_count}/{_MAX_PATTERN_COUNT}). "
                "Run aging or delete patterns before learning new ones."
            )

        # Dedup — only searched when the caller wants it, and only once.
        existing_key: str | None = None
        existing_data: dict | None = None
        if on_duplicate != "keep_both":
            existing_key, existing_data = self._find_duplicate(task)

        if existing_key is not None and existing_data is not None:
            if on_duplicate == "skip":
                _log.info("learn() skipped — duplicate of %s (on_duplicate=skip)", existing_key)
                return LearnResult(stored=False, pattern_count=current_count)

            # replace_with_better: only overwrite when we have a higher score
            existing_score = float(existing_data.get("success_score") or 0.0)
            if eval_score <= existing_score:
                _log.info(
                    "learn() kept existing %s (score %.2f >= incoming %.2f)",
                    existing_key,
                    existing_score,
                    eval_score,
                )
                return LearnResult(stored=False, pattern_count=current_count)
            # fall through and overwrite under the SAME key

        design: dict[str, Any] = {"code": code, "classification": classification, "source": source}
        if output is not None:
            design["output"] = output

        redacted = False
        if self._redaction is not None:
            clean_design, findings = self._redaction.process(design, extra_fields={"task": task})
            if findings:
                design = {k: v for k, v in clean_design.items() if k != "task"}
                redacted = True

        pattern = Pattern(task=task, design=design, success_score=eval_score)
        # Re-use the duplicate's key when we are replacing so downstream
        # references (analytics rollups, skill registry entries) stay valid.
        key = existing_key if existing_key is not None else _pattern_key(task)

        data = pattern.model_dump()
        if author:
            data["_author_key_id"] = author
        self._storage.save(key, data)
        if self._embeddings is not None:
            embedding = self._embeddings.embed(task)
            self._storage.save_embedding(key, embedding)

        self._storage.save_pattern_meta(
            key,
            classification=classification,
            source=source,
            run_id=run_id,
            author=author,
            redacted=redacted,
        )

        self._eval_store.save(
            agent_name=key,
            task=task,
            scores={"overall": eval_score, "feedback": ""},
        )
        self._metrics_store.record_run(success=True, eval_score=eval_score)
        self._roi_collector.record_learn(pattern_key=key, eval_score=eval_score)

        pattern_count = len(self._storage.list_keys(prefix=PATTERNS_PREFIX))
        _metrics.set_pattern_count(pattern_count)
        return LearnResult(stored=True, pattern_count=pattern_count)

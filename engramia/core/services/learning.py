# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""LearningService — stores a successful agent run as a reusable pattern."""

import logging
from typing import Any

from engramia._util import PATTERNS_PREFIX
from engramia.analytics.collector import ROICollector
from engramia.core.eval_store import EvalStore
from engramia.core.metrics import MetricsStore
from engramia.governance.redaction import RedactionPipeline
from engramia.providers.base import EmbeddingProvider, StorageBackend
from engramia.types import LearnResult, Pattern

_log = logging.getLogger(__name__)

_MAX_PATTERN_COUNT = 100_000


def _pattern_key(task: str) -> str:
    import hashlib
    import time

    task_hash = hashlib.sha256(task.encode()).hexdigest()[:8]
    ts = int(time.time() * 1000)
    return f"{PATTERNS_PREFIX}/{task_hash}_{ts}"


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
        embeddings: EmbeddingProvider,
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

        Returns:
            LearnResult with stored=True and current pattern count.
        """
        from engramia.exceptions import ValidationError

        current_count = len(self._storage.list_keys(prefix=PATTERNS_PREFIX))
        if current_count >= _MAX_PATTERN_COUNT:
            raise ValidationError(
                f"Pattern store is full ({current_count}/{_MAX_PATTERN_COUNT}). "
                "Run aging or delete patterns before learning new ones."
            )

        design: dict[str, Any] = {"code": code, "classification": classification, "source": source}
        if output is not None:
            design["output"] = output

        redacted = False
        if self._redaction is not None:
            clean_design, findings = self._redaction.process(
                design, extra_fields={"task": task}
            )
            if findings:
                design = {k: v for k, v in clean_design.items() if k != "task"}
                redacted = True

        pattern = Pattern(task=task, design=design, success_score=eval_score)
        key = _pattern_key(task)

        self._storage.save(key, pattern.model_dump())
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
        return LearnResult(stored=True, pattern_count=pattern_count)

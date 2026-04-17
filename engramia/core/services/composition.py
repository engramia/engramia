# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""CompositionService — builds multi-agent pipelines from stored patterns."""

import logging

from engramia.core.eval_store import EvalStore
from engramia.providers.base import EmbeddingProvider, LLMProvider, StorageBackend
from engramia.reuse.composer import PipelineComposer
from engramia.reuse.matcher import PatternMatcher
from engramia.telemetry import tracing as _tracing
from engramia.types import Pipeline

_log = logging.getLogger(__name__)


class CompositionService:
    """Builds a multi-agent pipeline for a task from stored patterns.

    Args:
        llm: LLM provider used for task decomposition.
        storage: Storage backend for pattern lookup.
        embeddings: Embedding provider.
        eval_store: Shared EvalStore instance for quality-weighted matching.
    """

    def __init__(
        self,
        llm: LLMProvider,
        storage: StorageBackend,
        embeddings: EmbeddingProvider | None,
        eval_store: EvalStore,
    ) -> None:
        self._llm = llm
        self._storage = storage
        self._embeddings = embeddings
        self._eval_store = eval_store

    @_tracing.traced("memory.compose")
    def compose(self, task: str) -> Pipeline:
        """Build a pipeline by decomposing task into stages via LLM.

        Args:
            task: High-level task description.

        Returns:
            Pipeline with stages and contract validation result.
        """
        matcher = PatternMatcher(self._storage, self._embeddings, self._eval_store)
        composer = PipelineComposer(self._llm, matcher)
        return composer.compose(task)

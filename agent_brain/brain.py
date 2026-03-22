"""Brain — the central facade for Agent Brain.

Users interact exclusively with this class. Internals (storage, embeddings,
LLM provider) are injected via constructor and swappable at any time.
"""

import hashlib
import time
from typing import Any, Literal

from agent_brain.providers.base import (
    EmbeddingProvider,
    LLMProvider,
    StorageBackend,
)
from agent_brain.types import (
    LearnResult,
    Match,
    Pattern,
    SIMILARITY_ADAPT,
    SIMILARITY_DUPLICATE,
)

_PATTERNS_PREFIX = "patterns"


def _reuse_tier(similarity: float) -> Literal["duplicate", "adapt", "fresh"]:
    if similarity >= SIMILARITY_DUPLICATE:
        return "duplicate"
    if similarity >= SIMILARITY_ADAPT:
        return "adapt"
    return "fresh"


class Brain:
    """Self-learning memory layer for AI agent frameworks.

    Inject your chosen providers at construction time:

    .. code-block:: python

        from agent_brain import Brain
        from agent_brain.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage

        brain = Brain(
            llm=OpenAIProvider(model="gpt-4.1"),
            embeddings=OpenAIEmbeddings(),
            storage=JSONStorage(path="./brain_data"),
        )

    Args:
        llm: LLM provider used for evaluate(), compose(), and evolve_prompt().
            May be ``None`` if you only need learn() and recall().
        embeddings: Embedding provider for semantic search.
        storage: Storage backend for persistence and vector search.
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
            eval_score: Quality score, 0.0–10.0 (from evaluate() or manual).
            output: Optional captured stdout/output for reference.

        Returns:
            LearnResult with ``stored=True`` and the current pattern count.
        """
        design: dict[str, Any] = {"code": code}
        if output is not None:
            design["output"] = output

        pattern = Pattern(
            task=task,
            design=design,
            success_score=eval_score,
        )

        key = self._pattern_key(task)
        self._storage.save(key, pattern.model_dump())

        embedding = self._embeddings.embed(task)
        self._storage.save_embedding(key, embedding)

        pattern_count = len(self._storage.list_keys(prefix=_PATTERNS_PREFIX))
        return LearnResult(stored=True, pattern_count=pattern_count)

    # ------------------------------------------------------------------
    # Recall
    # ------------------------------------------------------------------

    def recall(self, task: str, limit: int = 5) -> list[Match]:
        """Find stored patterns most relevant to *task*.

        Uses semantic embedding search — no exact keyword match required.
        Results are sorted by similarity descending.

        Args:
            task: Natural language description of the new task.
            limit: Maximum number of matches to return.

        Returns:
            List of Match objects. May be shorter than *limit* if fewer
            patterns are stored.
        """
        embedding = self._embeddings.embed(task)
        results = self._storage.search_similar(
            embedding,
            limit=limit,
            prefix=_PATTERNS_PREFIX,
        )

        matches: list[Match] = []
        for key, similarity in results:
            data = self._storage.load(key)
            if data is None:
                continue
            pattern = Pattern.model_validate(data)
            matches.append(
                Match(
                    pattern=pattern,
                    similarity=similarity,
                    reuse_tier=_reuse_tier(similarity),
                )
            )
        return matches

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pattern_key(task: str) -> str:
        """Generate a unique storage key for a pattern.

        Combines a short task hash with a millisecond timestamp so that
        the same task stored multiple times produces distinct keys.
        """
        task_hash = hashlib.md5(task.encode()).hexdigest()[:8]
        ts = int(time.time() * 1000)
        return f"{_PATTERNS_PREFIX}/{task_hash}_{ts}"

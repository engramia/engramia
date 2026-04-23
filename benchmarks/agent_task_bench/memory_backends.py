# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Memory backends for AgentTaskBench.

Two configurations:

- :class:`NoMemoryBackend` — stateless stub. ``recall_context`` is
  always the empty string; ``remember_success`` is a no-op. This is
  the baseline every other backend has to beat.
- :class:`EngramiaBackend` — full :class:`engramia.Memory` wired
  around ``Memory.learn`` / ``Memory.recall`` /
  ``Memory.refine_pattern``.

The split is intentionally tiny (three methods). HumanEval+ is a
code-generation workload — we want to measure whether repeated
exposure accumulates useful examples, so the memory interface the
runner consumes is just "give me context for this prompt" and
"here is a verified-correct solution".
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

_CONTEXT_RECALL_LIMIT = 3
_CONTEXT_CODE_CHAR_CAP = 400


class MemoryBackend(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def recall_context(self, prompt: str) -> str:
        """Return a context prefix to prepend to the agent's prompt."""
        ...

    def remember_success(self, prompt: str, completion: str, eval_score: float) -> None:
        """Called when a completion passed. Backends that learn over
        time (Engramia) persist the (prompt, completion) pair; backends
        that don't (baseline) no-op.
        """
        ...

    def reset(self) -> None:
        """Drop all stored state. Called at session start."""
        ...


class NoMemoryBackend:
    @property
    def name(self) -> str:
        return "baseline-no-memory"

    @property
    def version(self) -> str:
        return "1.0"

    def recall_context(self, prompt: str) -> str:
        return ""

    def remember_success(self, prompt: str, completion: str, eval_score: float) -> None:
        return

    def reset(self) -> None:
        return


class EngramiaBackend:
    """Wraps :class:`engramia.Memory` for AgentTaskBench.

    One Engramia instance per session, backed by a fresh JSONStorage
    temp directory. Patterns seeded by ``remember_success`` use
    ``on_duplicate='replace_with_better'`` so repeated exposures of
    the same task only persist when the new eval score is higher.
    """

    def __init__(self, *, use_local_embeddings: bool = False) -> None:
        from engramia import Memory
        from engramia.providers import JSONStorage

        if use_local_embeddings:
            from engramia.providers.local_embeddings import LocalEmbeddings

            embeddings = LocalEmbeddings()
        else:
            from engramia.providers.openai import OpenAIEmbeddings

            embeddings = OpenAIEmbeddings()

        self._tmpdir = tempfile.mkdtemp(prefix="engramia_task_bench_")
        self._storage = JSONStorage(path=Path(self._tmpdir))
        self._memory = Memory(embeddings=embeddings, storage=self._storage)

        try:
            import engramia

            self._version = engramia.__version__
        except (ImportError, AttributeError):
            self._version = "unknown"

    @property
    def name(self) -> str:
        return "engramia"

    @property
    def version(self) -> str:
        return self._version

    def recall_context(self, prompt: str) -> str:
        matches = self._memory.recall(
            task=prompt,
            limit=_CONTEXT_RECALL_LIMIT,
            deduplicate=False,
            eval_weighted=True,
            readonly=True,
        )
        if not matches:
            return ""
        blocks: list[str] = []
        for m in matches:
            code = (m.pattern.design or {}).get("code", "")
            blocks.append(
                f"Prior task: {m.pattern.task[:160]}\n"
                f"Known-good solution:\n{_truncate(code, _CONTEXT_CODE_CHAR_CAP)}"
            )
        return "\n\n".join(blocks)

    def remember_success(self, prompt: str, completion: str, eval_score: float) -> None:
        # `learn` with on_duplicate='replace_with_better' — repeated
        # success on the same task only replaces the stored pattern
        # when the new attempt scored higher, so the best-known
        # completion per task persists over time.
        result = self._memory.learn(
            task=prompt,
            code=completion,
            eval_score=eval_score,
            source="task_bench",
            on_duplicate="replace_with_better",
        )
        if not result.stored:
            # Same task already had a higher-scored pattern; still
            # append a fresh eval-store observation so the quality
            # evidence for this pattern stays current.
            matches = self._memory.recall(
                task=prompt,
                limit=1,
                deduplicate=False,
                eval_weighted=True,
                readonly=True,
            )
            if matches:
                self._memory.refine_pattern(
                    matches[0].pattern_key,
                    eval_score,
                    feedback="repeat success",
                )

    def reset(self) -> None:
        for key in list(self._storage.list_keys(prefix="patterns/")):
            self._storage.delete(key)
        # Also clear the eval-store list.
        scope_key = f"evals/{self._memory._eval_store._tenant_id}/{self._memory._eval_store._project_id}/_list"  # noqa: SLF001
        self._storage.save(scope_key, [])


def _truncate(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    return text[:cap] + "  …[truncated]"

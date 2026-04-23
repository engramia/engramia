# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Engramia adapter — implements both :class:`MemoryAdapter` and
:class:`LifecycleAdapter` so the lifecycle harness can run the same
scenarios against Engramia alongside Mem0, Hindsight, and any future
competitor.

The adapter is a thin wrapper over :class:`engramia.Memory`; it exists
so lifecycle scoring code stays adapter-agnostic (Engramia's Memory
facade is already adapter-shaped, but not Protocol-compliant in the
type-checker's eyes).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from benchmarks.adapters.base import MatchResult


class EngramiaAdapter:
    """Adapter over :class:`engramia.Memory` for the lifecycle benchmark.

    Implements both :class:`MemoryAdapter` and :class:`LifecycleAdapter`.
    """

    def __init__(self, *, use_local_embeddings: bool = True) -> None:
        from engramia import Memory
        from engramia.providers import JSONStorage

        if use_local_embeddings:
            from engramia.providers.local_embeddings import LocalEmbeddings

            embeddings: Any = LocalEmbeddings()
            self._embedding_model = "all-MiniLM-L6-v2 (local)"
        else:
            import os

            if not os.environ.get("OPENAI_API_KEY"):
                raise RuntimeError(
                    "OPENAI_API_KEY is not set; pass use_local_embeddings=True "
                    "for a zero-cost run."
                )
            from engramia.providers.openai import OpenAIEmbeddings

            embeddings = OpenAIEmbeddings()
            self._embedding_model = "text-embedding-3-small"

        tmpdir = tempfile.mkdtemp(prefix="engramia_lifecycle_")
        self._tmpdir = tmpdir
        self._storage = JSONStorage(path=Path(tmpdir))
        self._mem = Memory(embeddings=embeddings, storage=self._storage)
        self._pattern_key_by_id: dict[str, str] = {}

        try:
            import engramia

            self._version = engramia.__version__
        except (ImportError, AttributeError):
            self._version = "unknown"

    # ------------------------------------------------------------------
    # MemoryAdapter
    # ------------------------------------------------------------------

    @property
    def system_name(self) -> str:
        return "engramia"

    @property
    def system_version(self) -> str:
        return self._version

    @property
    def forced_mapping_note(self) -> str:
        return (
            "Engramia runs natively on this harness — no forced mapping. "
            f"Embedding backend: {self._embedding_model}. Every scenario "
            "uses the real public API (learn, recall, refine_pattern) "
            "and the real eval store path."
        )

    def seed(self, patterns: list[dict[str, Any]]) -> None:
        self._pattern_key_by_id.clear()
        for p in patterns:
            self._mem.learn(
                task=p["task"],
                code=p["code"],
                eval_score=p["eval_score"],
                on_duplicate="keep_both",
            )
        # After seeding, walk storage to map pattern_id → storage key by
        # matching the task text + code. Competitor harness uses
        # pattern_id as an opaque handle; we need a real storage key for
        # refine_pattern calls.
        for key in self._storage.list_keys(prefix="patterns/"):
            data = self._storage.load(key)
            if not data:
                continue
            task = data.get("task")
            code = (data.get("design") or {}).get("code")
            for p in patterns:
                if p["task"] == task and p["code"] == code:
                    self._pattern_key_by_id.setdefault(p["pattern_id"], key)
                    break

    def recall(
        self,
        query: str,
        limit: int,
        *,
        eval_weighted: bool = False,
        recency_weight: float = 0.0,
    ) -> list[MatchResult]:
        matches = self._mem.recall(
            task=query,
            limit=limit,
            deduplicate=False,
            eval_weighted=eval_weighted,
            recency_weight=recency_weight,
            recency_half_life_days=30.0,
            readonly=True,
        )
        out: list[MatchResult] = []
        for m in matches:
            # Resolve pattern_id from storage key if possible.
            pid = m.pattern_key
            for known_pid, known_key in self._pattern_key_by_id.items():
                if known_key == m.pattern_key:
                    pid = known_pid
                    break
            out.append(
                MatchResult(
                    similarity=float(m.similarity),
                    task_text=m.pattern.task,
                    pattern_id=pid,
                    success_score=float(m.pattern.success_score),
                    timestamp=float(m.pattern.timestamp),
                    metadata={
                        "effective_score": m.effective_score,
                        "storage_key": m.pattern_key,
                    },
                )
            )
        return out

    def reset(self) -> None:
        for key in list(self._storage.list_keys(prefix="patterns/")):
            self._storage.delete(key)
        self._pattern_key_by_id.clear()

    # ------------------------------------------------------------------
    # LifecycleAdapter
    # ------------------------------------------------------------------

    @property
    def supports_refine(self) -> bool:
        return True

    def refine_pattern(self, pattern_id: str, eval_score: float, *, feedback: str = "") -> None:
        storage_key = self._pattern_key_by_id.get(pattern_id, pattern_id)
        self._mem.refine_pattern(storage_key, eval_score, feedback=feedback)

    # ------------------------------------------------------------------
    # Lifecycle-specific helpers exposed for scenarios that need direct
    # storage manipulation (e.g. back-dating timestamps).
    # ------------------------------------------------------------------

    def patch_timestamp(self, pattern_id: str, unix_timestamp: float) -> None:
        """Rewrite ``Pattern.timestamp`` on disk. Benchmark-only."""
        key = self._pattern_key_by_id.get(pattern_id, pattern_id)
        data = self._storage.load(key)
        if data is None:
            return
        data["timestamp"] = unix_timestamp
        self._storage.save(key, data)

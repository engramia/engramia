# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Mem0 (OSS, local) adapter for the Engramia LongMemEval harness.

Runs against the self-hosted ``mem0ai`` package (Qdrant on-disk,
OpenAI embeddings + LLM). No Mem0 Cloud account needed — reuses the
caller's ``OPENAI_API_KEY``.

Forced-mapping caveats
----------------------

Mem0 is a user-preference / fact-extraction memory system, not an
execution-memory system. Running the Engramia synthetic LongMemEval
(12 agent domains × code patterns) on it stretches its native use
case. The honest translation we make:

* **Storage**: each pattern is stored as one raw memory via
  ``memory.add(text, infer=False, metadata={...})``. ``infer=False``
  bypasses Mem0's default fact-extraction LLM pass so the benchmark
  doesn't pay per-write LLM calls AND so the stored text is what
  the harness pass rules grep for. The metadata dict carries
  ``pattern_id`` and ``eval_score`` for round-trip.
* **Scoring**: Mem0's returned ``score`` is a Qdrant-derived 0-1
  similarity. It is *not* the same distribution as Engramia's raw
  cosine on OpenAI ``text-embedding-3-small``; thresholds tuned for
  one do not transfer. The competitor harness drops the
  ``SINGLE_HOP_THRESHOLD`` comparison and uses text-only pass rules.
* **Quality weighting**: Mem0 has no ``eval_weighted`` equivalent.
  Eval scores are stored in metadata but do not influence ranking.
* **Recency**: Mem0 has no ``recency_weight`` knob. Memories are
  timestamped but not re-ranked by age at query time.
* **Scope**: per-dimension isolation is achieved by assigning a
  distinct ``user_id`` per dimension and calling
  ``memory.delete_all(user_id=...)`` between runs.

Every caveat above is surfaced in ``forced_mapping_note`` and
propagated into the output JSON, so no reader can interpret the
resulting numbers without seeing the mapping choices.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

from benchmarks.adapters.base import MatchResult, MemoryAdapter

logger = logging.getLogger(__name__)


class Mem0Adapter(MemoryAdapter):
    """Mem0 OSS (local Qdrant) MemoryAdapter implementation."""

    def __init__(self, user_id: str = "engramia-bench") -> None:
        try:
            from mem0 import Memory
        except ImportError as exc:
            raise RuntimeError(
                "mem0ai is not installed. Install with: pip install mem0ai"
            ) from exc

        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY must be set — mem0 uses OpenAI for embeddings "
                "and LLM by default."
            )
        # Silence posthog telemetry noise on stdout.
        os.environ.setdefault("MEM0_TELEMETRY", "False")

        self._user_id = user_id
        self._qdrant_path = tempfile.mkdtemp(prefix="mem0_bench_")
        config = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": "engramia_bench",
                    "embedding_model_dims": 1536,
                    "path": self._qdrant_path,
                    "on_disk": True,
                },
            },
        }
        self._memory = Memory.from_config(config)
        try:
            import mem0
            self._version = mem0.__version__
        except (ImportError, AttributeError):
            self._version = "unknown"

    @property
    def system_name(self) -> str:
        return "mem0-local"

    @property
    def system_version(self) -> str:
        return self._version

    # LifecycleAdapter capability declarations
    @property
    def supports_refine(self) -> bool:
        # Mem0's public API has no endpoint to replace an evaluation
        # record on an existing memory. ``metadata`` is settable but
        # Mem0's ranker does not consult it for relevance scoring.
        return False

    def refine_pattern(self, pattern_id: str, eval_score: float, *, feedback: str = "") -> None:
        raise NotImplementedError(
            "Mem0 does not expose a refine_pattern equivalent — its "
            "ranker does not re-read metadata for relevance. Lifecycle "
            "scenarios depending on refine_pattern should mark Mem0 "
            "as capability_missing."
        )

    @property
    def forced_mapping_note(self) -> str:
        return (
            "Mem0 is a user-preference / fact-extraction memory system, "
            "not an execution-memory system. Patterns are stored verbatim "
            "via add(infer=False) to avoid the default LLM extraction pass; "
            "Mem0 has no eval_weighted or recency_weight equivalent, so "
            "those dimensions are exercised against raw Qdrant similarity "
            "alone. Returned scores are Qdrant-derived and not on the same "
            "distribution as Engramia's raw cosine — thresholds are dropped "
            "and pass rules check top-1 text content only."
        )

    def seed(self, patterns: list[dict[str, Any]]) -> None:
        # Drop any residue from a previous dimension on the same user_id
        # so reruns are clean.
        self._memory.delete_all(user_id=self._user_id)
        for p in patterns:
            content = f"{p['task']}\n\n{p['code']}"
            metadata = {
                "pattern_id": p["pattern_id"],
                "eval_score": p["eval_score"],
                "task": p["task"],
                "code": p["code"],
            }
            self._memory.add(
                content,
                user_id=self._user_id,
                infer=False,
                metadata=metadata,
            )

    def recall(
        self,
        query: str,
        limit: int,
        *,
        eval_weighted: bool = False,
        recency_weight: float = 0.0,
    ) -> list[MatchResult]:
        # eval_weighted / recency_weight are ignored — documented in
        # forced_mapping_note.
        del eval_weighted, recency_weight
        resp = self._memory.search(
            query=query,
            top_k=limit,
            filters={"user_id": self._user_id},
        )
        raw_results = resp.get("results", []) if isinstance(resp, dict) else list(resp)
        matches: list[MatchResult] = []
        for r in raw_results:
            meta = r.get("metadata") or {}
            matches.append(
                MatchResult(
                    similarity=float(r.get("score", 0.0)),
                    task_text=meta.get("task", r.get("memory", "")),
                    pattern_id=meta.get("pattern_id", r.get("id", "")),
                    success_score=meta.get("eval_score"),
                    timestamp=None,
                    metadata={
                        "mem0_id": r.get("id"),
                        "raw_memory": r.get("memory"),
                    },
                )
            )
        return matches

    def reset(self) -> None:
        self._memory.delete_all(user_id=self._user_id)

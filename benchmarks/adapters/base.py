# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Abstract memory-system adapter protocol.

Any competitor memory library that wants to run against the Engramia
synthetic LongMemEval harness implements :class:`MemoryAdapter`. The
harness calls ``seed`` once per dimension run, then ``recall`` per
query, and treats every backend as producing the same
:class:`MatchResult` shape so scoring code stays unchanged.

Design
------
We deliberately keep the surface thin. The harness itself makes no
assumptions about how a given backend represents ranking (cosine,
BM25, hybrid, LLM-extracted facts) — the adapter is responsible for
translating internal ranking into a list of ``(similarity, text,
metadata)`` tuples sorted best-first. Metadata is where backends can
round-trip their own identifiers (e.g. Mem0 memory ids, Hindsight
bank_ids) so the harness can keep its existing "did top-1's task
text contain the domain marker" pass rule.

Forced-mapping honesty
----------------------
Most competitor libraries were not built for execution-memory
workloads. Running this benchmark on them is, in part, a stress
test of whether their semantics happen to cover our cases. Each
concrete adapter MUST document its forced-mapping choices in the
class docstring and surface them via ``forced_mapping_note`` so the
emitted JSON is self-explanatory to a reader who does not have the
harness code open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class MatchResult:
    """One recall result returned by an adapter.

    Attributes:
        similarity: A ranking score in [0, 1]. Higher = better match.
            Backends that do not natively normalise should scale to
            this range so threshold comparisons in the harness remain
            meaningful. None if the backend did not expose a score.
        task_text: The stored task / memory text. The harness pass
            rules for single_hop / multi_hop / temporal / knowledge
            all string-match against this field, so it MUST be the
            text the backend ranked, not a derived summary.
        pattern_id: The adapter's identifier for the stored item
            (used for dedup, deletion, traceability). Opaque to the
            harness.
        success_score: Optional quality score in [0, 10] if the
            backend exposes one. Used by the ``knowledge_updates``
            dimension pass rule (top-1 score ≥ 8.5).
        timestamp: Optional Unix epoch seconds. Used by the temporal
            dimension's recency-aware call path when the backend
            supports it.
        metadata: Per-backend round-trip info. Ignored by the harness.
    """

    similarity: float | None
    task_text: str
    pattern_id: str
    success_score: float | None = None
    timestamp: float | None = None
    metadata: dict[str, Any] | None = None


@runtime_checkable
class MemoryAdapter(Protocol):
    """Adapter protocol for a memory system under benchmark.

    Implementations should be idempotent per ``seed()`` call — the
    harness calls ``seed()`` once per dimension on a fresh backend
    instance and never re-seeds within a dimension run.
    """

    @property
    def system_name(self) -> str:
        """Human-readable backend identifier, e.g. ``"mem0-local"``."""
        ...

    @property
    def system_version(self) -> str:
        """Version string of the backend library. Captured in JSON."""
        ...

    @property
    def forced_mapping_note(self) -> str:
        """One-paragraph honest caveat about how this adapter maps the
        execution-memory benchmark onto the backend's native
        semantics. Surfaced into the output JSON so readers are not
        misled by a number that was produced under a stretched mapping.
        """
        ...

    def seed(self, patterns: list[dict[str, Any]]) -> None:
        """Store every pattern in ``patterns`` on the backend.

        Each dict has: ``task: str``, ``code: str``, ``eval_score:
        float``, ``pattern_id: str``. The adapter decides how to
        present this to the backend (one memory per pattern, a
        conversation of one user turn + one assistant turn, a key-
        value fact, etc.). The mapping choice should be captured in
        ``forced_mapping_note``.
        """
        ...

    def recall(
        self,
        query: str,
        limit: int,
        *,
        eval_weighted: bool = False,
        recency_weight: float = 0.0,
    ) -> list[MatchResult]:
        """Return up to ``limit`` matches sorted best-first.

        ``eval_weighted`` and ``recency_weight`` are hints — backends
        that support comparable knobs should honour them, the rest
        should ignore and note that in ``forced_mapping_note``.
        """
        ...

    def reset(self) -> None:
        """Drop all stored patterns. Called between dimension runs."""
        ...


@runtime_checkable
class LifecycleAdapter(Protocol):
    """Optional extension for backends that expose a quality-evidence
    write path.

    Splitting this off from :class:`MemoryAdapter` reflects a
    deliberate capability split: a memory system that does semantic
    recall is not obligated to support closed-loop feedback refinement.
    The lifecycle benchmark queries ``supports_refine`` on each adapter
    and records "missing capability" in the result JSON when it is
    False, so readers can tell a genuine zero from an unused scenario.

    Engramia's adapter implements this via
    :py:meth:`engramia.Memory.refine_pattern`. Mem0 and Hindsight do
    not currently expose an equivalent write path — they declare
    ``supports_refine == False`` and the harness records the gap
    rather than producing a misleading number.
    """

    @property
    def supports_refine(self) -> bool:
        """``True`` when :meth:`refine_pattern` is usable.

        Defaults to ``False`` on adapters that do not implement it;
        the lifecycle harness treats a ``False`` here as "scenario
        cannot exercise this signal on this backend" and records the
        scenario score as ``None`` + a ``capability_missing`` note.
        """
        ...

    def refine_pattern(self, pattern_id: str, eval_score: float, *, feedback: str = "") -> None:
        """Record a fresh quality observation against ``pattern_id``.

        The next :meth:`recall` call on the same backend must take the
        updated evidence into account (i.e. the multiplier / ranking
        weight must reflect the latest observation). Adapters that
        cannot honour this contract should set
        ``supports_refine`` to ``False`` rather than silently accept
        the write — silent acceptance would mask the benchmark
        signal and produce false equivalence.
        """
        ...

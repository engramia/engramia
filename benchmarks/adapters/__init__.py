# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Memory-system adapters for competitor comparison on the Engramia
synthetic LongMemEval harness.

Every adapter implements the :class:`MemoryAdapter` protocol so a
single benchmark harness can swap the memory backend and report
apples-to-apples numbers. Forced-mapping caveats — e.g. Mem0 treats
patterns as extracted facts, not verbatim code — are documented in
each adapter's module docstring and surface in the output JSON
under ``metadata.forced_mapping_note``.
"""

from benchmarks.adapters.base import MemoryAdapter, MatchResult

__all__ = ["MemoryAdapter", "MatchResult"]

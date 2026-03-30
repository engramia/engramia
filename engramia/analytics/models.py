# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Pydantic models for Phase 5.7 ROI Analytics.

All types are pure data containers — no I/O, no side effects.
"""

import time
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class EventKind(StrEnum):
    """Type of a recorded ROI event."""

    LEARN = "learn"
    RECALL = "recall"


class ROIEvent(BaseModel):
    """A single learn or recall event recorded by ROICollector.

    Args:
        kind: Event type ("learn" or "recall").
        ts: Unix timestamp of the event (float seconds).
        eval_score: Eval score passed to learn() — None for recall events.
        similarity: Best cosine similarity returned — None for learn events.
        reuse_tier: Tier of the best match ("duplicate"|"adapt"|"fresh"|None).
        pattern_key: Storage key of the affected pattern.
        scope_tenant: Tenant ID at event time.
        scope_project: Project ID at event time.
    """

    kind: EventKind
    ts: float = Field(default_factory=time.time)
    eval_score: float | None = None
    similarity: float | None = None
    reuse_tier: Literal["duplicate", "adapt", "fresh"] | None = None
    pattern_key: str = ""
    scope_tenant: str = "default"
    scope_project: str = "default"


class RecallOutcome(BaseModel):
    """Outcome breakdown for recall events in a rollup window.

    Args:
        total: Total recall events in window.
        duplicate_hits: Events where best match was "duplicate".
        adapt_hits: Events where best match was "adapt".
        fresh_misses: Events where best match was "fresh" (no reuse).
        reuse_rate: (duplicate_hits + adapt_hits) / total.
        avg_similarity: Mean best-match similarity across all recall events.
    """

    total: int = 0
    duplicate_hits: int = 0
    adapt_hits: int = 0
    fresh_misses: int = 0
    reuse_rate: float = 0.0
    avg_similarity: float = 0.0


class LearnSummary(BaseModel):
    """Summary of learn events in a rollup window.

    Args:
        total: Total learn events.
        avg_eval_score: Mean eval score across learn events.
        p50_eval_score: Median eval score.
        p90_eval_score: 90th-percentile eval score.
    """

    total: int = 0
    avg_eval_score: float = 0.0
    p50_eval_score: float = 0.0
    p90_eval_score: float = 0.0


class ROIRollup(BaseModel):
    """Aggregated ROI statistics for one tenant/project/window combination.

    Args:
        tenant_id: Tenant scope.
        project_id: Project scope.
        window: Aggregation window label ("hourly" | "daily" | "weekly").
        window_start: ISO-8601 UTC timestamp of the window start.
        recall: RecallOutcome summary.
        learn: LearnSummary summary.
        roi_score: Composite score 0-10 representing overall memory ROI.
            Formula: 0.6 * reuse_rate * 10 + 0.4 * avg_eval_score.
            Weighted toward reuse since that is the primary value signal.
        computed_at: ISO-8601 UTC timestamp when this rollup was computed.
    """

    tenant_id: str = "default"
    project_id: str = "default"
    window: Literal["hourly", "daily", "weekly"]
    window_start: str
    recall: RecallOutcome = Field(default_factory=RecallOutcome)
    learn: LearnSummary = Field(default_factory=LearnSummary)
    roi_score: float = Field(default=0.0, ge=0.0, le=10.0)
    computed_at: str = ""

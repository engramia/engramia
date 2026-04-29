# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Billing data models and plan configuration.

Pydantic models represent in-memory state; DB rows are accessed via raw
SQL in the service layer (same pattern as engramia/api/auth.py).
"""

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Plan limits (single source of truth)
# ---------------------------------------------------------------------------

PLAN_LIMITS: dict[str, dict[str, int | None]] = {
    # Phase 6.6 BYOK pricing (PRICING_TIERS_260428.md). Limits are
    # fair-use rate caps now that LLM cost lives with the tenant — they
    # gate DB I/O + abuse, not LLM spend.
    "developer": {"eval_runs": 5_000, "patterns": 10_000, "projects": 2},
    "pro": {"eval_runs": 50_000, "patterns": 100_000, "projects": 10},
    "team": {"eval_runs": 250_000, "patterns": 1_000_000, "projects": 50},
    "business": {"eval_runs": 1_000_000, "patterns": 10_000_000, "projects": 250},
    "enterprise": {"eval_runs": None, "patterns": None, "projects": None},
    # Legacy alias — pre-6.6 deployments persisted plan_tier='sandbox' for
    # the free tier. Migration 024 renames existing rows to 'developer';
    # this entry is the safety net for any DB row the migration missed.
    "sandbox": {"eval_runs": 5_000, "patterns": 10_000, "projects": 2},
}

# Overage pricing per tier and metric. price_per_unit_cents charged per
# completed unit_size block. Aligned with the BYOK pricing strategy:
# unlike the pre-6.6 model, overage is now a *fair-use* surcharge for DB
# I/O — not an LLM cost recovery — so the unit price stays modest.
# Developer has no overage option (free tier hard-stops at the cap).
OVERAGE_CONFIG: dict[str, dict[str, dict[str, int]]] = {
    "pro": {"eval_runs": {"price_per_unit_cents": 500, "unit_size": 5_000}},
    "team": {"eval_runs": {"price_per_unit_cents": 2_500, "unit_size": 50_000}},
    "business": {"eval_runs": {"price_per_unit_cents": 10_000, "unit_size": 250_000}},
}

METRIC_EVAL_RUNS = "eval_runs"


# ---------------------------------------------------------------------------
# Pydantic models (service layer)
# ---------------------------------------------------------------------------


class BillingSubscription(BaseModel):
    """Cached subscription state for a tenant (local DB row, synced from Stripe).

    Args:
        tenant_id: UUID of the tenant.
        stripe_customer_id: Stripe Customer ID, or None for sandbox accounts.
        stripe_subscription_id: Stripe Subscription ID, or None for sandbox.
        plan_tier: Active plan — sandbox | pro | team | enterprise.
        billing_interval: month | year.
        status: active | past_due | canceled | trialing.
        eval_runs_limit: Monthly eval run quota (None = unlimited).
        patterns_limit: Pattern storage quota (None = unlimited).
        projects_limit: Max projects (None = unlimited).
        current_period_end: ISO-8601 UTC end of the current billing period.
    """

    tenant_id: str
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    plan_tier: str = "developer"
    billing_interval: str = "month"
    status: str = "active"
    eval_runs_limit: int | None = 5_000
    patterns_limit: int | None = 10_000
    projects_limit: int | None = 2
    current_period_end: str | None = None
    past_due_since: str | None = None
    cancel_at_period_end: bool = False

    @classmethod
    def developer_default(cls, tenant_id: str) -> "BillingSubscription":
        """Return a developer-tier subscription without a DB row.

        Developer is the free BYOK tier introduced in Phase 6.6. The
        previous free tier was named "sandbox"; the rename is permanent
        and migration 024 backfills existing rows.
        """
        limits = PLAN_LIMITS["developer"]
        return cls(
            tenant_id=tenant_id,
            plan_tier="developer",
            eval_runs_limit=limits["eval_runs"],
            patterns_limit=limits["patterns"],
            projects_limit=limits["projects"],
        )

    # Backward-compat alias — kept so call sites that still say
    # ``BillingSubscription.sandbox_default(...)`` continue to work
    # against existing fixtures while the rename rolls through. New
    # call sites should use ``developer_default``.
    sandbox_default = developer_default


class OverageSettings(BaseModel):
    """Overage opt-in configuration for a tenant/metric pair."""

    tenant_id: str
    metric: str
    enabled: bool = False
    price_per_unit_cents: int = 0
    unit_size: int = 1
    budget_cap_cents: int | None = None


class BillingStatus(BaseModel):
    """Response model for GET /v1/billing/status."""

    plan_tier: str
    status: str
    billing_interval: str
    eval_runs_used: int
    eval_runs_limit: int | None
    patterns_used: int
    patterns_limit: int | None
    projects_used: int
    projects_limit: int | None
    period_end: str | None
    overage_enabled: bool
    overage_budget_cap_cents: int | None
    cancel_at_period_end: bool = False

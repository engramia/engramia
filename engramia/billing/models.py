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
    "sandbox":    {"eval_runs": 500,    "patterns": 5_000,   "projects": 1},
    "pro":        {"eval_runs": 3_000,  "patterns": 50_000,  "projects": 3},
    "team":       {"eval_runs": 15_000, "patterns": 500_000, "projects": 15},
    "enterprise": {"eval_runs": None,   "patterns": None,    "projects": None},
}

# Overage pricing per tier and metric.
# price_per_unit_cents: charged per completed unit_size block.
# Pro:  $5  / 500  eval runs
# Team: $25 / 5000 eval runs
OVERAGE_CONFIG: dict[str, dict[str, dict[str, int]]] = {
    "pro":  {"eval_runs": {"price_per_unit_cents": 500,  "unit_size": 500}},
    "team": {"eval_runs": {"price_per_unit_cents": 2500, "unit_size": 5000}},
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
    plan_tier: str = "sandbox"
    billing_interval: str = "month"
    status: str = "active"
    eval_runs_limit: int | None = 500
    patterns_limit: int | None = 5_000
    projects_limit: int | None = 1
    current_period_end: str | None = None

    @classmethod
    def sandbox_default(cls, tenant_id: str) -> "BillingSubscription":
        """Return a sandbox-tier subscription without a DB row."""
        limits = PLAN_LIMITS["sandbox"]
        return cls(
            tenant_id=tenant_id,
            plan_tier="sandbox",
            eval_runs_limit=limits["eval_runs"],
            patterns_limit=limits["patterns"],
            projects_limit=limits["projects"],
        )


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

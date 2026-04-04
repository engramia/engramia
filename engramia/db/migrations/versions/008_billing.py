# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Phase 6: Billing — subscription state, usage metering, overage settings.

Creates three tables:
- ``billing_subscriptions`` — per-tenant plan state, synced from Stripe via webhooks
- ``usage_counters``        — rolling monthly counters (eval_runs per tenant)
- ``overage_settings``      — opt-in overage configuration per tenant/metric

Revision ID: 008
Revises: 007
Create Date: 2026-04-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: str = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # billing_subscriptions
    # Stores the local cache of Stripe subscription state per tenant.
    # Source of truth is Stripe; this table is updated via webhooks.
    # UNIQUE on tenant_id — one active subscription record per tenant.
    # ------------------------------------------------------------------
    op.create_table(
        "billing_subscriptions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, unique=True),
        sa.Column("stripe_customer_id", sa.Text(), nullable=True, unique=True),
        sa.Column("stripe_subscription_id", sa.Text(), nullable=True, unique=True),
        # sandbox | pro | team | enterprise
        sa.Column("plan_tier", sa.Text(), nullable=False, server_default="sandbox"),
        # month | year
        sa.Column("billing_interval", sa.Text(), nullable=False, server_default="month"),
        # active | past_due | canceled | trialing
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        # Effective limits (denormalised from tier; allows per-tenant Enterprise overrides)
        sa.Column("eval_runs_limit", sa.Integer(), nullable=True, server_default="500"),
        sa.Column("patterns_limit", sa.Integer(), nullable=True, server_default="5000"),
        sa.Column("projects_limit", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("current_period_start", sa.Text(), nullable=True),
        sa.Column("current_period_end", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_billing_subs_tenant", "billing_subscriptions", ["tenant_id"])
    op.create_index("idx_billing_subs_customer", "billing_subscriptions", ["stripe_customer_id"])

    # ------------------------------------------------------------------
    # usage_counters
    # Rolling monthly per-tenant, per-metric counters.
    # Incremented atomically via INSERT ... ON CONFLICT DO UPDATE.
    # Current metrics: eval_runs
    # ------------------------------------------------------------------
    op.create_table(
        "usage_counters",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("month", sa.SmallInteger(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("tenant_id", "metric", "year", "month", name="uq_usage_counters"),
    )
    op.create_index(
        "idx_usage_counters_lookup",
        "usage_counters",
        ["tenant_id", "metric", "year", "month"],
    )

    # ------------------------------------------------------------------
    # overage_settings
    # Opt-in overage configuration for a tenant/metric pair.
    # Only eval_runs is metered for overage billing in Phase 6.
    # ------------------------------------------------------------------
    op.create_table(
        "overage_settings",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        # Cents per completed unit_size block (e.g. 500 = $5.00)
        sa.Column("price_per_unit_cents", sa.Integer(), nullable=False),
        # Number of eval_runs per billable block (Pro: 500, Team: 5000)
        sa.Column("unit_size", sa.Integer(), nullable=False),
        # Maximum overage spend per billing period in cents (NULL = no cap)
        sa.Column("budget_cap_cents", sa.Integer(), nullable=True),
        sa.UniqueConstraint("tenant_id", "metric", name="uq_overage_settings"),
    )
    op.create_index(
        "idx_overage_settings_lookup",
        "overage_settings",
        ["tenant_id", "metric"],
    )


def downgrade() -> None:
    op.drop_index("idx_overage_settings_lookup", table_name="overage_settings")
    op.drop_table("overage_settings")

    op.drop_index("idx_usage_counters_lookup", table_name="usage_counters")
    op.drop_table("usage_counters")

    op.drop_index("idx_billing_subs_customer", table_name="billing_subscriptions")
    op.drop_index("idx_billing_subs_tenant", table_name="billing_subscriptions")
    op.drop_table("billing_subscriptions")

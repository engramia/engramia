# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""BYOK tier rename: sandbox → developer + business tier introduction.

Companion DB migration to the Phase 6.6 BYOK pricing rework. Two changes:

1. Renames any existing rows where ``plan_tier='sandbox'`` to
   ``plan_tier='developer'`` across the two tables that store it
   (``billing_subscriptions`` and ``tenants``). The application code
   keeps a "sandbox" alias in ``PLAN_LIMITS`` as a defensive fallback,
   but the canonical name everywhere new is "developer".

2. Updates the ``server_default`` on ``billing_subscriptions.plan_tier``
   and ``tenants.plan_tier`` from ``'sandbox'`` to ``'developer'`` so
   future INSERTs without an explicit plan_tier land on the new name.

The "business" tier introduced in 6.6 needs no schema change — the
column is plain TEXT with no CHECK constraint enumerating tiers (the
application enforces the enum via ``PLAN_LIMITS`` membership).

This migration is safe to apply on a database with no existing
sandbox rows (it becomes a no-op UPDATE).

Revision ID: 024
Revises: 023
Create Date: 2026-04-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "024"
down_revision: str = "023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Rename existing sandbox rows.
    op.execute("UPDATE billing_subscriptions SET plan_tier = 'developer' WHERE plan_tier = 'sandbox'")
    op.execute("UPDATE tenants SET plan_tier = 'developer' WHERE plan_tier = 'sandbox'")

    # 2. Update server defaults so future INSERTs land on the new name.
    op.execute("ALTER TABLE billing_subscriptions ALTER COLUMN plan_tier SET DEFAULT 'developer'")
    op.execute("ALTER TABLE tenants ALTER COLUMN plan_tier SET DEFAULT 'developer'")


def downgrade() -> None:
    # Revert: rename developer back to sandbox + restore old defaults.
    # This is lossy if any "business" rows exist (no sandbox<->business
    # mapping); leave them on "business" and let the operator decide.
    op.execute("ALTER TABLE billing_subscriptions ALTER COLUMN plan_tier SET DEFAULT 'sandbox'")
    op.execute("ALTER TABLE tenants ALTER COLUMN plan_tier SET DEFAULT 'sandbox'")

    op.execute("UPDATE billing_subscriptions SET plan_tier = 'sandbox' WHERE plan_tier = 'developer'")
    op.execute("UPDATE tenants SET plan_tier = 'sandbox' WHERE plan_tier = 'developer'")

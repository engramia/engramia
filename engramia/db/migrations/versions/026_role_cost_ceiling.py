# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Per-role cost ceiling (Phase 6.6 #2b — Business+ tier).

Two changes:

1. ``tenant_credentials.role_cost_limits`` JSONB — per-role monthly budget
   in cents (e.g. ``{"coder": 5000}`` = $50/mo cap on the ``coder`` role).
   NULL means no ceiling (default behaviour). Empty {} means cleared.

2. ``role_spend_counters`` table — durable monthly accumulators for
   ``(tenant_id, credential_id, role, month)``. Incremented after every
   LLM call by ``role_metering.increment_spend``; read by the preflight
   ceiling gate in ``tenant_scoped`` to decide whether the next call's
   role override is still under the budget.

The counter table is intentionally separate from ``tenant_credentials``:
- High-write rate (one INSERT per LLM call) — keeps the credentials row
  stable for the LRU+TTL cache.
- Composite PK ``(tenant_id, credential_id, role, month)`` is the
  natural UPSERT target.
- ON DELETE CASCADE from credentials so a revoked credential's spend
  history goes with it (no orphan rows).

Month is stored as ``CHAR(7)`` ``YYYY-MM`` UTC — same format used by
``billing/metering.py`` for the eval_runs counter so dashboards have
consistent grouping keys.

Revision ID: 026
Revises: 025
Create Date: 2026-04-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "026"
down_revision: str = "025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_credentials ADD COLUMN role_cost_limits JSONB")

    op.execute("""
        CREATE TABLE role_spend_counters (
            tenant_id     TEXT NOT NULL,
            credential_id TEXT NOT NULL REFERENCES tenant_credentials(id) ON DELETE CASCADE,
            role          TEXT NOT NULL,
            month         CHAR(7) NOT NULL,
            spend_cents   BIGINT NOT NULL DEFAULT 0,
            tokens_in     BIGINT NOT NULL DEFAULT 0,
            tokens_out    BIGINT NOT NULL DEFAULT 0,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, credential_id, role, month)
        )
    """)
    # Lookup index for "list this tenant's role spend in current month" —
    # the dashboard's per-role budget bar reads via this. Without it the
    # query falls back to a PK-prefix scan that pulls every month.
    op.execute(
        "CREATE INDEX idx_role_spend_counters_tenant_month "
        "ON role_spend_counters (tenant_id, month)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_role_spend_counters_tenant_month")
    op.execute("DROP TABLE IF EXISTS role_spend_counters")
    op.execute("ALTER TABLE tenant_credentials DROP COLUMN IF EXISTS role_cost_limits")

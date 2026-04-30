# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""tenant_credentials.failover_chain — provider failover for Business+ tier.

Adds a JSONB column holding an ordered list of credential IDs to fall back to
when the primary credential's LLM call hits a transient error (5xx, timeout,
network). Auth errors on the primary never trigger failover — they fail fast
so the tenant sees the rotation/revocation signal directly.

The list contains other ``tenant_credentials.id`` values within the same
tenant. Cross-tenant references are blocked at the API layer (defence in
depth) — the column itself is plain JSONB without a foreign-key constraint
because PostgreSQL does not support FK into JSONB elements.

NULL means "no failover" (default behaviour). Length is enforced at the API
layer (max 2 fallback entries → 3 total chain steps).

This migration is purely additive — existing rows get NULL, no data
backfill, no application restart required for the schema change itself
(the read path tolerates ``failover_chain IS NULL``).

Revision ID: 025
Revises: 024
Create Date: 2026-04-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "025"
down_revision: str = "024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_credentials ADD COLUMN failover_chain JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_credentials DROP COLUMN IF EXISTS failover_chain")

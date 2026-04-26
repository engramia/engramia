# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""memory_data / memory_embeddings: composite (tenant, project, key) PK.

Migration 003 originally kept the bare ``key`` column as the primary key
(legacy from 001 where the constraint name is still ``brain_data_pkey``).
Migration 009 layered a UNIQUE(tenant_id, project_id, key) constraint on
top so that ``ON CONFLICT (tenant_id, project_id, key)`` upserts could
target the scope-aware identity, but the global PK on ``key`` survived
"to avoid a full table rewrite" (009 docstring).

That deferred rewrite has bitten us in production-shaped tests:

- Stores that wrote a constant or hard-coded-default-scope key
  (``metrics/_global``, ``evals/default/default/_list``) succeeded for
  the first tenant and then tripped the global PK for every tenant
  after — silently turning ``POST /v1/learn`` into a bare uvicorn
  500 (fixed by 56fc61d at the application layer; this migration
  closes the underlying constraint).
- Any future store that picks an unscoped key would hit the same
  cliff with no operational warning.

Drop the bare PK and promote the existing scope-aware UNIQUE to the
real primary key. Migration 009's ``uq_*_scope_key`` constraints
become redundant once the PK is composite, so we drop them too. ON
CONFLICT clauses already target the composite tuple — they keep
working because PostgreSQL resolves the conflict by column list,
not by constraint name.

Index hygiene: PostgreSQL automatically backs the new PK with a
unique B-tree index. The old ``brain_data_pkey`` index drops with
the constraint.

Revision ID: 019
Revises: 018
Create Date: 2026-04-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "019"
down_revision: str = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # memory_data
    op.execute("ALTER TABLE memory_data DROP CONSTRAINT IF EXISTS brain_data_pkey")
    op.execute("ALTER TABLE memory_data DROP CONSTRAINT IF EXISTS memory_data_pkey")
    op.execute("ALTER TABLE memory_data DROP CONSTRAINT IF EXISTS uq_memory_data_scope_key")
    op.execute("ALTER TABLE memory_data ADD PRIMARY KEY (tenant_id, project_id, key)")

    # memory_embeddings — same shape, same fix
    op.execute("ALTER TABLE memory_embeddings DROP CONSTRAINT IF EXISTS brain_embeddings_pkey")
    op.execute("ALTER TABLE memory_embeddings DROP CONSTRAINT IF EXISTS memory_embeddings_pkey")
    op.execute("ALTER TABLE memory_embeddings DROP CONSTRAINT IF EXISTS uq_memory_embeddings_scope_key")
    op.execute("ALTER TABLE memory_embeddings ADD PRIMARY KEY (tenant_id, project_id, key)")


def downgrade() -> None:
    # Best-effort revert. Will fail if any two tenants share the same key
    # string (which is exactly the situation the upgrade was meant to
    # support); operators rolling back must scrub duplicates first.
    op.execute("ALTER TABLE memory_data DROP CONSTRAINT IF EXISTS memory_data_pkey")
    op.execute("ALTER TABLE memory_data ADD PRIMARY KEY (key)")
    op.execute("ALTER TABLE memory_data ADD CONSTRAINT uq_memory_data_scope_key UNIQUE (tenant_id, project_id, key)")

    op.execute("ALTER TABLE memory_embeddings DROP CONSTRAINT IF EXISTS memory_embeddings_pkey")
    op.execute("ALTER TABLE memory_embeddings ADD PRIMARY KEY (key)")
    op.execute(
        "ALTER TABLE memory_embeddings ADD CONSTRAINT uq_memory_embeddings_scope_key "
        "UNIQUE (tenant_id, project_id, key)"
    )

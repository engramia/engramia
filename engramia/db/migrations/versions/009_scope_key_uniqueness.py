# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Security: scope-aware unique key identity for memory_data and memory_embeddings.

Problem:
    The primary key on both tables was the bare ``key`` column. Two different
    tenants or projects could therefore share a key string, and an upsert
    (ON CONFLICT (key)) would silently overwrite a row belonging to another
    scope.

Fix:
    Add composite unique constraints (tenant_id, project_id, key) so that
    ON CONFLICT can target the scope-aware constraint instead of the bare PK.
    The PK itself stays as ``key`` to avoid a full table rewrite, but the
    unique constraint enforces the correct identity invariant.

Revision ID: 009
Revises: 008
Create Date: 2026-04-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "009"
down_revision: str = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_memory_data_scope_key",
        "memory_data",
        ["tenant_id", "project_id", "key"],
    )
    op.create_unique_constraint(
        "uq_memory_embeddings_scope_key",
        "memory_embeddings",
        ["tenant_id", "project_id", "key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_memory_embeddings_scope_key", "memory_embeddings", type_="unique")
    op.drop_constraint("uq_memory_data_scope_key", "memory_data", type_="unique")

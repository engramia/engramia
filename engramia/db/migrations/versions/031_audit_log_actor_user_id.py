# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Audit log — dedicated ``actor_user_id`` column for cloud-JWT actors.

Until now the audit pipeline packed the cloud user UUID into ``key_id``
as ``cloud:USER_ID`` because there was no other column to put it in. Add
a real ``actor_user_id TEXT NULL`` column so cloud-auth events can record
the user identity in a typed slot, separate from API-key callers.

Existing ``cloud:*`` rows in ``key_id`` are not rewritten by this
migration — the historical data stays intact and the API ``actor`` field
falls back to ``COALESCE(actor_user_id, key_id)`` for display.

Revision ID: 031
Revises: 030
Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers.
revision: str = "031"
down_revision: str | None = "030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_log",
        sa.Column("actor_user_id", sa.Text(), nullable=True),
    )
    # Index supports the optional ``?actor_user_id=...`` filter on
    # /v1/audit. Tenant scope is already covered by idx_audit_log_tenant.
    op.create_index(
        "idx_audit_log_actor_user",
        "audit_log",
        ["tenant_id", "actor_user_id"],
        postgresql_where=sa.text("actor_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_audit_log_actor_user", table_name="audit_log")
    op.drop_column("audit_log", "actor_user_id")

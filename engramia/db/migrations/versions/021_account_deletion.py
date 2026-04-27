# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Self-service account deletion: tokens table + cloud_users soft-delete columns.

Adds an ``account_deletion_requests`` table that mirrors the email-verification
flow (single-use, hashed token, 24h TTL). Adds ``deleted_at`` and
``deletion_reason`` columns to ``cloud_users`` so account deletion is a
two-phase soft-delete (immediate anonymisation + 30-day grace window before
final hard-delete by the cleanup CLI).

Revision ID: 021
Revises: 020
Create Date: 2026-04-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "021"
down_revision: str = "020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE account_deletion_requests (
            token_hash TEXT PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES cloud_users(id) ON DELETE CASCADE,
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_account_deletion_user ON account_deletion_requests(user_id)")
    op.execute("CREATE INDEX idx_account_deletion_expires ON account_deletion_requests(expires_at)")

    op.add_column(
        "cloud_users",
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "cloud_users",
        sa.Column("deletion_reason", sa.Text(), nullable=True),
    )
    op.execute("CREATE INDEX idx_cloud_users_deleted_at ON cloud_users(deleted_at) WHERE deleted_at IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_cloud_users_deleted_at")
    op.drop_column("cloud_users", "deletion_reason")
    op.drop_column("cloud_users", "deleted_at")
    op.execute("DROP INDEX IF EXISTS idx_account_deletion_expires")
    op.execute("DROP INDEX IF EXISTS idx_account_deletion_user")
    op.execute("DROP TABLE IF EXISTS account_deletion_requests")

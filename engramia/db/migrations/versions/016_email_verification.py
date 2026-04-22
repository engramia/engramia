# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Email verification: tokens table + reminder tracking on cloud_users.

Adds a single-use verification token per pending user, plus a column to
track when a reminder email has been sent so the cleanup job doesn't
re-notify the same user on consecutive runs.

Revision ID: 016
Revises: 015
Create Date: 2026-04-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "016"
down_revision: str = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE email_verification_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES cloud_users(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_email_verif_user ON email_verification_tokens(user_id)")
    op.execute("CREATE INDEX idx_email_verif_expires ON email_verification_tokens(expires_at)")

    op.add_column(
        "cloud_users",
        sa.Column("reminder_sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cloud_users", "reminder_sent_at")
    op.execute("DROP INDEX IF EXISTS idx_email_verif_expires")
    op.execute("DROP INDEX IF EXISTS idx_email_verif_user")
    op.execute("DROP TABLE IF EXISTS email_verification_tokens")

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""api_keys.expires_at: convert TEXT to TIMESTAMPTZ to fix expiry comparison.

The original column was TEXT and the auth lookup used ``expires_at > now()::text``.
That comparison is broken for ISO-8601 inputs that use the ``T`` separator
(e.g. ``2026-04-25T09:37:55+00:00``) because PostgreSQL's ``now()::text``
emits a space separator (``2026-04-25 09:37:55+00``). Lexically ``T`` (0x54)
is greater than space (0x20), so any ``T``-format expires_at compares as
"in the future" regardless of the actual time — the key never expires.

This migration converts the column to TIMESTAMPTZ. Combined with the
auth.py change to ``expires_at > now()`` (no ``::text`` cast), expiry now
works correctly regardless of the input format.

Existing TEXT values are parsed via ``USING expires_at::timestamptz``,
which PostgreSQL accepts for both ``T`` and space separators.

Revision ID: 017
Revises: 016
Create Date: 2026-04-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "017"
down_revision: str = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE api_keys
        ALTER COLUMN expires_at TYPE TIMESTAMPTZ
        USING (
            CASE
                WHEN expires_at IS NULL OR expires_at = '' THEN NULL
                ELSE expires_at::timestamptz
            END
        )
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE api_keys
        ALTER COLUMN expires_at TYPE TEXT
        USING (
            CASE
                WHEN expires_at IS NULL THEN NULL
                ELSE to_char(expires_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS+00')
            END
        )
    """)

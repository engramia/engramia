# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Waitlist + force-change-password (cloud onboarding Variant A).

Two additive changes to support manual admin onboarding at public launch:

1. **New ``waitlist_requests`` table.** Persists every access-request
   submitted via the marketing site form. Rows transition through
   ``pending → approved | rejected``; on approve, ``tenant_id`` links
   back to the freshly-created tenant for audit trail. The architecture
   is documented in
   ``Ops/internal/cloud-onboarding-architecture.md`` (COMP-007, ADR-002).

2. **New ``cloud_users.must_change_password`` column.** Boolean,
   ``NOT NULL DEFAULT FALSE``. Set to ``true`` whenever the admin CLI
   provisions an account (``engramia waitlist approve`` and
   ``engramia cloud create-account``); cleared by
   ``POST /auth/change-password`` on the user's first login. Existing
   self-registered users keep ``false`` and are unaffected. See ADR-007.

Both operations are non-destructive — no existing data is modified or
moved.

Revision ID: 029
Revises: 028
Create Date: 2026-05-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "029"
down_revision: str = "028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE waitlist_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT NOT NULL,
            name TEXT NOT NULL,
            plan_interest TEXT NOT NULL
                CHECK (plan_interest IN ('developer','pro','team','business','enterprise')),
            country TEXT NOT NULL,
            use_case TEXT,
            company_name TEXT,
            referral_source TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','approved','rejected')),
            rejection_reason TEXT,
            tenant_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            approved_at TIMESTAMPTZ,
            rejected_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_waitlist_status ON waitlist_requests(status, created_at)")
    op.execute("CREATE INDEX idx_waitlist_email ON waitlist_requests(email)")

    op.add_column(
        "cloud_users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("cloud_users", "must_change_password")
    op.execute("DROP INDEX IF EXISTS idx_waitlist_email")
    op.execute("DROP INDEX IF EXISTS idx_waitlist_status")
    op.execute("DROP TABLE IF EXISTS waitlist_requests")

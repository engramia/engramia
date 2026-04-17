# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""M-02: Persist JWT revocation blocklist to database.

Adds a revoked_jtis table to survive server restarts. JTIs are inserted on
logout and checked at token validation time. Expired rows are cleaned up
periodically by the application.

Revision ID: 015
Revises: 014
Create Date: 2026-04-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: str = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "revoked_jtis",
        sa.Column("jti", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("jti"),
    )
    op.create_index("idx_revoked_jtis_expires_at", "revoked_jtis", ["expires_at"])


def downgrade() -> None:
    op.drop_index("idx_revoked_jtis_expires_at", table_name="revoked_jtis")
    op.drop_table("revoked_jtis")

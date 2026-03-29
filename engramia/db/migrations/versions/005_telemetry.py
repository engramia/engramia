# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Phase 5.5: Observability — add request_id to jobs table.

Adds a nullable ``request_id`` TEXT column to the ``jobs`` table so that
async job executions can be correlated back to the originating HTTP request.

Revision ID: 005
Revises: 004
Create Date: 2026-03-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("request_id", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "request_id")

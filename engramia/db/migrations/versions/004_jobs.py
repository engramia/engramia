# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Phase 5.4: Async job queue table.

Creates the ``jobs`` table for DB-backed async job processing.
Uses PostgreSQL ``SELECT ... FOR UPDATE SKIP LOCKED`` pattern
for competing-consumer job claims without external queue infrastructure.

Revision ID: 004
Revises: 003
Create Date: 2026-03-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Text(), primary_key=True),  # UUID as string
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("project_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("key_id", sa.Text(), nullable=True),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.SmallInteger(), nullable=False, server_default="3"),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.Column("scheduled_at", sa.Text(), nullable=True),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.Text(), nullable=True),
    )

    # Index for efficient job polling: pending jobs ordered by creation time
    op.create_index("idx_jobs_poll", "jobs", ["status", "created_at"])

    # Index for tenant-scoped job listing
    op.create_index("idx_jobs_tenant", "jobs", ["tenant_id", "project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_jobs_tenant", table_name="jobs")
    op.drop_index("idx_jobs_poll", table_name="jobs")
    op.drop_table("jobs")

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""GDPR DSR tracking: add dsr_requests table.

Adds a durable queue for Data Subject Requests (GDPR Art. 15-20)
with SLA deadline tracking.

Revision ID: 010
Revises: 009
Create Date: 2026-04-05
"""

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: str = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dsr_requests",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("request_type", sa.Text, nullable=False),
        sa.Column("subject_email", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("deadline", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.Column("completed_at", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
    )
    op.create_index("ix_dsr_requests_tenant_id", "dsr_requests", ["tenant_id"])
    op.create_index("ix_dsr_requests_status", "dsr_requests", ["status"])
    op.create_index("ix_dsr_requests_deadline", "dsr_requests", ["deadline"])


def downgrade() -> None:
    op.drop_table("dsr_requests")

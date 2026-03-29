# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Phase 5.6: Data Governance + Privacy.

Adds governance columns to support retention policies, data classification,
PII redaction tracking, and GDPR-compliant scoped deletion/export.

Changes:
- tenants: retention_days, deleted_at
- projects: retention_days, default_classification, redaction_enabled, deleted_at
- memory_data: classification, source, run_id, author, redacted, expires_at
- audit_log: detail (JSONB for structured event context)
- Indexes: expires_at (partial), classification

Revision ID: 006
Revises: 005
Create Date: 2026-03-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "006"
down_revision: str = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # tenants — retention + soft-delete
    # ------------------------------------------------------------------
    op.add_column("tenants", sa.Column("retention_days", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("deleted_at", sa.Text(), nullable=True))

    # ------------------------------------------------------------------
    # projects — retention policy + classification default + redaction
    # ------------------------------------------------------------------
    op.add_column("projects", sa.Column("retention_days", sa.Integer(), nullable=True))
    op.add_column(
        "projects",
        sa.Column("default_classification", sa.Text(), nullable=False, server_default="internal"),
    )
    op.add_column(
        "projects",
        sa.Column("redaction_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("projects", sa.Column("deleted_at", sa.Text(), nullable=True))

    # ------------------------------------------------------------------
    # memory_data — governance metadata per pattern
    # ------------------------------------------------------------------
    op.add_column(
        "memory_data",
        sa.Column("classification", sa.Text(), nullable=False, server_default="internal"),
    )
    op.add_column(
        "memory_data",
        sa.Column("source", sa.Text(), nullable=True),  # 'api' | 'sdk' | 'cli' | 'import'
    )
    op.add_column(
        "memory_data",
        sa.Column("run_id", sa.Text(), nullable=True),  # caller-supplied correlation ID
    )
    op.add_column(
        "memory_data",
        sa.Column("author", sa.Text(), nullable=True),  # key_id or identifier
    )
    op.add_column(
        "memory_data",
        sa.Column("redacted", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "memory_data",
        sa.Column("expires_at", sa.Text(), nullable=True),  # ISO-8601 UTC, None = no expiry
    )

    # Partial index for fast expired-pattern sweeps
    op.create_index(
        "idx_memory_data_expires",
        "memory_data",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    # Index for classification-filtered export / access control
    op.create_index(
        "idx_memory_data_classification",
        "memory_data",
        ["tenant_id", "classification"],
    )

    # ------------------------------------------------------------------
    # audit_log — structured detail field for richer event context
    # ------------------------------------------------------------------
    op.add_column("audit_log", sa.Column("detail", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_log", "detail")

    op.drop_index("idx_memory_data_classification", table_name="memory_data")
    op.drop_index("idx_memory_data_expires", table_name="memory_data")
    op.drop_column("memory_data", "expires_at")
    op.drop_column("memory_data", "redacted")
    op.drop_column("memory_data", "author")
    op.drop_column("memory_data", "run_id")
    op.drop_column("memory_data", "source")
    op.drop_column("memory_data", "classification")

    op.drop_column("projects", "deleted_at")
    op.drop_column("projects", "redaction_enabled")
    op.drop_column("projects", "default_classification")
    op.drop_column("projects", "retention_days")

    op.drop_column("tenants", "deleted_at")
    op.drop_column("tenants", "retention_days")

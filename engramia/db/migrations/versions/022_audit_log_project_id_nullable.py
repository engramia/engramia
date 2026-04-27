# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""audit_log.project_id: drop NOT NULL for tenant-level events.

Account-level events (e.g. ``account_deletion_requested``,
``account_deletion_completed``) are scoped at the tenant level and have no
single owning project. The previous ``NOT NULL`` constraint forced callers to
invent a sentinel project id, which conflicted with the cloud-auth JWT (which
carries ``tenant_id`` only — never a project id).

Down-migration is best-effort: any rows inserted with NULL project_id will be
backfilled to ``'-'`` so the column can be re-tightened.

Revision ID: 022
Revises: 021
Create Date: 2026-04-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "022"
down_revision: str = "021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit_log ALTER COLUMN project_id DROP NOT NULL")


def downgrade() -> None:
    op.execute("UPDATE audit_log SET project_id = '-' WHERE project_id IS NULL")
    op.execute("ALTER TABLE audit_log ALTER COLUMN project_id SET NOT NULL")

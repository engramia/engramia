# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""J-03: Add max_execution_seconds to jobs table.

Adds an optional per-job maximum execution time in seconds. When set, the job
worker actively cancels the job if it runs longer than this limit rather than
waiting for the passive TTL reaper to fire.

Revision ID: 014
Revises: 013
Create Date: 2026-04-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: str = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("max_execution_seconds", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "max_execution_seconds")

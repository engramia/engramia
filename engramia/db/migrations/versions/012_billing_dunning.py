# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Billing: add past_due_since column for dunning grace-period tracking.

When a subscription transitions to past_due, the application records the
timestamp of the first payment failure in this column.  Access is granted
for 7 days from that timestamp; after 7 days HTTP 402 is returned.

The column is cleared (set to NULL) when the subscription becomes active
again (invoice.paid webhook), so the grace-period clock resets cleanly
on successful retry.

Revision ID: 012
Revises: 011
Create Date: 2026-04-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: str = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "billing_subscriptions",
        sa.Column("past_due_since", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("billing_subscriptions", "past_due_since")

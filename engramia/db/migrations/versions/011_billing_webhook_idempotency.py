# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Billing: add processed_webhook_events table for Stripe webhook idempotency.

Stripe guarantees at-least-once delivery, so the same event can arrive
multiple times. This table records the Stripe event ID of every successfully
processed event, allowing the webhook handler to skip duplicates and prevent
double-charging on overage invoice items.

Revision ID: 011
Revises: 010
Create Date: 2026-04-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: str = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # stripe_event_id is the PK — Stripe event IDs are globally unique strings
    # (e.g. "evt_1AbcDef..."). Using them directly as PK makes the idempotency
    # check a single indexed lookup with no secondary dedup key required.
    op.create_table(
        "processed_webhook_events",
        sa.Column("stripe_event_id", sa.Text(), primary_key=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "processed_at",
            sa.Text(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("processed_webhook_events")

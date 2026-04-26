# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Billing: add cancel_at_period_end column to surface scheduled cancellations.

Stripe Customer Portal's default cancel flow is "at period end": Stripe
sets ``cancel_at_period_end=true`` on the Subscription, fires
``customer.subscription.updated`` (the subscription stays ``active``
through the rest of the billing period), and only fires
``customer.subscription.deleted`` once the period actually ends.

Without storing the flag, the Engramia dashboard can't tell the
difference between "active and renewing" and "active but ending
on current_period_end". Add a column so the billing UI can show
"Subscription cancelled — active until <date>".

Revision ID: 020
Revises: 019
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "020"
down_revision: str = "019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "billing_subscriptions",
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("billing_subscriptions", "cancel_at_period_end")

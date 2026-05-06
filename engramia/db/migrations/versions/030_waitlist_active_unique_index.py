# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Waitlist active-row UNIQUE constraint (race-safe silent dedup).

Adds a partial unique index on ``waitlist_requests(email)`` covering only
``status IN ('pending','approved')``. Closes the race window that the
prior application-layer dedup in ``submit_waitlist_request`` could not
fully guard: two concurrent POSTs with the same email could both pass
the SELECT-not-found check and both INSERT. With this index the
race-loser hits ``ON CONFLICT DO NOTHING`` and the handler silently
re-fetches the race winner — same shape, same enumeration-safe response.

Pre-existing duplicates are collapsed before the index is created: for
each email with multiple ``pending``/``approved`` rows the canonical row
is the earliest ``approved`` (admin already acted on it), or — if no
``approved`` exists — the earliest ``pending``. All other rows in that
email's active set are flipped to ``status='rejected'`` with a synthetic
``rejection_reason`` so the original audit trail is preserved.

``status='rejected'`` rows are intentionally NOT covered by the unique
constraint — a rejected applicant may legitimately resubmit with
corrected info.

Revision ID: 030
Revises: 029
Create Date: 2026-05-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "030"
down_revision: str = "029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Step 1 — collapse pre-existing duplicates. Within each email's set
    # of pending/approved rows, rank by status (approved first, then
    # pending), then by created_at, then by id (UUID tiebreaker). Keep
    # rank 1, flip everything else to rejected.
    op.execute("""
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY email
                    ORDER BY
                        CASE status WHEN 'approved' THEN 0 ELSE 1 END,
                        created_at,
                        id
                ) AS rn
            FROM waitlist_requests
            WHERE status IN ('pending', 'approved')
        )
        UPDATE waitlist_requests w
        SET
            status = 'rejected',
            rejected_at = COALESCE(w.rejected_at, now()),
            rejection_reason = COALESCE(
                w.rejection_reason,
                'Auto-collapsed: superseded by earlier submission '
                '(waitlist dedup migration 030).'
            )
        FROM ranked r
        WHERE w.id = r.id AND r.rn > 1
    """)

    # Step 2 — partial unique index. Application code (waitlist.py) now
    # relies on this index for ON CONFLICT DO NOTHING; the predicate
    # below MUST stay byte-identical to the WHERE clause in that INSERT
    # for PostgreSQL to infer the arbiter index correctly.
    op.execute("""
        CREATE UNIQUE INDEX uq_waitlist_active
        ON waitlist_requests (email)
        WHERE status IN ('pending', 'approved')
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_waitlist_active")
    # Step 1 (the duplicate collapse) is intentionally not reversed —
    # the rejected-status flip is non-destructive (rows preserved) and
    # reverting would require either a backup restore or a separate
    # audit-trail migration. If you need the duplicates back, restore
    # from the backup taken before running migration 030.

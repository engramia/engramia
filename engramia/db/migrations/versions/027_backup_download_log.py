# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""backup_download_log: rate-limit + audit ledger for self-service backup download.

Phase 6.6 #5 — Team+ tenants can pull a streaming NDJSON dump of their own
data via ``GET /v1/governance/backup/download``. Two responsibilities for
this table:

1. **Rate limit**: enforce 1 download per tenant per 24 h. The route handler
   reads the most recent ``status='success'`` row before serving and returns
   429 if it's within the window. Failed attempts (``status='failed'``) do
   not count against the rate limit so a tenant can retry after a transient
   failure.

2. **Audit + cost accounting**: every download (success or failure) is
   logged with the requesting key id, byte count, and table count. This is
   surfaced in the audit log viewer (admin+) so tenants can see who pulled
   their own data and when.

The table is intentionally separate from ``audit_log``:

- High-cardinality (one row per download) but low absolute volume (1/day/
  tenant max); doesn't bloat the general audit log.
- The rate-limit check is a tight ``SELECT ... ORDER BY requested_at DESC
  LIMIT 1`` on a focused B-tree index — keeping it out of the audit-log
  hot path keeps the audit query plan stable.
- Operator wants to drop / scrub backup history independently of compliance
  audit retention.

ON DELETE CASCADE from tenants so an account-deletion request wipes
download history alongside the rest of the tenant's data.

Revision ID: 027
Revises: 026
Create Date: 2026-04-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "027"
down_revision: str = "026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE backup_download_log (
            id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
            tenant_id       TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            requested_by    TEXT NOT NULL,
            requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            status          TEXT NOT NULL,
            bytes_streamed  BIGINT NOT NULL DEFAULT 0,
            tables_exported INTEGER NOT NULL DEFAULT 0,
            error_message   TEXT,
            CONSTRAINT backup_download_log_status_check
                CHECK (status IN ('success', 'failed', 'in_progress'))
        )
    """)

    # Hot-path index: rate-limit check reads the most recent success per
    # tenant. Partial index on status='success' keeps it small.
    op.execute("""
        CREATE INDEX ix_backup_download_log_tenant_recent_success
        ON backup_download_log (tenant_id, requested_at DESC)
        WHERE status = 'success'
    """)

    # Audit log viewer query path: list all attempts per tenant ordered by
    # time, including failures. Full index without the partial filter.
    op.execute("""
        CREATE INDEX ix_backup_download_log_tenant_all
        ON backup_download_log (tenant_id, requested_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS backup_download_log")

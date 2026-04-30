# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Credential backend column (Phase 6.6 #6 — Vault Transit support).

Two changes to ``tenant_credentials`` to support a pluggable backend:

1. **Rename ``encrypted_key`` → ``ciphertext_blob``.** The column already
   stores opaque encrypted bytes; the new name is backend-agnostic.
   For the local (AES-GCM) backend the bytes are the AES ciphertext
   without the tag (we keep a separate ``auth_tag`` column). For the
   Vault Transit backend the bytes will be the UTF-8 of Vault's
   ``vault:vN:...`` ciphertext string. ``nonce`` and ``auth_tag``
   columns stay — for vault rows they are simply ``b''`` (empty), keeping
   schema uniform.

2. **Add ``backend TEXT NOT NULL DEFAULT 'local'``.** Per-row dispatch
   marker. The default keeps every existing row resolvable through
   ``LocalAESGCMBackend`` with zero data movement; the bulk migration
   script (``engramia credentials migrate-to-vault``) flips rows to
   ``'vault'`` after re-encryption.

Both operations are metadata-only on PostgreSQL ≥11 — no table rewrite,
no row-level lock, no downtime.

See ``Ops/internal/vault-credential-backend-architecture.md`` ADR-001
for the design rationale.

Revision ID: 028
Revises: 027
Create Date: 2026-04-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "028"
down_revision: str = "027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rename — pure metadata operation, no row writes.
    op.execute("ALTER TABLE tenant_credentials RENAME COLUMN encrypted_key TO ciphertext_blob")

    # Add backend column with a constant DEFAULT — metadata-only on PG ≥11.
    op.execute(
        "ALTER TABLE tenant_credentials "
        "ADD COLUMN backend TEXT NOT NULL DEFAULT 'local' "
        "CHECK (backend IN ('local', 'vault'))"
    )

    # Index for the bulk-migration script's WHERE clause. Cardinality is
    # low (2 values) but the script will hammer it with ORDER BY id LIMIT
    # batches — without the index that's a sequential scan per batch.
    op.execute("CREATE INDEX idx_tenant_credentials_backend ON tenant_credentials (backend)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tenant_credentials_backend")
    op.execute("ALTER TABLE tenant_credentials DROP COLUMN IF EXISTS backend")
    op.execute("ALTER TABLE tenant_credentials RENAME COLUMN ciphertext_blob TO encrypted_key")

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""audit_log.key_id: drop FK to api_keys for cross-auth-mode compatibility.

The original ``audit_log.key_id`` column had a foreign key to ``api_keys.id``,
assuming every authenticated principal corresponded to a row in ``api_keys``.
That assumption broke once we added other auth modes:

- Env-mode auth uses the literal string ``"env-key"`` as key_id.
- Cloud-JWT auth uses ``"cloud:<user_id>"`` (cloud user, not an api_key).
- OIDC auth uses the JWT subject claim.

None of these are valid ``api_keys.id`` values, so any audit_log INSERT from
those auth modes failed with a FK violation. ``log_db_event`` swallows the
error, leaving the audit_log silently empty for non-DB-key auth.

We drop the FK rather than rename the column or normalise key_id values: the
audit trail records *who* acted, and the identifier semantics depend on the
auth mode in use. Cross-table integrity isn't load-bearing here.

Revision ID: 018
Revises: 017
Create Date: 2026-04-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "018"
down_revision: str = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_key_id_fkey")


def downgrade() -> None:
    # Best-effort restore. Will fail if existing rows have key_id values that
    # do not correspond to api_keys.id (e.g. cloud:* or env-key strings written
    # after this migration). A real rollback would need to scrub those rows.
    op.execute(
        "ALTER TABLE audit_log ADD CONSTRAINT audit_log_key_id_fkey FOREIGN KEY (key_id) REFERENCES api_keys(id)"
    )

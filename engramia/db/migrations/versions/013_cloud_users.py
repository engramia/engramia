# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Cloud auth: add cloud_users table for web registration and OAuth logins.

Stores email/password (bcrypt) and OAuth (Google/Apple) identities.
Each user owns exactly one tenant, created automatically at registration.

Revision ID: 013
Revises: 012
Create Date: 2026-04-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "013"
down_revision: str = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE cloud_users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT,
            tenant_id TEXT NOT NULL,
            name TEXT,
            provider TEXT DEFAULT 'credentials',
            provider_id TEXT,
            email_verified BOOLEAN DEFAULT false,
            email_verified_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT now(),
            last_login_at TIMESTAMPTZ,
            CONSTRAINT cloud_users_tenant_fk FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        )
    """)
    op.execute("CREATE INDEX idx_cloud_users_email ON cloud_users(email)")
    op.execute("CREATE INDEX idx_cloud_users_tenant ON cloud_users(tenant_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_cloud_users_tenant")
    op.execute("DROP INDEX IF EXISTS idx_cloud_users_email")
    op.execute("DROP TABLE IF EXISTS cloud_users")

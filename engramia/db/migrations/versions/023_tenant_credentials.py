# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""tenant_credentials: per-tenant LLM provider keys for BYOK.

Adds a ``tenant_credentials`` table that stores AES-256-GCM-encrypted LLM
provider API keys (one row per tenant + provider + purpose triple). Plaintext
keys never enter the database — only the ciphertext, nonce, auth tag, and a
fingerprint suffix safe to display in the UI.

The encryption key (``ENGRAMIA_CREDENTIALS_KEY``) lives in the operator's
environment (SOPS-encrypted) — not in the DB. Loss of the master key is
unrecoverable; backups must be stored separately.

UNIQUE ``(tenant_id, provider, purpose)`` enforces "one key per role per
tenant" — a tenant may hold both ``(openai, llm)`` and ``(openai, embedding)``
rows distinctly. Replacing a key is a server-side UPSERT on this triple.

Cascading delete from ``tenants`` so that account deletion automatically wipes
credentials. The partial index on ``status != 'active'`` keeps the common
"active credentials only" lookup small even if revoked rows accumulate.

Revision ID: 023
Revises: 022
Create Date: 2026-04-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "023"
down_revision: str = "022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE tenant_credentials (
            id                    TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
            tenant_id             TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            provider              TEXT NOT NULL,
            purpose               TEXT NOT NULL,
            encrypted_key         BYTEA NOT NULL,
            nonce                 BYTEA NOT NULL,
            auth_tag              BYTEA NOT NULL,
            key_version           SMALLINT NOT NULL DEFAULT 1,
            key_fingerprint       TEXT NOT NULL,
            base_url              TEXT,
            default_model         TEXT,
            default_embed_model   TEXT,
            role_models           JSONB,
            status                TEXT NOT NULL DEFAULT 'active',
            last_used_at          TIMESTAMPTZ,
            last_validated_at     TIMESTAMPTZ,
            last_validation_error TEXT,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by            TEXT NOT NULL,
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX uq_tenant_credentials_provider_purpose "
        "ON tenant_credentials (tenant_id, provider, purpose)"
    )
    op.execute("CREATE INDEX idx_tenant_credentials_tenant ON tenant_credentials (tenant_id)")
    op.execute("CREATE INDEX idx_tenant_credentials_status ON tenant_credentials (status) WHERE status != 'active'")
    # CHECK constraints catch typos before they corrupt data; cheap at insert
    # time and document the expected vocabulary directly in the schema.
    op.execute("""
        ALTER TABLE tenant_credentials
        ADD CONSTRAINT ck_tenant_credentials_provider
        CHECK (provider IN ('openai', 'anthropic', 'gemini', 'ollama', 'openai_compat'))
    """)
    op.execute("""
        ALTER TABLE tenant_credentials
        ADD CONSTRAINT ck_tenant_credentials_purpose
        CHECK (purpose IN ('llm', 'embedding', 'both'))
    """)
    op.execute("""
        ALTER TABLE tenant_credentials
        ADD CONSTRAINT ck_tenant_credentials_status
        CHECK (status IN ('active', 'revoked', 'invalid'))
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tenant_credentials_status")
    op.execute("DROP INDEX IF EXISTS idx_tenant_credentials_tenant")
    op.execute("DROP INDEX IF EXISTS uq_tenant_credentials_provider_purpose")
    op.execute("DROP TABLE IF EXISTS tenant_credentials")

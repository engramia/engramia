# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Phase 5.1 + 5.2: tenant/project scope isolation + RBAC (api_keys, audit_log).

Changes:
- Add ``tenant_id``, ``project_id`` columns to ``memory_data`` and
  ``memory_embeddings`` (DEFAULT 'default' — fully backward-compatible).
- Add composite B-tree indexes on (tenant_id, project_id) for fast filtering.
- Create ``tenants`` and ``projects`` management tables with a pre-seeded
  'default' tenant and project for existing single-tenant deployments.
- Create ``api_keys`` table: hashed API keys with RBAC role + quota.
- Create ``audit_log`` table: security-relevant event trail.

Revision ID: 003
Revises: 002
Create Date: 2026-03-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Add scope columns to existing data tables (backward-compatible)
    # ------------------------------------------------------------------
    op.add_column("memory_data", sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"))
    op.add_column("memory_data", sa.Column("project_id", sa.Text(), nullable=False, server_default="default"))
    op.add_column("memory_embeddings", sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"))
    op.add_column("memory_embeddings", sa.Column("project_id", sa.Text(), nullable=False, server_default="default"))

    # ------------------------------------------------------------------
    # 2. Composite B-tree indexes for efficient scope filtering
    # ------------------------------------------------------------------
    op.create_index("idx_memory_data_scope", "memory_data", ["tenant_id", "project_id"])
    op.create_index("idx_memory_embeddings_scope", "memory_embeddings", ["tenant_id", "project_id"])

    # ------------------------------------------------------------------
    # 3. Tenant management table
    # ------------------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("plan_tier", sa.Text(), nullable=False, server_default="free"),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.func.now()),
    )
    # Seed the default tenant for existing single-tenant deployments
    op.execute("INSERT INTO tenants (id, name) VALUES ('default', 'Default')")

    # ------------------------------------------------------------------
    # 4. Project management table
    # ------------------------------------------------------------------
    op.create_table(
        "projects",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("max_patterns", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.func.now()),
    )
    # Seed the default project for existing single-tenant deployments
    op.execute("INSERT INTO projects (id, tenant_id, name) VALUES ('default', 'default', 'default')")

    # ------------------------------------------------------------------
    # 5. API keys table (RBAC)
    # ------------------------------------------------------------------
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("role", sa.Text(), nullable=False, server_default="editor"),
        sa.Column("max_patterns", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.Text(), nullable=True),
    )
    op.create_index("idx_api_keys_hash", "api_keys", ["key_hash"])

    # ------------------------------------------------------------------
    # 6. Audit log table
    # ------------------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("key_id", sa.Text(), sa.ForeignKey("api_keys.id"), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=True),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_audit_log_tenant", "audit_log", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_audit_log_tenant", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index("idx_api_keys_hash", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_table("projects")
    op.drop_table("tenants")

    op.drop_index("idx_memory_embeddings_scope", table_name="memory_embeddings")
    op.drop_index("idx_memory_data_scope", table_name="memory_data")

    op.drop_column("memory_embeddings", "project_id")
    op.drop_column("memory_embeddings", "tenant_id")
    op.drop_column("memory_data", "project_id")
    op.drop_column("memory_data", "tenant_id")

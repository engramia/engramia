# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""SQLAlchemy 2.x models for PostgreSQL + pgvector storage backend.

Schema design:
- ``memory_data``       — generic key-value store (TEXT key, JSONB data, scope columns)
- ``memory_embeddings`` — vector index (TEXT key, pgvector vector(1536), scope columns)
- ``tenants``           — top-level tenant accounts
- ``projects``          — projects within a tenant (isolation boundary)
- ``api_keys``          — hashed API keys with RBAC role + quota
- ``audit_log``         — structured audit trail for security events

The ``tenant_id`` / ``project_id`` columns on ``memory_data`` and
``memory_embeddings`` default to ``'default'`` so that existing single-tenant
data continues to work without migration of existing rows.

HNSW index on ``memory_embeddings.embedding`` enables sub-millisecond ANN
search via pgvector's ``<=>`` cosine distance operator.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, SmallInteger, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Core data tables (Phase 1/2 + scope columns added in Phase 5.1)
# ---------------------------------------------------------------------------


class MemoryData(Base):
    """Generic key-value store for all Engramia data objects."""

    __tablename__ = "memory_data"
    __table_args__ = (
        # Scope-aware unique identity: the same key in different projects is
        # a distinct row.  This prevents cross-tenant/project row collisions
        # when two scopes share an identical key string.
        UniqueConstraint("tenant_id", "project_id", "key", name="uq_memory_data_scope_key"),
    )

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    project_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    # Phase 5.6: Data Governance
    classification: Mapped[str] = mapped_column(Text, nullable=False, server_default="internal")
    source: Mapped[str | None] = mapped_column(Text, nullable=True)         # 'api'|'sdk'|'cli'|'import'
    run_id: Mapped[str | None] = mapped_column(Text, nullable=True)          # caller correlation ID
    author: Mapped[str | None] = mapped_column(Text, nullable=True)          # key_id or identifier
    redacted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    expires_at: Mapped[str | None] = mapped_column(Text, nullable=True)      # ISO-8601 UTC


class MemoryEmbedding(Base):
    """Embedding vectors stored separately for efficient pgvector indexing."""

    __tablename__ = "memory_embeddings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "key", name="uq_memory_embeddings_scope_key"),
    )

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    project_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    # Vector dimension is fixed at 1536 (OpenAI text-embedding-3-small).
    # pgvector requires a concrete dimension at DDL time.
    embedding: Mapped[list] = mapped_column(Vector(1536), nullable=False)


# Composite B-tree index for efficient scope filtering on all data queries.
scope_data_index = Index(
    "idx_memory_data_scope",
    MemoryData.tenant_id,
    MemoryData.project_id,
)

# HNSW index for cosine similarity search.
hnsw_index = Index(
    "idx_memory_embeddings_hnsw",
    MemoryEmbedding.embedding,
    postgresql_using="hnsw",
    postgresql_with={"m": 16, "ef_construction": 64},
    postgresql_ops={"embedding": "vector_cosine_ops"},
)

scope_embeddings_index = Index(
    "idx_memory_embeddings_scope",
    MemoryEmbedding.tenant_id,
    MemoryEmbedding.project_id,
)


# ---------------------------------------------------------------------------
# Tenant + Project management (Phase 5.1)
# ---------------------------------------------------------------------------


class Tenant(Base):
    """Top-level organizational unit. Each API key belongs to a tenant."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # UUID as string
    name: Mapped[str] = mapped_column(Text, nullable=False)
    plan_tier: Mapped[str] = mapped_column(Text, nullable=False, server_default="free")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())
    # Phase 5.6: Data Governance
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = use global default
    deleted_at: Mapped[str | None] = mapped_column(Text, nullable=True)          # soft-delete timestamp


class Project(Base):
    """Isolation boundary within a tenant. API keys are scoped to a project."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    max_patterns: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10000")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())
    # Phase 5.6: Data Governance
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)         # None = inherit tenant
    default_classification: Mapped[str] = mapped_column(Text, nullable=False, server_default="internal")
    redaction_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    deleted_at: Mapped[str | None] = mapped_column(Text, nullable=True)                # soft-delete timestamp


# ---------------------------------------------------------------------------
# RBAC — API Keys (Phase 5.2)
# ---------------------------------------------------------------------------


class ApiKey(Base):
    """Hashed API key with RBAC role and optional pattern quota.

    The full key is never stored. Only ``key_hash`` (SHA-256) is persisted.
    ``key_prefix`` is the first 8 chars of the suffix after ``engramia_sk_``
    — safe to display in the UI to identify which key is which.
    """

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)    # e.g. "engramia_sk_aBcD1234..."
    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # SHA-256 of full key
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="editor")
    max_patterns: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = inherit project
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())
    last_used_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Audit log (Phase 5.2)
# ---------------------------------------------------------------------------


class AuditLogEntry(Base):
    """Structured audit trail entry for security-relevant API operations."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    key_id: Mapped[str | None] = mapped_column(Text, ForeignKey("api_keys.id"), nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)        # e.g. "learn", "key_created"
    resource_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())
    # Phase 5.6: structured event context (counts, params, reason, etc.)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


audit_log_index = Index(
    "idx_audit_log_tenant",
    AuditLogEntry.tenant_id,
    AuditLogEntry.created_at,
)

# Phase 5.6: governance indexes
memory_data_classification_index = Index(
    "idx_memory_data_classification",
    MemoryData.tenant_id,
    MemoryData.classification,
)


# ---------------------------------------------------------------------------
# Async job queue (Phase 5.4)
# ---------------------------------------------------------------------------


class Job(Base):
    """DB-backed async job for long-running operations.

    Uses PostgreSQL ``SELECT ... FOR UPDATE SKIP LOCKED`` for competing-consumer
    claims without external queue infrastructure (Redis/Celery).
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    project_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    key_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="3")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())
    scheduled_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[str | None] = mapped_column(Text, nullable=True)


jobs_poll_index = Index(
    "idx_jobs_poll",
    Job.status,
    Job.created_at,
)

jobs_tenant_index = Index(
    "idx_jobs_tenant",
    Job.tenant_id,
    Job.project_id,
    Job.created_at,
)


# ---------------------------------------------------------------------------
# Billing (Phase 6)
# ---------------------------------------------------------------------------


class BillingSubscription(Base):
    """Per-tenant subscription state, synced from Stripe via webhooks.

    Local cache only — Stripe is the source of truth. Updated by the
    ``invoice.created``, ``customer.subscription.*`` webhook handlers.
    """

    __tablename__ = "billing_subscriptions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.id"), nullable=False, unique=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    plan_tier: Mapped[str] = mapped_column(Text, nullable=False, server_default="sandbox")
    billing_interval: Mapped[str] = mapped_column(Text, nullable=False, server_default="month")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    eval_runs_limit: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="500")
    patterns_limit: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="5000")
    projects_limit: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="1")
    current_period_start: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_period_end: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())


class UsageCounter(Base):
    """Rolling monthly usage counter per tenant and metric.

    Incremented atomically via INSERT ... ON CONFLICT DO UPDATE.
    Current metrics: ``eval_runs``.
    """

    __tablename__ = "usage_counters"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class OverageSettings(Base):
    """Opt-in overage billing configuration per tenant and metric.

    Pro:  $5  / 500  eval runs, optional budget cap.
    Team: $25 / 5000 eval runs, optional budget cap.
    """

    __tablename__ = "overage_settings"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    price_per_unit_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_size: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_cap_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

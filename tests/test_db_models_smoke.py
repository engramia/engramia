# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Smoke tests for SQLAlchemy ORM models.

These run without Docker/Postgres and just verify the declarative metadata
is importable and mirrors the schema produced by Alembic migrations 011-014.
Full DDL round-trip is covered by tests/test_db/test_migrations.py (postgres).
"""

from __future__ import annotations

from engramia.db.models import (
    ApiKey,
    AuditLogEntry,
    Base,
    BillingSubscription,
    CloudUser,
    DataSubjectRequest,
    Job,
    MemoryData,
    MemoryEmbedding,
    OverageSettings,
    ProcessedWebhookEvent,
    Project,
    Tenant,
    TenantCredential,
    UsageCounter,
)


def test_all_expected_tables_registered():
    """Alembic head should declare these tables — metadata must match."""
    expected = {
        "memory_data",
        "memory_embeddings",
        "tenants",
        "projects",
        "api_keys",
        "audit_log",
        "jobs",
        "billing_subscriptions",
        "usage_counters",
        "overage_settings",
        "data_subject_requests",
        "processed_webhook_events",  # migration 011
        "cloud_users",  # migration 013
        "tenant_credentials",  # migration 023
    }
    actual = set(Base.metadata.tables.keys())
    missing = expected - actual
    assert not missing, f"missing ORM tables: {missing}"


def test_job_has_max_execution_seconds_column():
    """Migration 014 adds max_execution_seconds — ORM must declare it."""
    assert "max_execution_seconds" in Job.__table__.columns
    col = Job.__table__.columns["max_execution_seconds"]
    assert col.nullable is True


def test_billing_subscription_has_past_due_since():
    """Migration 012 adds past_due_since — ORM must declare it."""
    assert "past_due_since" in BillingSubscription.__table__.columns
    col = BillingSubscription.__table__.columns["past_due_since"]
    assert col.nullable is True


def test_processed_webhook_event_pk_is_stripe_event_id():
    """Idempotency relies on Stripe event_id being the PK."""
    pk_cols = [c.name for c in ProcessedWebhookEvent.__table__.primary_key]
    assert pk_cols == ["stripe_event_id"]


def test_cloud_user_has_email_unique():
    email_col = CloudUser.__table__.columns["email"]
    assert email_col.unique is True
    assert email_col.nullable is False


def test_cloud_user_password_hash_is_nullable():
    """OAuth-only users (google/apple) have no password hash."""
    pw = CloudUser.__table__.columns["password_hash"]
    assert pw.nullable is True


def test_tenant_credential_unique_triple():
    """Migration 023 enforces UNIQUE(tenant_id, provider, purpose).
    The ORM must declare the matching constraint so SQLAlchemy DDL stays
    in sync with Alembic."""
    cols = {c.name for c in TenantCredential.__table__.columns}
    assert {"tenant_id", "provider", "purpose"}.issubset(cols)
    constraints = TenantCredential.__table__.constraints
    unique_names = {c.name for c in constraints if hasattr(c, "name") and c.name}
    assert "uq_tenant_credentials_provider_purpose" in unique_names


def test_tenant_credential_encryption_columns_are_binary():
    """encrypted_key, nonce, auth_tag must be BYTEA (LargeBinary), not TEXT —
    storing ciphertext as text would force base64 round-tripping per request."""
    from sqlalchemy import LargeBinary

    for col_name in ("encrypted_key", "nonce", "auth_tag"):
        col = TenantCredential.__table__.columns[col_name]
        assert col.nullable is False, f"{col_name} must be NOT NULL"
        assert isinstance(col.type, LargeBinary), f"{col_name} must be LargeBinary, got {type(col.type)}"


def test_tenant_credential_role_models_is_jsonb_nullable():
    """role_models is the Business-tier per-role routing column. Nullable
    because Developer/Pro tenants leave it empty."""
    col = TenantCredential.__table__.columns["role_models"]
    assert col.nullable is True


def test_tenant_credential_status_has_default():
    """Default 'active' so a freshly inserted row is immediately resolvable."""
    col = TenantCredential.__table__.columns["status"]
    assert col.nullable is False
    assert col.server_default is not None


def test_tenant_credential_cascades_on_tenant_delete():
    """When a tenant is deleted (GDPR Art. 17), credentials must cascade-
    delete so plaintext residue cannot survive an anonymisation request."""
    fk = next(iter(TenantCredential.__table__.columns["tenant_id"].foreign_keys))
    assert fk.ondelete == "CASCADE"


def test_all_models_share_one_metadata():
    """Declarative Base metadata must be consistent across modules."""
    shared = {
        MemoryData.metadata,
        MemoryEmbedding.metadata,
        Tenant.metadata,
        Project.metadata,
        ApiKey.metadata,
        AuditLogEntry.metadata,
        Job.metadata,
        BillingSubscription.metadata,
        UsageCounter.metadata,
        OverageSettings.metadata,
        DataSubjectRequest.metadata,
        ProcessedWebhookEvent.metadata,
        CloudUser.metadata,
        TenantCredential.metadata,
    }
    assert len(shared) == 1

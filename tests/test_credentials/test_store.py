# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Integration tests for engramia.credentials.store.CredentialStore.

Requires a live PostgreSQL with pgvector (testcontainers). Marked
``postgres`` so it runs in the CI release lane, not on every PR.

Coverage:
- upsert insert path → SELECT round-trip
- upsert UPSERT path → existing row replaced; status reset to 'active'
- get_active_for_purpose: exact + 'both' fallback
- patch: partial updates, role_models JSONB
- revoke: status flips to 'revoked', subsequent get returns None
- mark_invalid / mark_validated audit columns
- engine=None paths return safe defaults (no-op mode)
"""

from __future__ import annotations

from typing import Any

import pytest

from engramia.credentials.store import CredentialStore, PatchOutcome

pytestmark = pytest.mark.postgres


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine() -> Any:
    """Module-scoped pgvector container + Alembic upgrade head."""
    try:
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine, text
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers / alembic not installed")

    from pathlib import Path

    migrations_dir = str(Path(__file__).parent.parent.parent / "engramia" / "db" / "migrations")

    with PostgresContainer("pgvector/pgvector:0.7.4-pg16") as pg:
        url = pg.get_connection_url()
        cfg = Config()
        cfg.set_main_option("script_location", migrations_dir)
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        engine = create_engine(url, pool_pre_ping=True)
        # Seed a tenant + project so FK constraints are satisfied
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tenants (id, name, plan_tier) "
                    "VALUES ('tenant-test', 'test', 'pro') "
                    "ON CONFLICT (id) DO NOTHING"
                )
            )
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def store(pg_engine: Any) -> CredentialStore:
    return CredentialStore(pg_engine)


@pytest.fixture(autouse=True)
def _clean_credentials(pg_engine: Any) -> None:
    """Wipe tenant_credentials between tests so each starts fresh."""
    from sqlalchemy import text

    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM tenant_credentials"))


# ---------------------------------------------------------------------------
# upsert
# ---------------------------------------------------------------------------


class TestUpsert:
    def _kwargs(self, **overrides: Any) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "tenant_id": "tenant-test",
            "provider": "openai",
            "purpose": "llm",
            "encrypted_key": b"\x00" * 32,
            "nonce": b"\x01" * 12,
            "auth_tag": b"\x02" * 16,
            "key_version": 1,
            "key_fingerprint": "sk-...abcd",
            "base_url": None,
            "default_model": "gpt-4.1",
            "default_embed_model": None,
            "created_by": "test-user",
        }
        defaults.update(overrides)
        return defaults

    def test_insert_returns_id(self, store: CredentialStore) -> None:
        row_id = store.upsert(**self._kwargs())
        assert row_id is not None
        assert isinstance(row_id, str)

    def test_inserted_row_is_readable(self, store: CredentialStore) -> None:
        store.upsert(**self._kwargs())
        row = store.get("tenant-test", "openai", "llm")
        assert row is not None
        assert row.tenant_id == "tenant-test"
        assert row.provider == "openai"
        assert row.encrypted_key == b"\x00" * 32

    def test_upsert_replaces_existing(self, store: CredentialStore) -> None:
        first = store.upsert(**self._kwargs(key_fingerprint="sk-...0001"))
        second = store.upsert(**self._kwargs(key_fingerprint="sk-...0002"))
        assert first == second  # same id (UPSERT)
        row = store.get("tenant-test", "openai", "llm")
        assert row is not None
        assert row.key_fingerprint == "sk-...0002"

    def test_upsert_resets_revoked_status(self, store: CredentialStore) -> None:
        """A previously-revoked credential slot is re-activated by a fresh
        UPSERT — the tenant explicitly chose to add a new key for that
        provider/purpose."""
        first_id = store.upsert(**self._kwargs())
        assert first_id is not None
        store.revoke("tenant-test", first_id)
        # Revoked → no longer in get()
        assert store.get("tenant-test", "openai", "llm") is None
        # Re-upsert
        store.upsert(**self._kwargs(key_fingerprint="sk-...new"))
        row = store.get("tenant-test", "openai", "llm")
        assert row is not None
        assert row.status == "active"


# ---------------------------------------------------------------------------
# get_active_for_purpose
# ---------------------------------------------------------------------------


class TestGetActiveForPurpose:
    def _kwargs(self, **overrides: Any) -> dict[str, Any]:
        return {
            "tenant_id": "tenant-test",
            "provider": "openai",
            "purpose": "llm",
            "encrypted_key": b"\x00" * 32,
            "nonce": b"\x01" * 12,
            "auth_tag": b"\x02" * 16,
            "key_version": 1,
            "key_fingerprint": "sk-...x",
            "base_url": None,
            "default_model": None,
            "default_embed_model": None,
            "created_by": "test",
            **overrides,
        }

    def test_exact_purpose_match_wins(self, store: CredentialStore) -> None:
        store.upsert(**self._kwargs(provider="openai", purpose="llm"))
        store.upsert(**self._kwargs(provider="anthropic", purpose="both"))
        row = store.get_active_for_purpose("tenant-test", "llm")
        assert row is not None
        assert row.provider == "openai"  # exact 'llm' wins over 'both'

    def test_falls_back_to_both(self, store: CredentialStore) -> None:
        """No exact match for purpose='embedding' → fallback to 'both'."""
        store.upsert(**self._kwargs(provider="openai", purpose="both"))
        row = store.get_active_for_purpose("tenant-test", "embedding")
        assert row is not None
        assert row.provider == "openai"

    def test_returns_none_when_no_active_row(self, store: CredentialStore) -> None:
        row_id = store.upsert(**self._kwargs())
        assert row_id is not None
        store.revoke("tenant-test", row_id)
        assert store.get_active_for_purpose("tenant-test", "llm") is None


# ---------------------------------------------------------------------------
# patch
# ---------------------------------------------------------------------------


class TestPatch:
    def test_partial_update_only_changes_specified_field(self, store: CredentialStore) -> None:
        row_id = store.upsert(
            tenant_id="tenant-test",
            provider="openai",
            purpose="llm",
            encrypted_key=b"\x00" * 32,
            nonce=b"\x01" * 12,
            auth_tag=b"\x02" * 16,
            key_version=1,
            key_fingerprint="sk-...x",
            base_url=None,
            default_model="gpt-4.1",
            default_embed_model=None,
            created_by="test",
        )
        assert row_id is not None
        outcome = store.patch(
            tenant_id="tenant-test",
            credential_id=row_id,
            default_model="gpt-5",
        )
        assert outcome is PatchOutcome.UPDATED
        row = store.get_by_id("tenant-test", row_id)
        assert row is not None
        assert row.default_model == "gpt-5"
        assert row.encrypted_key == b"\x00" * 32  # unchanged

    def test_role_models_jsonb_round_trip(self, store: CredentialStore) -> None:
        row_id = store.upsert(
            tenant_id="tenant-test",
            provider="openai",
            purpose="llm",
            encrypted_key=b"\x00" * 32,
            nonce=b"\x01" * 12,
            auth_tag=b"\x02" * 16,
            key_version=1,
            key_fingerprint="sk-...x",
            base_url=None,
            default_model=None,
            default_embed_model=None,
            created_by="test",
        )
        assert row_id is not None
        store.patch(
            tenant_id="tenant-test",
            credential_id=row_id,
            role_models={"eval": "gpt-4.1-mini", "evolve": "claude-opus-4-7"},
        )
        row = store.get_by_id("tenant-test", row_id)
        assert row is not None
        assert row.role_models == {"eval": "gpt-4.1-mini", "evolve": "claude-opus-4-7"}


# ---------------------------------------------------------------------------
# revoke / mark_invalid / mark_validated / touch_last_used
# ---------------------------------------------------------------------------


class TestStatusTransitions:
    def _seed(self, store: CredentialStore) -> str:
        row_id = store.upsert(
            tenant_id="tenant-test",
            provider="openai",
            purpose="llm",
            encrypted_key=b"\x00" * 32,
            nonce=b"\x01" * 12,
            auth_tag=b"\x02" * 16,
            key_version=1,
            key_fingerprint="sk-...x",
            base_url=None,
            default_model=None,
            default_embed_model=None,
            created_by="test",
        )
        assert row_id is not None
        return row_id

    def test_revoke_hides_from_get(self, store: CredentialStore) -> None:
        row_id = self._seed(store)
        assert store.revoke("tenant-test", row_id) is True
        assert store.get("tenant-test", "openai", "llm") is None
        # Audit row still exists via list_for_tenant
        rows = store.list_for_tenant("tenant-test")
        assert any(r.id == row_id and r.status == "revoked" for r in rows)

    def test_revoke_idempotent(self, store: CredentialStore) -> None:
        row_id = self._seed(store)
        assert store.revoke("tenant-test", row_id) is True
        assert store.revoke("tenant-test", row_id) is False  # already revoked

    def test_mark_invalid_sets_status_and_error(self, store: CredentialStore) -> None:
        row_id = self._seed(store)
        store.mark_invalid(row_id, "401 Unauthorized")
        rows = store.list_for_tenant("tenant-test")
        target = next(r for r in rows if r.id == row_id)
        assert target.status == "invalid"
        assert target.last_validation_error == "401 Unauthorized"

    def test_touch_last_used_sets_timestamp(self, store: CredentialStore) -> None:
        row_id = self._seed(store)
        store.touch_last_used(row_id)
        row = store.get_by_id("tenant-test", row_id)
        assert row is not None
        assert row.last_used_at is not None

    def test_mark_validated_clears_error(self, store: CredentialStore) -> None:
        row_id = self._seed(store)
        store.mark_invalid(row_id, "boom")
        store.mark_validated(row_id, error=None)
        rows = store.list_for_tenant("tenant-test")
        target = next(r for r in rows if r.id == row_id)
        assert target.last_validation_error is None
        assert target.last_validated_at is not None


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------


class TestCrossTenantIsolation:
    def test_get_returns_none_for_other_tenant(self, store: CredentialStore) -> None:
        store.upsert(
            tenant_id="tenant-test",
            provider="openai",
            purpose="llm",
            encrypted_key=b"\x00" * 32,
            nonce=b"\x01" * 12,
            auth_tag=b"\x02" * 16,
            key_version=1,
            key_fingerprint="sk-...x",
            base_url=None,
            default_model=None,
            default_embed_model=None,
            created_by="test",
        )
        # Another tenant cannot see this row
        assert store.get("tenant-other", "openai", "llm") is None
        assert store.get_active_for_purpose("tenant-other", "llm") is None

    def test_get_by_id_enforces_tenant_scope(self, store: CredentialStore) -> None:
        row_id = store.upsert(
            tenant_id="tenant-test",
            provider="openai",
            purpose="llm",
            encrypted_key=b"\x00" * 32,
            nonce=b"\x01" * 12,
            auth_tag=b"\x02" * 16,
            key_version=1,
            key_fingerprint="sk-...x",
            base_url=None,
            default_model=None,
            default_embed_model=None,
            created_by="test",
        )
        assert row_id is not None
        # Even with the correct UUID, a different tenant cannot read
        assert store.get_by_id("tenant-other", row_id) is None


# ---------------------------------------------------------------------------
# No-engine paths
# ---------------------------------------------------------------------------


class TestNoEngine:
    """When ENGRAMIA_BYOK_ENABLED=false / engine unconfigured, every method
    must return a safe default rather than raising."""

    def test_no_engine_get_returns_none(self) -> None:
        s = CredentialStore(engine=None)
        assert s.get("any", "openai", "llm") is None

    def test_no_engine_list_returns_empty(self) -> None:
        s = CredentialStore(engine=None)
        assert s.list_for_tenant("any") == []

    def test_no_engine_upsert_returns_none(self) -> None:
        s = CredentialStore(engine=None)
        assert (
            s.upsert(
                tenant_id="t",
                provider="openai",
                purpose="llm",
                encrypted_key=b"",
                nonce=b"",
                auth_tag=b"",
                key_version=1,
                key_fingerprint="",
                base_url=None,
                default_model=None,
                default_embed_model=None,
                created_by="x",
            )
            is None
        )

    def test_no_engine_revoke_returns_false(self) -> None:
        s = CredentialStore(engine=None)
        assert s.revoke("t", "id") is False

    def test_no_engine_patch_returns_no_db(self) -> None:
        s = CredentialStore(engine=None)
        assert s.patch(tenant_id="t", credential_id="id") is PatchOutcome.NO_DB

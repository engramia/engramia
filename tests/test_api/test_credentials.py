# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Integration tests for /v1/credentials/* (BYOK REST endpoints).

Uses ``create_app()`` per the API testing convention, with BYOK enabled
via env vars and a real :class:`AESGCMCipher`. The credential store and
resolver are stubbed with in-memory fakes so these tests stay
postgres-free and fast.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from typing import Any

import pytest
from fastapi.testclient import TestClient

from engramia.api.auth import require_auth
from engramia.credentials import (
    AESGCMCipher,
    CredentialResolver,
    CredentialStore,
    StoredCredential,
)
from tests.factories import make_auth_dep

_TEST_KEY = bytes(range(32))


# ---------------------------------------------------------------------------
# In-memory fake store + resolver to bypass Postgres in unit tests
# ---------------------------------------------------------------------------


class _FakeStore(CredentialStore):
    """In-memory credential store. Drop-in for CredentialStore so the
    resolver and route handlers use the same surface."""

    def __init__(self) -> None:  # type: ignore[override]
        self._rows: dict[str, StoredCredential] = {}
        self._tenant_index: dict[str, list[str]] = defaultdict(list)
        self._next_id = 1

    def upsert(  # type: ignore[override]
        self,
        *,
        tenant_id: str,
        provider,
        purpose,
        encrypted_key: bytes,
        nonce: bytes,
        auth_tag: bytes,
        key_version: int,
        key_fingerprint: str,
        base_url: str | None,
        default_model: str | None,
        default_embed_model: str | None,
        created_by: str,
    ) -> str | None:
        # Look for existing (tenant, provider, purpose) row
        for rid in self._tenant_index[tenant_id]:
            row = self._rows[rid]
            if row.provider == provider and row.purpose == purpose:
                self._rows[rid] = StoredCredential(
                    id=rid,
                    tenant_id=tenant_id,
                    provider=provider,
                    purpose=purpose,
                    encrypted_key=encrypted_key,
                    nonce=nonce,
                    auth_tag=auth_tag,
                    key_version=key_version,
                    key_fingerprint=key_fingerprint,
                    base_url=base_url,
                    default_model=default_model,
                    default_embed_model=default_embed_model,
                    role_models={},
                    status="active",
                    last_used_at=None,
                    last_validated_at=None,
                    last_validation_error=None,
                    created_at=datetime.datetime.now(datetime.UTC),
                    created_by=created_by,
                )
                return rid
        new_id = f"cred-{self._next_id:04d}"
        self._next_id += 1
        self._rows[new_id] = StoredCredential(
            id=new_id,
            tenant_id=tenant_id,
            provider=provider,
            purpose=purpose,
            encrypted_key=encrypted_key,
            nonce=nonce,
            auth_tag=auth_tag,
            key_version=key_version,
            key_fingerprint=key_fingerprint,
            base_url=base_url,
            default_model=default_model,
            default_embed_model=default_embed_model,
            role_models={},
            status="active",
            last_used_at=None,
            last_validated_at=None,
            last_validation_error=None,
            created_at=datetime.datetime.now(datetime.UTC),
            created_by=created_by,
        )
        self._tenant_index[tenant_id].append(new_id)
        return new_id

    def get_by_id(self, tenant_id: str, credential_id: str) -> StoredCredential | None:  # type: ignore[override]
        row = self._rows.get(credential_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        return row

    def get(self, tenant_id, provider, purpose) -> StoredCredential | None:  # type: ignore[override]
        for rid in self._tenant_index[tenant_id]:
            row = self._rows[rid]
            if row.provider == provider and row.purpose == purpose and row.status == "active":
                return row
        return None

    def get_active_for_purpose(self, tenant_id, purpose) -> StoredCredential | None:  # type: ignore[override]
        return None  # not exercised in these tests

    def list_for_tenant(self, tenant_id: str) -> list[StoredCredential]:  # type: ignore[override]
        return [self._rows[rid] for rid in self._tenant_index[tenant_id]]

    def patch(  # type: ignore[override]
        self,
        *,
        tenant_id: str,
        credential_id: str,
        base_url: str | None = None,
        default_model: str | None = None,
        default_embed_model: str | None = None,
        role_models: dict[str, str] | None = None,
    ) -> bool:
        row = self.get_by_id(tenant_id, credential_id)
        if row is None:
            return False
        if all(v is None for v in (base_url, default_model, default_embed_model, role_models)):
            return False
        updated = StoredCredential(
            id=row.id,
            tenant_id=row.tenant_id,
            provider=row.provider,
            purpose=row.purpose,
            encrypted_key=row.encrypted_key,
            nonce=row.nonce,
            auth_tag=row.auth_tag,
            key_version=row.key_version,
            key_fingerprint=row.key_fingerprint,
            base_url=base_url if base_url is not None else row.base_url,
            default_model=default_model if default_model is not None else row.default_model,
            default_embed_model=(default_embed_model if default_embed_model is not None else row.default_embed_model),
            role_models=role_models if role_models is not None else row.role_models,
            status=row.status,
            last_used_at=row.last_used_at,
            last_validated_at=row.last_validated_at,
            last_validation_error=row.last_validation_error,
            created_at=row.created_at,
            created_by=row.created_by,
        )
        self._rows[row.id] = updated
        return True

    def revoke(self, tenant_id: str, credential_id: str) -> bool:  # type: ignore[override]
        row = self.get_by_id(tenant_id, credential_id)
        if row is None or row.status == "revoked":
            return False
        self._rows[row.id] = StoredCredential(
            **{**row.__dict__, "status": "revoked"}
        )
        return True

    def mark_invalid(self, credential_id: str, error: str) -> None:  # type: ignore[override]
        row = self._rows.get(credential_id)
        if row is None:
            return
        self._rows[credential_id] = StoredCredential(
            **{**row.__dict__, "status": "invalid", "last_validation_error": error}
        )

    def mark_validated(self, credential_id: str, error: str | None = None) -> None:  # type: ignore[override]
        row = self._rows.get(credential_id)
        if row is None:
            return
        self._rows[credential_id] = StoredCredential(
            **{
                **row.__dict__,
                "last_validated_at": datetime.datetime.now(datetime.UTC),
                "last_validation_error": error,
            }
        )

    def touch_last_used(self, credential_id: str) -> None:  # type: ignore[override]
        return  # not exercised


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_byok(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Create an Engramia app with BYOK wired to in-memory fakes.

    Mirrors the env-var setup of ``app_client`` (conftest.py) so the
    factory mocks for embeddings + LLM apply: this prevents the real
    OpenAI client from instantiating during request handling and
    decoupling our tests from OPENAI_API_KEY availability.
    """
    monkeypatch.setenv("ENGRAMIA_AUTH_MODE", "dev")
    monkeypatch.setenv("ENGRAMIA_ALLOW_NO_AUTH", "true")
    monkeypatch.setenv("ENGRAMIA_STORAGE", "json")
    monkeypatch.setenv("ENGRAMIA_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("ENGRAMIA_LLM_PROVIDER", "none")
    monkeypatch.setenv("ENGRAMIA_SKIP_AUTO_APP", "1")
    # BYOK is set up manually below — keep the env flag off to avoid the
    # real master-key load path during create_app.
    monkeypatch.delenv("ENGRAMIA_BYOK_ENABLED", raising=False)

    # Match conftest's app_client mocking so /v1/learn etc. don't try
    # to construct a real OpenAI client. Lazy import: importing
    # engramia.api.app at module-load time would freeze the original
    # make_embeddings/make_llm bindings in app.py before this fixture
    # runs, defeating the monkeypatch.
    from unittest.mock import MagicMock

    import engramia._factory as factory

    mock_embeddings = MagicMock()
    mock_embeddings.embed.return_value = [0.1] * 1536
    mock_llm = MagicMock()
    mock_llm.call.return_value = "{}"
    monkeypatch.setattr(factory, "make_embeddings", lambda: mock_embeddings)
    monkeypatch.setattr(factory, "make_llm", lambda: mock_llm)

    from engramia.api.app import create_app

    app = create_app()
    cipher = AESGCMCipher(_TEST_KEY)
    store = _FakeStore()
    resolver = CredentialResolver(store=store, cipher=cipher)
    app.state.credential_store = store
    app.state.credential_resolver = resolver
    app.state.credential_cipher = cipher
    return app


@pytest.fixture
def admin_client(app_with_byok: Any) -> TestClient:
    app_with_byok.dependency_overrides[require_auth] = make_auth_dep(
        role="admin", tenant_id="tenant-A"
    )
    return TestClient(app_with_byok)


@pytest.fixture
def switch_tenant(app_with_byok: Any):
    """Helper: rebind require_auth to a different tenant on the same app.

    Cross-tenant tests need to interleave calls from tenant A and tenant
    B against a single app. Reassigning the override before each call is
    cleaner than maintaining two TestClient fixtures whose overrides
    overwrite each other at fixture setup time.
    """

    def _switch(role: str, tenant_id: str) -> TestClient:
        app_with_byok.dependency_overrides[require_auth] = make_auth_dep(
            role=role, tenant_id=tenant_id
        )
        return TestClient(app_with_byok)

    return _switch


@pytest.fixture
def mock_validation_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the validator so tests don't make real outbound HTTPS calls."""
    from engramia.credentials import validator

    monkeypatch.setattr(
        validator,
        "validate",
        lambda provider, api_key, base_url=None: validator.ValidationResult(
            success=True, error=None, category="ok"
        ),
    )
    # Also patch in the route module
    from engramia.api import credentials as credentials_route

    monkeypatch.setattr(
        credentials_route,
        "validate_credential",
        lambda provider, api_key, base_url=None: validator.ValidationResult(
            success=True, error=None, category="ok"
        ),
    )


@pytest.fixture
def mock_validation_auth_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    from engramia.api import credentials as credentials_route
    from engramia.credentials import validator

    bad = validator.ValidationResult(
        success=False, error="Provider rejected the API key (401/403)", category="auth_failed"
    )
    monkeypatch.setattr(credentials_route, "validate_credential", lambda *a, **kw: bad)


# ---------------------------------------------------------------------------
# POST /v1/credentials
# ---------------------------------------------------------------------------


class TestCreateCredential:
    def test_happy_path_returns_201(self, admin_client: TestClient, mock_validation_ok) -> None:
        resp = admin_client.post(
            "/v1/credentials",
            json={
                "provider": "openai",
                "purpose": "llm",
                "api_key": "sk-test-1234567890ABCDEF",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["provider"] == "openai"
        assert body["purpose"] == "llm"
        assert body["status"] == "active"
        # Plaintext must NEVER appear in response
        assert "api_key" not in body
        assert "sk-test-1234" not in resp.text
        # Fingerprint surfaced in display format
        assert "..." in body["key_fingerprint"]
        assert body["key_fingerprint"].endswith("CDEF")

    def test_validation_failure_returns_400(
        self, admin_client: TestClient, mock_validation_auth_failed
    ) -> None:
        resp = admin_client.post(
            "/v1/credentials",
            json={
                "provider": "openai",
                "purpose": "llm",
                "api_key": "sk-bad-1234567890ABCDEF",
            },
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["error_code"] == "CREDENTIAL_VALIDATION_FAILED"
        assert body["error_context"]["category"] == "auth_failed"

    def test_response_does_not_leak_api_key_on_validation_failure(
        self, admin_client: TestClient, mock_validation_auth_failed
    ) -> None:
        resp = admin_client.post(
            "/v1/credentials",
            json={
                "provider": "openai",
                "purpose": "llm",
                "api_key": "sk-LEAK-DETECTOR-1234567890",
            },
        )
        assert "sk-LEAK-DETECTOR" not in resp.text

    def test_pydantic_rejects_blank_api_key(self, admin_client: TestClient) -> None:
        resp = admin_client.post(
            "/v1/credentials",
            json={"provider": "openai", "api_key": "        "},
        )
        assert resp.status_code == 422
        # The 422 body must not include the api_key value
        assert "        " not in resp.text or "api_key" not in resp.json().get("detail", "")

    def test_reader_role_forbidden(self, switch_tenant, mock_validation_ok) -> None:
        client = switch_tenant("reader", "tenant-A")
        resp = client.post(
            "/v1/credentials",
            json={"provider": "openai", "api_key": "sk-test-1234567890ABCDEF"},
        )
        assert resp.status_code == 403

    def test_upsert_replaces_existing(self, admin_client: TestClient, mock_validation_ok) -> None:
        admin_client.post(
            "/v1/credentials",
            json={
                "provider": "openai",
                "purpose": "llm",
                "api_key": "sk-old-key-1234567890ABCD",
            },
        )
        resp2 = admin_client.post(
            "/v1/credentials",
            json={
                "provider": "openai",
                "purpose": "llm",
                "api_key": "sk-new-key-1234567890WXYZ",
            },
        )
        assert resp2.status_code == 201
        # New fingerprint reflects the rotated key
        assert resp2.json()["key_fingerprint"].endswith("WXYZ")
        # Only one row total per (tenant, provider, purpose)
        list_resp = admin_client.get("/v1/credentials")
        assert len(list_resp.json()) == 1


# ---------------------------------------------------------------------------
# GET /v1/credentials
# ---------------------------------------------------------------------------


class TestListCredentials:
    def test_empty_for_new_tenant(self, admin_client: TestClient) -> None:
        resp = admin_client.get("/v1/credentials")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_lists_active_and_revoked(self, admin_client: TestClient, mock_validation_ok) -> None:
        admin_client.post(
            "/v1/credentials",
            json={"provider": "openai", "api_key": "sk-test-1234567890"},
        )
        # List shows the active row
        rows = admin_client.get("/v1/credentials").json()
        assert len(rows) == 1
        # Revoke and re-list — revoked row still appears
        admin_client.delete(f"/v1/credentials/{rows[0]['id']}")
        rows_after = admin_client.get("/v1/credentials").json()
        assert len(rows_after) == 1
        assert rows_after[0]["status"] == "revoked"

    def test_no_plaintext_in_list(self, admin_client: TestClient, mock_validation_ok) -> None:
        admin_client.post(
            "/v1/credentials",
            json={"provider": "openai", "api_key": "sk-LEAK-IN-LIST-1234567890"},
        )
        list_resp = admin_client.get("/v1/credentials")
        assert "sk-LEAK-IN-LIST" not in list_resp.text


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------


class TestCrossTenantIsolation:
    def test_other_tenant_cannot_read(self, switch_tenant, mock_validation_ok) -> None:
        # Tenant A creates a credential
        client_a = switch_tenant("admin", "tenant-A")
        create_resp = client_a.post(
            "/v1/credentials",
            json={"provider": "openai", "api_key": "sk-tenant-A-1234567890"},
        )
        cred_id = create_resp.json()["id"]

        # Tenant B cannot read it (404, not 403 — to avoid leaking existence)
        client_b = switch_tenant("admin", "tenant-B")
        get_resp = client_b.get(f"/v1/credentials/{cred_id}")
        assert get_resp.status_code == 404

        # Tenant B's list is empty
        list_resp = client_b.get("/v1/credentials")
        assert list_resp.json() == []

    def test_other_tenant_cannot_revoke(self, switch_tenant, mock_validation_ok) -> None:
        client_a = switch_tenant("admin", "tenant-A")
        create_resp = client_a.post(
            "/v1/credentials",
            json={"provider": "openai", "api_key": "sk-tenant-A-1234567890"},
        )
        cred_id = create_resp.json()["id"]

        client_b = switch_tenant("admin", "tenant-B")
        delete_resp = client_b.delete(f"/v1/credentials/{cred_id}")
        assert delete_resp.status_code == 404

        # And the credential still exists for tenant A
        client_a = switch_tenant("admin", "tenant-A")
        list_resp = client_a.get("/v1/credentials").json()
        assert list_resp[0]["status"] == "active"


# ---------------------------------------------------------------------------
# PATCH /v1/credentials/{id}
# ---------------------------------------------------------------------------


class TestPatch:
    def test_updates_default_model(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = admin_client.post(
            "/v1/credentials",
            json={"provider": "openai", "api_key": "sk-test-1234567890ABCDEF"},
        ).json()
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}",
            json={"default_model": "gpt-5"},
        )
        assert resp.status_code == 200
        assert resp.json()["default_model"] == "gpt-5"

    def test_role_models_round_trip(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = admin_client.post(
            "/v1/credentials",
            json={"provider": "openai", "api_key": "sk-test-1234567890ABCDEF"},
        ).json()
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}",
            json={"role_models": {"eval": "gpt-4.1-mini", "evolve": "claude-opus-4-7"}},
        )
        assert resp.status_code == 200
        assert resp.json()["role_models"] == {
            "eval": "gpt-4.1-mini",
            "evolve": "claude-opus-4-7",
        }

    def test_404_for_unknown_id(self, admin_client: TestClient) -> None:
        resp = admin_client.patch(
            "/v1/credentials/nonexistent",
            json={"default_model": "gpt-5"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /v1/credentials/{id}
# ---------------------------------------------------------------------------


class TestDelete:
    def test_revokes_active_credential(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = admin_client.post(
            "/v1/credentials",
            json={"provider": "openai", "api_key": "sk-test-1234567890ABCDEF"},
        ).json()
        resp = admin_client.delete(f"/v1/credentials/{cred['id']}")
        assert resp.status_code == 204

    def test_404_when_already_revoked(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = admin_client.post(
            "/v1/credentials",
            json={"provider": "openai", "api_key": "sk-test-1234567890ABCDEF"},
        ).json()
        admin_client.delete(f"/v1/credentials/{cred['id']}")
        resp = admin_client.delete(f"/v1/credentials/{cred['id']}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# BYOK disabled — endpoints return 503
# ---------------------------------------------------------------------------


class TestByokDisabled:
    def test_503_when_byok_not_wired(self, app_with_byok: Any) -> None:
        # Override the BYOK fixture by clearing the wired-up state
        app_with_byok.state.credential_store = None
        app_with_byok.state.credential_resolver = None
        app_with_byok.dependency_overrides[require_auth] = make_auth_dep(role="admin")
        client = TestClient(app_with_byok)
        resp = client.get("/v1/credentials")
        assert resp.status_code == 503
        assert resp.json()["error_code"] == "BYOK_NOT_ENABLED"

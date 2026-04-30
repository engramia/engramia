# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for the dedicated PATCH /v1/credentials/{id}/role-models endpoint.

These cover the Phase 6.6 #2 design:

* Tier gate (Business+) on non-empty role_models
* Mandatory If-Match (428 when missing, 412 on stale)
* Validator: lowercase normalisation + bad role/model names rejected
* Permission gate (admin+; editor cannot set role_models)
* Empty {} downgrade exit allowed on any tier
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from engramia.api.auth import require_auth
from engramia.billing.models import BillingSubscription
from tests.factories import make_auth_dep
from tests.test_api.test_credentials import (  # reuse fixtures + fakes
    _TEST_KEY,
    _FakeStore,
)


# ---------------------------------------------------------------------------
# Fixture: app with BYOK + a billing service stub returning a configurable tier
# ---------------------------------------------------------------------------


class _StubBilling:
    """Minimal billing service stub controllable per-test."""

    def __init__(self, tier: str = "business") -> None:
        self._tier = tier

    def set_tier(self, tier: str) -> None:
        self._tier = tier

    def get_subscription(self, tenant_id: str) -> BillingSubscription:
        return BillingSubscription(tenant_id=tenant_id, plan_tier=self._tier)


@pytest.fixture
def app_with_byok_billing(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ENGRAMIA_AUTH_MODE", "dev")
    monkeypatch.setenv("ENGRAMIA_ALLOW_NO_AUTH", "true")
    monkeypatch.setenv("ENGRAMIA_STORAGE", "json")
    monkeypatch.setenv("ENGRAMIA_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("ENGRAMIA_LLM_PROVIDER", "none")
    monkeypatch.setenv("ENGRAMIA_SKIP_AUTO_APP", "1")
    monkeypatch.delenv("ENGRAMIA_BYOK_ENABLED", raising=False)

    import engramia._factory as factory

    mock_embeddings = MagicMock()
    mock_embeddings.embed.return_value = [0.1] * 1536
    mock_llm = MagicMock()
    mock_llm.call.return_value = "{}"
    monkeypatch.setattr(factory, "make_embeddings", lambda resolver=None: mock_embeddings)
    monkeypatch.setattr(factory, "make_llm", lambda resolver=None: mock_llm)

    from engramia.api.app import create_app
    from engramia.credentials import AESGCMCipher, CredentialResolver

    app = create_app()
    cipher = AESGCMCipher(_TEST_KEY)
    store = _FakeStore()
    resolver = CredentialResolver(store=store, cipher=cipher)
    app.state.credential_store = store
    app.state.credential_resolver = resolver
    app.state.credential_cipher = cipher
    app.state.billing_service = _StubBilling(tier="business")
    return app


@pytest.fixture
def admin_client(app_with_byok_billing: Any) -> TestClient:
    app_with_byok_billing.dependency_overrides[require_auth] = make_auth_dep(
        role="admin", tenant_id="tenant-A"
    )
    return TestClient(app_with_byok_billing)


@pytest.fixture
def switch_role(app_with_byok_billing: Any):
    """Rebind ``require_auth`` to a different role on the same app.

    Two clients (admin + editor) cannot coexist via separate fixtures —
    both would share the same ``dependency_overrides`` dict and the
    second to be created would silently overwrite the first.
    """

    def _switch(role: str, tenant_id: str = "tenant-A") -> TestClient:
        app_with_byok_billing.dependency_overrides[require_auth] = make_auth_dep(
            role=role, tenant_id=tenant_id
        )
        return TestClient(app_with_byok_billing)

    return _switch


@pytest.fixture
def mock_validation_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the provider /models ping so POST /credentials succeeds."""
    from engramia.api import credentials as creds_module
    from engramia.credentials.validator import ValidationResult

    monkeypatch.setattr(
        creds_module,
        "validate_credential",
        lambda *a, **k: ValidationResult(success=True, category=None, error=None),
    )


def _create_cred(client: TestClient) -> dict:
    resp = client.post(
        "/v1/credentials",
        json={"provider": "openai", "api_key": "sk-test-1234567890ABCDEF"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _etag(view: dict) -> str:
    return f'"{view["updated_at"]}"'


# ---------------------------------------------------------------------------
# Tier gate
# ---------------------------------------------------------------------------


class TestRoleModelsTierGate:
    def test_business_tier_can_set(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-models",
            json={"role_models": {"eval": "gpt-4.1-mini"}},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["role_models"] == {"eval": "gpt-4.1-mini"}

    def test_pro_tier_blocked_with_402(
        self, app_with_byok_billing, admin_client: TestClient, mock_validation_ok
    ) -> None:
        app_with_byok_billing.state.billing_service.set_tier("pro")
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-models",
            json={"role_models": {"eval": "gpt-4.1-mini"}},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 402
        body = resp.json()
        # Engramia's structured error formatter flattens detail dict into
        # {error_code, detail, error_context}.
        assert body["error_code"] == "ENTITLEMENT_REQUIRED"
        # current_tier is promoted into error_context by the global handler.
        assert body.get("error_context", {}).get("current_tier") == "pro"

    def test_pro_tier_can_clear_empty(
        self, app_with_byok_billing, admin_client: TestClient, mock_validation_ok
    ) -> None:
        """Empty {} is the downgrade exit — always permitted."""
        app_with_byok_billing.state.billing_service.set_tier("pro")
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-models",
            json={"role_models": {}},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Mandatory If-Match
# ---------------------------------------------------------------------------


class TestRoleModelsIfMatch:
    def test_missing_if_match_is_428(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-models",
            json={"role_models": {"eval": "gpt-4.1-mini"}},
        )
        assert resp.status_code == 428
        assert resp.json()["error_code"] == "PRECONDITION_REQUIRED"

    def test_stale_if_match_is_412(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        # First write succeeds
        first = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-models",
            json={"role_models": {"eval": "gpt-4.1-mini"}},
            headers={"If-Match": _etag(cred)},
        )
        assert first.status_code == 200
        # Second write with the OLD etag must fail
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-models",
            json={"role_models": {"eval": "gpt-4o-mini"}},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 412
        assert resp.json()["error_code"] == "PRECONDITION_FAILED"

    def test_malformed_if_match_is_412(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-models",
            json={"role_models": {"eval": "gpt-4.1-mini"}},
            headers={"If-Match": '"not-a-timestamp"'},
        )
        assert resp.status_code == 412


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class TestRoleModelsValidator:
    def test_lowercase_normalisation(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-models",
            json={"role_models": {"Eval": "gpt-4.1-mini"}},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 200, resp.text
        # Server-side normalisation: stored as 'eval'
        assert resp.json()["role_models"] == {"eval": "gpt-4.1-mini"}

    def test_invalid_role_name_422(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-models",
            json={"role_models": {"role with space": "gpt-4.1-mini"}},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 422

    def test_invalid_model_name_422(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-models",
            json={"role_models": {"eval": "model with spaces"}},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 422

    def test_too_many_entries_422(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        big = {f"role_{i}": "gpt-4.1-mini" for i in range(20)}
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-models",
            json={"role_models": big},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Permission
# ---------------------------------------------------------------------------


class TestRoleModelsPermission:
    def test_editor_cannot_set_role_models(
        self,
        switch_role,
        mock_validation_ok,
    ) -> None:
        admin = switch_role("admin")
        cred = _create_cred(admin)
        editor = switch_role("editor")
        resp = editor.patch(
            f"/v1/credentials/{cred['id']}/role-models",
            json={"role_models": {"eval": "gpt-4.1-mini"}},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Round-trip + ETag advance
# ---------------------------------------------------------------------------


class TestRoleModelsRoundTrip:
    def test_etag_advances_on_each_write(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        first = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-models",
            json={"role_models": {"eval": "gpt-4.1-mini"}},
            headers={"If-Match": _etag(cred)},
        )
        assert first.status_code == 200
        new_etag = _etag(first.json())
        assert new_etag != _etag(cred)
        # Use the NEW etag — should succeed
        second = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-models",
            json={"role_models": {"eval": "gpt-4o-mini"}},
            headers={"If-Match": new_etag},
        )
        assert second.status_code == 200

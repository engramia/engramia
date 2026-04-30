# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for PATCH /v1/credentials/{id}/role-cost-limits (#2b).

Mirrors the role-models endpoint test shape — tier gate (Business+),
mandatory If-Match, validator (positive int cents, lowercase, max),
permission gate. The cost-ceiling-specific cases are the safety
ceiling on the value (catch dollars-vs-cents mistakes) and the
positive-int requirement (no negative or zero limits — clear via
empty {} instead).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from engramia.api.auth import require_auth
from engramia.billing.models import BillingSubscription
from tests.factories import make_auth_dep
from tests.test_api.test_credentials import _TEST_KEY, _FakeStore


class _StubBilling:
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
    monkeypatch.setattr(
        factory,
        "make_llm",
        lambda resolver=None, store=None, role_meter=None: mock_llm,
    )

    from engramia.api.app import create_app
    from engramia.credentials import AESGCMCipher, CredentialResolver

    app = create_app()
    cipher = AESGCMCipher(_TEST_KEY)
    store = _FakeStore()
    from engramia.credentials.backends.local import LocalAESGCMBackend
    backend = LocalAESGCMBackend(cipher)
    resolver = CredentialResolver(store=store, backends={backend.backend_id: backend})
    app.state.credential_store = store
    app.state.credential_resolver = resolver
    app.state.credential_cipher = cipher
    app.state.credential_backend = backend
    app.state.billing_service = _StubBilling(tier="business")
    return app


@pytest.fixture
def admin_client(app_with_byok_billing: Any) -> TestClient:
    app_with_byok_billing.dependency_overrides[require_auth] = make_auth_dep(
        role="admin", tenant_id="tenant-A"
    )
    return TestClient(app_with_byok_billing)


@pytest.fixture
def mock_validation_ok(monkeypatch: pytest.MonkeyPatch) -> None:
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
# Happy path + tier gate
# ---------------------------------------------------------------------------


class TestRoleCostLimitsTierGate:
    def test_business_can_set(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-cost-limits",
            json={"role_cost_limits": {"eval": 5000, "coder": 20000}},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["role_cost_limits"] == {"eval": 5000, "coder": 20000}

    def test_pro_blocked_with_402(
        self, app_with_byok_billing, admin_client: TestClient, mock_validation_ok
    ) -> None:
        app_with_byok_billing.state.billing_service.set_tier("pro")
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-cost-limits",
            json={"role_cost_limits": {"eval": 5000}},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 402
        assert resp.json()["error_code"] == "ENTITLEMENT_REQUIRED"

    def test_pro_can_clear_empty(
        self, app_with_byok_billing, admin_client: TestClient, mock_validation_ok
    ) -> None:
        app_with_byok_billing.state.billing_service.set_tier("pro")
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-cost-limits",
            json={"role_cost_limits": {}},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class TestRoleCostLimitsValidator:
    def test_negative_value_422(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-cost-limits",
            json={"role_cost_limits": {"eval": -100}},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 422

    def test_zero_value_422(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-cost-limits",
            json={"role_cost_limits": {"eval": 0}},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 422

    def test_dollar_sized_value_rejected(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        # Anything above $100 000 / mo / role looks like a dollars-not-cents
        # mistake. The validator catches it before the DB write.
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-cost-limits",
            json={"role_cost_limits": {"eval": 50_000_000}},  # $500k
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 422

    def test_string_value_422(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-cost-limits",
            json={"role_cost_limits": {"eval": "5000"}},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 422

    def test_lowercase_normalisation(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-cost-limits",
            json={"role_cost_limits": {"Eval": 1000}},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["role_cost_limits"] == {"eval": 1000}


# ---------------------------------------------------------------------------
# If-Match
# ---------------------------------------------------------------------------


class TestRoleCostLimitsIfMatch:
    def test_missing_if_match_is_428(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/role-cost-limits",
            json={"role_cost_limits": {"eval": 1000}},
        )
        assert resp.status_code == 428

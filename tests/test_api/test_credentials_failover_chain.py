# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for PATCH /v1/credentials/{id}/failover-chain.

Covers Phase 6.6 #2 design:

* Self-reference rejected with 422 FAILOVER_CHAIN_INVALID
* Cross-tenant id rejected (returns "unknown" — defence in depth)
* Inactive credential in chain rejected
* Tier gate (Business+) on non-empty chain
* Mandatory If-Match
* Empty list clear allowed on any tier
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
def mock_validation_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from engramia.api import credentials as creds_module
    from engramia.credentials.validator import ValidationResult

    monkeypatch.setattr(
        creds_module,
        "validate_credential",
        lambda *a, **k: ValidationResult(success=True, category=None, error=None),
    )


def _create_cred(client: TestClient, provider: str = "openai", purpose: str = "llm") -> dict:
    resp = client.post(
        "/v1/credentials",
        json={
            "provider": provider,
            "purpose": purpose,
            "api_key": "sk-test-1234567890ABCDEF",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _etag(view: dict) -> str:
    return f'"{view["updated_at"]}"'


# ---------------------------------------------------------------------------
# Structural validation
# ---------------------------------------------------------------------------


class TestSelfReference:
    def test_self_ref_rejected(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/failover-chain",
            json={"failover_chain": [cred["id"]]},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "FAILOVER_CHAIN_INVALID"

    def test_self_ref_check_runs_before_tier_gate(
        self,
        app_with_byok_billing,
        admin_client: TestClient,
        mock_validation_ok,
    ) -> None:
        # Even on Pro tier, self-ref returns 422 (structural error) — not 402.
        # This way the user gets the real reason, not "upgrade your plan".
        app_with_byok_billing.state.billing_service.set_tier("pro")
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/failover-chain",
            json={"failover_chain": [cred["id"]]},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 422


class TestUnknownIdRejected:
    def test_unknown_id_in_chain_422(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/failover-chain",
            json={"failover_chain": ["does-not-exist-1234"]},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "FAILOVER_CHAIN_INVALID"


class TestRevokedRejected:
    def test_revoked_credential_in_chain_422(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        primary = _create_cred(admin_client, provider="openai", purpose="llm")
        secondary = _create_cred(admin_client, provider="anthropic", purpose="llm")
        # Revoke the secondary
        admin_client.delete(f"/v1/credentials/{secondary['id']}")

        resp = admin_client.patch(
            f"/v1/credentials/{primary['id']}/failover-chain",
            json={"failover_chain": [secondary["id"]]},
            headers={"If-Match": _etag(primary)},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tier gate
# ---------------------------------------------------------------------------


class TestFailoverTierGate:
    def test_business_can_set(self, admin_client: TestClient, mock_validation_ok) -> None:
        primary = _create_cred(admin_client, provider="openai", purpose="llm")
        secondary = _create_cred(admin_client, provider="anthropic", purpose="llm")
        resp = admin_client.patch(
            f"/v1/credentials/{primary['id']}/failover-chain",
            json={"failover_chain": [secondary["id"]]},
            headers={"If-Match": _etag(primary)},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["failover_chain"] == [secondary["id"]]

    def test_pro_blocked(
        self,
        app_with_byok_billing,
        admin_client: TestClient,
        mock_validation_ok,
    ) -> None:
        app_with_byok_billing.state.billing_service.set_tier("pro")
        primary = _create_cred(admin_client, provider="openai", purpose="llm")
        secondary = _create_cred(admin_client, provider="anthropic", purpose="llm")
        resp = admin_client.patch(
            f"/v1/credentials/{primary['id']}/failover-chain",
            json={"failover_chain": [secondary["id"]]},
            headers={"If-Match": _etag(primary)},
        )
        assert resp.status_code == 402

    def test_pro_can_clear_empty_list(
        self,
        app_with_byok_billing,
        admin_client: TestClient,
        mock_validation_ok,
    ) -> None:
        app_with_byok_billing.state.billing_service.set_tier("pro")
        cred = _create_cred(admin_client)
        resp = admin_client.patch(
            f"/v1/credentials/{cred['id']}/failover-chain",
            json={"failover_chain": []},
            headers={"If-Match": _etag(cred)},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class TestFailoverValidator:
    def test_too_long_chain_422(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        primary = _create_cred(admin_client, provider="openai", purpose="llm")
        resp = admin_client.patch(
            f"/v1/credentials/{primary['id']}/failover-chain",
            # Max is 2 fallback entries
            json={"failover_chain": ["id1", "id2", "id3"]},
            headers={"If-Match": _etag(primary)},
        )
        assert resp.status_code == 422

    def test_duplicate_in_chain_422(
        self, admin_client: TestClient, mock_validation_ok
    ) -> None:
        primary = _create_cred(admin_client, provider="openai", purpose="llm")
        resp = admin_client.patch(
            f"/v1/credentials/{primary['id']}/failover-chain",
            json={"failover_chain": ["abc-123", "abc-123"]},
            headers={"If-Match": _etag(primary)},
        )
        assert resp.status_code == 422

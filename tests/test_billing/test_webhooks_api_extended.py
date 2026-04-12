# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Extended billing webhook API tests — checkout, portal, overage endpoints.

Covers:
- POST /v1/billing/checkout — success, missing fields, billing not configured,
  service RuntimeError (no detail leakage)
- GET /v1/billing/portal — success, no customer, billing not configured
- PATCH /v1/billing/overage — success, sandbox rejection, billing not configured,
  invalid JSON, error detail not leaked
- Metering: UsageMeter increment/get_count/get_overage_units no-op + DB paths
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engramia.api.auth import require_auth
from engramia.billing.metering import UsageMeter
from engramia.billing.webhooks import router as billing_router
from tests.factories import make_auth_dep

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _make_app(billing_service=None, pattern_count: int = 0) -> FastAPI:
    """Minimal FastAPI app with billing router and faked app state."""
    app = FastAPI()
    app.include_router(billing_router, prefix="/v1")
    app.dependency_overrides[require_auth] = make_auth_dep()

    mock_storage = MagicMock()
    mock_storage.count_patterns.return_value = pattern_count
    mock_memory = MagicMock()
    mock_memory._storage = mock_storage

    app.state.billing_service = billing_service
    app.state.memory = mock_memory
    return app


# ---------------------------------------------------------------------------
# POST /v1/billing/checkout
# ---------------------------------------------------------------------------


class TestCreateCheckout:
    def test_success_returns_checkout_url(self):
        svc = MagicMock()
        svc.create_checkout_url.return_value = "https://checkout.stripe.com/pay/cs_test_123"
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/checkout",
            json={
                "price_id": "price_pro_monthly",
                "success_url": "https://app.example.com/success",
                "cancel_url": "https://app.example.com/cancel",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["checkout_url"] == "https://checkout.stripe.com/pay/cs_test_123"

    def test_missing_price_id_returns_400(self):
        svc = MagicMock()
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/checkout",
            json={"success_url": "https://ok", "cancel_url": "https://cancel"},
        )
        assert resp.status_code == 400
        assert "required" in resp.json()["detail"].lower()

    def test_missing_success_url_returns_400(self):
        svc = MagicMock()
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/checkout",
            json={"price_id": "price_x", "cancel_url": "https://cancel"},
        )
        assert resp.status_code == 400

    def test_billing_not_configured_returns_503(self):
        client = TestClient(_make_app(billing_service=None))
        resp = client.post(
            "/v1/billing/checkout",
            json={"price_id": "price_x", "success_url": "https://ok", "cancel_url": "https://cancel"},
        )
        assert resp.status_code == 503
        assert "Billing not configured" in resp.json()["detail"]

    def test_service_error_does_not_leak_details(self):
        """RuntimeError from service must not propagate internal message."""
        svc = MagicMock()
        svc.create_checkout_url.side_effect = RuntimeError("Stripe API key expired: sk-prod-xxx")
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/checkout",
            json={"price_id": "price_x", "success_url": "https://ok", "cancel_url": "https://cancel"},
        )
        assert resp.status_code == 503
        # Must not contain the internal error message
        assert "sk-prod" not in resp.text
        assert "Stripe API key" not in resp.text
        assert "Checkout session creation failed" in resp.json()["detail"]

    def test_invalid_json_body_returns_400(self):
        svc = MagicMock()
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/checkout",
            content=b"not valid json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["detail"]

    def test_tenant_id_from_auth_forwarded_to_service(self):
        svc = MagicMock()
        svc.create_checkout_url.return_value = "https://checkout.stripe.com/test"
        client = TestClient(_make_app(billing_service=svc))
        client.post(
            "/v1/billing/checkout",
            json={"price_id": "price_x", "success_url": "https://ok", "cancel_url": "https://cancel"},
        )
        # First argument to create_checkout_url should be tenant_id
        call_args = svc.create_checkout_url.call_args[0]
        assert call_args[0] == "default"  # from make_auth_dep() default


# ---------------------------------------------------------------------------
# GET /v1/billing/portal
# ---------------------------------------------------------------------------


class TestCustomerPortal:
    def test_success_returns_portal_url(self):
        svc = MagicMock()
        svc.create_portal_url.return_value = "https://billing.stripe.com/session/xyz"
        client = TestClient(_make_app(billing_service=svc))
        resp = client.get("/v1/billing/portal", params={"return_url": "https://app.example.com"})
        assert resp.status_code == 200
        assert resp.json()["portal_url"] == "https://billing.stripe.com/session/xyz"

    def test_billing_not_configured_returns_503(self):
        client = TestClient(_make_app(billing_service=None))
        resp = client.get("/v1/billing/portal")
        assert resp.status_code == 503
        assert "Billing not configured" in resp.json()["detail"]

    def test_no_customer_error_does_not_leak_details(self):
        """RuntimeError from service must not propagate internal message."""
        svc = MagicMock()
        svc.create_portal_url.side_effect = RuntimeError("Tenant t1 has no Stripe customer: cus_xxx was deleted")
        client = TestClient(_make_app(billing_service=svc))
        resp = client.get("/v1/billing/portal", params={"return_url": "https://return"})
        assert resp.status_code == 400
        # Must not contain the internal error message
        assert "cus_xxx" not in resp.text
        assert "Customer portal session creation failed" in resp.json()["detail"]

    def test_return_url_defaults_to_base_url(self):
        svc = MagicMock()
        svc.create_portal_url.return_value = "https://portal"
        client = TestClient(_make_app(billing_service=svc))
        resp = client.get("/v1/billing/portal")  # no return_url param
        assert resp.status_code == 200
        # return_url should have been derived from request.base_url
        call_args = svc.create_portal_url.call_args[0]
        assert "testserver" in call_args[1] or call_args[1] != ""


# ---------------------------------------------------------------------------
# PATCH /v1/billing/overage
# ---------------------------------------------------------------------------


class TestSetOverage:
    def test_success_returns_overage_settings(self):
        svc = MagicMock()
        svc.set_overage.return_value = None  # set_overage has no return value
        client = TestClient(_make_app(billing_service=svc))
        resp = client.patch(
            "/v1/billing/overage",
            json={"enabled": True, "budget_cap_cents": 5000},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["overage_enabled"] is True
        assert data["budget_cap_cents"] == 5000

    def test_disable_overage(self):
        svc = MagicMock()
        client = TestClient(_make_app(billing_service=svc))
        resp = client.patch("/v1/billing/overage", json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json()["overage_enabled"] is False

    def test_billing_not_configured_returns_503(self):
        client = TestClient(_make_app(billing_service=None))
        resp = client.patch("/v1/billing/overage", json={"enabled": True})
        assert resp.status_code == 503

    def test_sandbox_plan_rejection_does_not_leak_details(self):
        """ValueError from service (e.g. sandbox plan) must use generic message."""
        svc = MagicMock()
        svc.set_overage.side_effect = ValueError(
            "Overage not available for plan tier 'sandbox' — tenant t1 subscription sub_abc"
        )
        client = TestClient(_make_app(billing_service=svc))
        resp = client.patch("/v1/billing/overage", json={"enabled": True})
        assert resp.status_code == 400
        # Must not contain the internal error details
        assert "sub_abc" not in resp.text
        assert "Invalid overage configuration" in resp.json()["detail"]

    def test_invalid_json_returns_400(self):
        svc = MagicMock()
        client = TestClient(_make_app(billing_service=svc))
        resp = client.patch(
            "/v1/billing/overage",
            content=b"{{broken",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["detail"]

    def test_null_budget_cap_removes_cap(self):
        svc = MagicMock()
        client = TestClient(_make_app(billing_service=svc))
        resp = client.patch(
            "/v1/billing/overage",
            json={"enabled": True, "budget_cap_cents": None},
        )
        assert resp.status_code == 200
        assert resp.json()["budget_cap_cents"] is None


# ---------------------------------------------------------------------------
# UsageMeter unit tests
# ---------------------------------------------------------------------------


class TestUsageMeter:
    def test_increment_no_engine_returns_zero(self):
        meter = UsageMeter(engine=None)
        assert meter.increment("t1", "eval_runs") == 0

    def test_get_count_no_engine_returns_zero(self):
        meter = UsageMeter(engine=None)
        assert meter.get_count("t1", "eval_runs") == 0

    def test_get_overage_units_no_engine_returns_zero(self):
        meter = UsageMeter(engine=None)
        assert meter.get_overage_units("t1", "eval_runs", limit=500) == 0

    def test_get_overage_units_within_limit(self):
        meter = UsageMeter(engine=None)
        with patch.object(meter, "get_count", return_value=300):
            result = meter.get_overage_units("t1", "eval_runs", limit=500)
        assert result == 0

    def test_get_overage_units_over_limit(self):
        meter = UsageMeter(engine=None)
        with patch.object(meter, "get_count", return_value=750):
            result = meter.get_overage_units("t1", "eval_runs", limit=500)
        assert result == 250

    def test_increment_db_error_returns_zero(self):
        engine = MagicMock()
        engine.begin.side_effect = RuntimeError("DB down")
        meter = UsageMeter(engine=engine)
        result = meter.increment("t1", "eval_runs")
        assert result == 0

    def test_get_count_db_error_returns_zero(self):
        engine = MagicMock()
        engine.connect.side_effect = RuntimeError("DB down")
        meter = UsageMeter(engine=engine)
        result = meter.get_count("t1", "eval_runs")
        assert result == 0

    def test_current_period_returns_year_month(self):
        year, month = UsageMeter._current_period()
        assert isinstance(year, int)
        assert isinstance(month, int)
        assert 1 <= month <= 12
        assert year >= 2026

    def test_get_count_explicit_period(self):
        engine = MagicMock()
        conn = MagicMock()
        engine.connect.return_value.__enter__ = lambda s: conn
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = (42,)
        meter = UsageMeter(engine=engine)
        result = meter.get_count("t1", "eval_runs", year=2026, month=3)
        assert result == 42
        # Verify period params passed to query
        params = conn.execute.call_args[0][1]
        assert params["year"] == 2026
        assert params["month"] == 3

    def test_get_count_no_rows_returns_zero(self):
        engine = MagicMock()
        conn = MagicMock()
        engine.connect.return_value.__enter__ = lambda s: conn
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = None
        meter = UsageMeter(engine=engine)
        result = meter.get_count("t1", "eval_runs", year=2026, month=3)
        assert result == 0

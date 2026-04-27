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


_VALID_BODY = {
    "plan": "pro",
    "interval": "yearly",
    "success_url": "https://app.example.com/success",
    "cancel_url": "https://app.example.com/cancel",
}


class TestCreateCheckout:
    def test_success_returns_checkout_url(self):
        svc = MagicMock()
        svc.create_checkout_url.return_value = "https://checkout.stripe.com/pay/cs_test_123"
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post("/v1/billing/checkout", json=_VALID_BODY)
        assert resp.status_code == 200
        assert resp.json()["checkout_url"] == "https://checkout.stripe.com/pay/cs_test_123"

    def test_missing_plan_returns_400(self):
        svc = MagicMock()
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/checkout",
            json={k: v for k, v in _VALID_BODY.items() if k != "plan"},
        )
        assert resp.status_code == 400
        assert "plan" in resp.json()["detail"].lower()

    def test_invalid_plan_returns_400(self):
        svc = MagicMock()
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/checkout",
            json={**_VALID_BODY, "plan": "enterprise"},
        )
        assert resp.status_code == 400
        assert "plan" in resp.json()["detail"].lower()

    def test_invalid_interval_returns_400(self):
        svc = MagicMock()
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/checkout",
            json={**_VALID_BODY, "interval": "weekly"},
        )
        assert resp.status_code == 400
        assert "interval" in resp.json()["detail"].lower()

    def test_missing_success_url_returns_400(self):
        svc = MagicMock()
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/checkout",
            json={k: v for k, v in _VALID_BODY.items() if k != "success_url"},
        )
        assert resp.status_code == 400

    def test_billing_not_configured_returns_503(self):
        client = TestClient(_make_app(billing_service=None))
        resp = client.post("/v1/billing/checkout", json=_VALID_BODY)
        assert resp.status_code == 503
        assert "Billing not configured" in resp.json()["detail"]

    def test_service_error_does_not_leak_details(self):
        """RuntimeError from service must not propagate internal message."""
        svc = MagicMock()
        svc.create_checkout_url.side_effect = RuntimeError("Stripe API key expired: sk-prod-xxx")
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post("/v1/billing/checkout", json=_VALID_BODY)
        assert resp.status_code == 503
        assert "sk-prod" not in resp.text
        assert "Stripe API key" not in resp.text
        assert "Checkout session creation failed" in resp.json()["detail"]

    def test_invalid_plan_interval_combination_returns_400(self):
        """Service-level ValueError (resolved combo unknown) → 400."""
        svc = MagicMock()
        svc.create_checkout_url.side_effect = ValueError("Unsupported plan/interval")
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post("/v1/billing/checkout", json=_VALID_BODY)
        assert resp.status_code == 400

    def test_stripe_error_returns_502(self):
        """Stripe SDK raising InvalidRequestError must not 500 — 502 with
        a clean message keeps CORS headers on the response and lets the
        dashboard surface a real error instead of 'Failed to fetch'."""
        # Build a fake exception whose __module__ starts with 'stripe.' so
        # the endpoint's module-path check classifies it as a Stripe error
        # without importing the optional SDK in tests.
        fake_stripe_error = type(
            "InvalidRequestError",
            (Exception,),
            {"__module__": "stripe._error"},
        )
        svc = MagicMock()
        svc.create_checkout_url.side_effect = fake_stripe_error(
            "Tax ID collection requires updating business name on the customer."
        )
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post("/v1/billing/checkout", json=_VALID_BODY)
        assert resp.status_code == 502
        # Internal Stripe message must not leak.
        assert "Tax ID" not in resp.text
        assert "Stripe rejected" in resp.json()["detail"]

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

    def test_tenant_plan_interval_forwarded_to_service(self):
        svc = MagicMock()
        svc.create_checkout_url.return_value = "https://checkout.stripe.com/test"
        client = TestClient(_make_app(billing_service=svc))
        client.post("/v1/billing/checkout", json=_VALID_BODY)
        kwargs = svc.create_checkout_url.call_args.kwargs
        assert kwargs["tenant_id"] == "default"  # from make_auth_dep() default
        assert kwargs["plan"] == "pro"
        assert kwargs["interval"] == "yearly"

    def test_customer_email_optional(self):
        """customer_email is optional and forwarded as-is when present."""
        svc = MagicMock()
        svc.create_checkout_url.return_value = "https://checkout.stripe.com/test"
        client = TestClient(_make_app(billing_service=svc))
        client.post(
            "/v1/billing/checkout",
            json={**_VALID_BODY, "customer_email": "user@example.com"},
        )
        kwargs = svc.create_checkout_url.call_args.kwargs
        assert kwargs["customer_email"] == "user@example.com"


# ---------------------------------------------------------------------------
# GET /v1/billing/portal
# ---------------------------------------------------------------------------


class TestCustomerPortal:
    def test_success_returns_portal_url(self):
        svc = MagicMock()
        svc.create_portal_url.return_value = "https://billing.stripe.com/session/xyz"
        client = TestClient(_make_app(billing_service=svc))
        resp = client.get("/v1/billing/portal", params={"return_url": "http://testserver/app"})
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
        resp = client.get("/v1/billing/portal", params={"return_url": "http://testserver/return"})
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

    def test_cross_origin_dashboard_return_url_accepted(self, monkeypatch):
        """Dashboard runs on a different subdomain from the API; ENGRAMIA_DASHBOARD_URL must whitelist it."""
        monkeypatch.setenv("ENGRAMIA_DASHBOARD_URL", "https://app.engramia.dev")
        svc = MagicMock()
        svc.create_portal_url.return_value = "https://billing.stripe.com/session/xyz"
        client = TestClient(_make_app(billing_service=svc))
        resp = client.get(
            "/v1/billing/portal",
            params={"return_url": "https://app.engramia.dev/billing/"},
        )
        assert resp.status_code == 200
        # Service was called with the dashboard URL, not the API base_url
        call_args = svc.create_portal_url.call_args[0]
        assert call_args[1] == "https://app.engramia.dev/billing/"

    def test_return_url_unrelated_origin_rejected(self, monkeypatch):
        """Even with ENGRAMIA_DASHBOARD_URL set, only the dashboard host is allowed."""
        monkeypatch.setenv("ENGRAMIA_DASHBOARD_URL", "https://app.engramia.dev")
        svc = MagicMock()
        client = TestClient(_make_app(billing_service=svc))
        resp = client.get(
            "/v1/billing/portal",
            params={"return_url": "https://evil.example.com/steal"},
        )
        assert resp.status_code == 400
        assert "Invalid return_url" in resp.json()["detail"]
        svc.create_portal_url.assert_not_called()

    def test_return_url_without_dashboard_env_only_api_origin_allowed(self, monkeypatch):
        """When ENGRAMIA_DASHBOARD_URL is unset, cross-origin return_url is rejected."""
        monkeypatch.delenv("ENGRAMIA_DASHBOARD_URL", raising=False)
        svc = MagicMock()
        client = TestClient(_make_app(billing_service=svc))
        resp = client.get(
            "/v1/billing/portal",
            params={"return_url": "https://app.engramia.dev/billing/"},
        )
        assert resp.status_code == 400
        assert "Invalid return_url" in resp.json()["detail"]


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

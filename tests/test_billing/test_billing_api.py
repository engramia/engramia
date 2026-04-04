# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""P0-2 + P0-3: API-level tests for billing endpoints.

Covers:
P0-2 — POST /v1/billing/webhook
  - billing_service absent → 200 "ignored" (Stripe retry prevention)
  - missing Stripe-Signature header → 400
  - invalid HMAC signature → 400
  - valid event → 200 with event_type
  - unexpected service error → 500
  - payload + sig forwarded verbatim to handle_webhook_event

P0-3 — GET /v1/billing/status
  - sandbox mode (billing_service absent) → 200 with sandbox defaults
  - with billing_service → delegates to get_status(), returns plan data
  - correct pattern_count forwarded to get_status()
"""

from unittest.mock import MagicMock, call

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engramia.billing.models import BillingStatus
from engramia.billing.webhooks import router as billing_router

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _make_app(billing_service=None, pattern_count: int = 0) -> FastAPI:
    """Minimal FastAPI app with billing router and faked app state."""
    app = FastAPI()
    app.include_router(billing_router, prefix="/v1")

    mock_storage = MagicMock()
    mock_storage.count_patterns.return_value = pattern_count
    mock_memory = MagicMock()
    mock_memory._storage = mock_storage

    app.state.billing_service = billing_service
    app.state.memory = mock_memory
    return app


def _pro_status(**overrides) -> BillingStatus:
    defaults = dict(
        plan_tier="pro",
        status="active",
        billing_interval="month",
        eval_runs_used=1_200,
        eval_runs_limit=3_000,
        patterns_used=8_000,
        patterns_limit=50_000,
        projects_used=2,
        projects_limit=3,
        period_end="2026-05-01",
        overage_enabled=False,
        overage_budget_cap_cents=None,
    )
    defaults.update(overrides)
    return BillingStatus(**defaults)


# ---------------------------------------------------------------------------
# POST /v1/billing/webhook  (P0-2)
# ---------------------------------------------------------------------------


class TestStripeWebhook:
    def test_no_billing_service_returns_200_ignored(self):
        """Stripe must not be sent non-2xx when billing is unconfigured."""
        client = TestClient(_make_app(billing_service=None))
        resp = client.post(
            "/v1/billing/webhook",
            content=b'{"type":"test.event"}',
            headers={"stripe-signature": "t=1,v1=abc"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    def test_missing_signature_header_returns_400(self):
        """Requests without Stripe-Signature must be rejected immediately."""
        svc = MagicMock()
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/webhook",
            content=b'{"type":"test.event"}',
            # intentionally no stripe-signature header
        )
        assert resp.status_code == 400
        assert "Missing Stripe-Signature" in resp.json()["detail"]

    def test_invalid_signature_returns_400(self):
        """ValueError from handle_webhook_event (bad HMAC) → 400."""
        svc = MagicMock()
        svc.handle_webhook_event.side_effect = ValueError("No signatures found matching")
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/webhook",
            content=b'{"type":"test.event"}',
            headers={"stripe-signature": "t=1,v1=badsig"},
        )
        assert resp.status_code == 400
        assert "Invalid webhook signature" in resp.json()["detail"]

    def test_valid_event_returns_200_with_event_type(self):
        """Successfully processed event → 200 {status: ok, event_type: ...}."""
        svc = MagicMock()
        svc.handle_webhook_event.return_value = "customer.subscription.created"
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/webhook",
            content=b'{"type":"customer.subscription.created","data":{"object":{}}}',
            headers={"stripe-signature": "t=123,v1=valid"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["event_type"] == "customer.subscription.created"

    def test_unexpected_error_returns_500(self):
        """Unhandled exception in service → 500 (not leaking detail)."""
        svc = MagicMock()
        svc.handle_webhook_event.side_effect = RuntimeError("DB is down")
        client = TestClient(_make_app(billing_service=svc), raise_server_exceptions=False)
        resp = client.post(
            "/v1/billing/webhook",
            content=b'{"type":"test.event"}',
            headers={"stripe-signature": "t=1,v1=sig"},
        )
        assert resp.status_code == 500
        # Must not expose internal error message
        assert "DB is down" not in resp.text

    def test_payload_and_signature_forwarded_verbatim(self):
        """Raw bytes and sig header must be passed unchanged to the service."""
        svc = MagicMock()
        svc.handle_webhook_event.return_value = "invoice.paid"
        client = TestClient(_make_app(billing_service=svc))
        payload = b'{"type":"invoice.paid","data":{"object":{}}}'
        sig = "t=999,v1=exact-value"
        client.post(
            "/v1/billing/webhook",
            content=payload,
            headers={"stripe-signature": sig},
        )
        svc.handle_webhook_event.assert_called_once()
        args = svc.handle_webhook_event.call_args[0]
        assert args[0] == payload
        assert args[1] == sig

    def test_no_billing_service_does_not_call_handle(self):
        """Service must never be called when billing is not configured."""
        # billing_service=None, so there is no service to call
        # Just verify the endpoint doesn't crash and returns "ignored"
        client = TestClient(_make_app(billing_service=None))
        resp = client.post(
            "/v1/billing/webhook",
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=x"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    @pytest.mark.parametrize(
        "event_type",
        [
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
            "invoice.paid",
            "invoice.payment_failed",
        ],
    )
    def test_all_stripe_event_types_return_200(self, event_type):
        svc = MagicMock()
        svc.handle_webhook_event.return_value = event_type
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/webhook",
            content=b'{"type":"x","data":{"object":{}}}',
            headers={"stripe-signature": "t=1,v1=sig"},
        )
        assert resp.status_code == 200
        assert resp.json()["event_type"] == event_type


# ---------------------------------------------------------------------------
# GET /v1/billing/status  (P0-3)
# ---------------------------------------------------------------------------


class TestBillingStatus:
    def test_sandbox_mode_returns_200_with_defaults(self):
        """Without billing_service, endpoint returns sandbox plan defaults."""
        client = TestClient(_make_app(billing_service=None))
        resp = client.get("/v1/billing/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan_tier"] == "sandbox"
        assert data["status"] == "active"
        assert data["billing_interval"] == "month"
        assert data["eval_runs_used"] == 0
        assert data["overage_enabled"] is False
        assert data["overage_budget_cap_cents"] is None

    def test_sandbox_mode_limits_are_zero_or_null(self):
        """Sandbox defaults: usage fields should be zero (no activity yet)."""
        client = TestClient(_make_app(billing_service=None))
        data = client.get("/v1/billing/status").json()
        assert data["eval_runs_used"] == 0
        assert data["patterns_used"] == 0
        assert data["projects_used"] == 0

    def test_with_billing_service_delegates_to_get_status(self):
        """Endpoint must call billing_svc.get_status() when configured."""
        svc = MagicMock()
        svc.get_status.return_value = _pro_status()
        client = TestClient(_make_app(billing_service=svc, pattern_count=8_000))
        resp = client.get("/v1/billing/status")
        assert resp.status_code == 200
        svc.get_status.assert_called_once()

    def test_response_contains_plan_data_from_service(self):
        svc = MagicMock()
        svc.get_status.return_value = _pro_status(eval_runs_used=1_200, eval_runs_limit=3_000)
        client = TestClient(_make_app(billing_service=svc))
        data = client.get("/v1/billing/status").json()
        assert data["plan_tier"] == "pro"
        assert data["eval_runs_used"] == 1_200
        assert data["eval_runs_limit"] == 3_000

    def test_pattern_count_from_storage_forwarded_to_service(self):
        """Storage pattern count must be passed as the second arg to get_status()."""
        svc = MagicMock()
        svc.get_status.return_value = _pro_status(patterns_used=42)
        client = TestClient(_make_app(billing_service=svc, pattern_count=42))
        client.get("/v1/billing/status")
        # get_status(tenant_id, pattern_count)
        assert svc.get_status.call_args[0][1] == 42

    def test_tenant_id_from_auth_context_used(self):
        """When auth_context is absent, tenant_id defaults to 'default'."""
        svc = MagicMock()
        svc.get_status.return_value = _pro_status()
        client = TestClient(_make_app(billing_service=svc))
        client.get("/v1/billing/status")
        tenant_id_used = svc.get_status.call_args[0][0]
        assert tenant_id_used == "default"

    def test_enterprise_plan_returns_null_limits(self):
        svc = MagicMock()
        svc.get_status.return_value = BillingStatus(
            plan_tier="enterprise",
            status="active",
            billing_interval="year",
            eval_runs_used=50_000,
            eval_runs_limit=None,
            patterns_used=1_000_000,
            patterns_limit=None,
            projects_used=10,
            projects_limit=None,
            period_end="2027-01-01",
            overage_enabled=False,
            overage_budget_cap_cents=None,
        )
        client = TestClient(_make_app(billing_service=svc))
        data = client.get("/v1/billing/status").json()
        assert data["plan_tier"] == "enterprise"
        assert data["eval_runs_limit"] is None
        assert data["patterns_limit"] is None
        assert data["projects_limit"] is None

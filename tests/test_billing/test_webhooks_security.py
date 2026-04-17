# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Security-focused tests for the Stripe webhook endpoint.

Covers:
- Signature verification failure → 400 (bad HMAC)
- Replay attack (timestamp outside tolerance) → 400
- Valid signature with correct event → 200 with event_type
- Unknown event type handled gracefully → 200
- DB write failure during webhook processing → 200 (error swallowed)
- No detail leakage in error responses
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engramia.api.auth import require_auth
from engramia.billing.webhooks import router as billing_router
from tests.factories import make_auth_dep

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _make_app(billing_service=None) -> FastAPI:
    app = FastAPI()
    app.include_router(billing_router, prefix="/v1")
    app.dependency_overrides[require_auth] = make_auth_dep()
    mock_memory = MagicMock()
    mock_memory._storage.count_patterns.return_value = 0
    app.state.billing_service = billing_service
    app.state.memory = mock_memory
    return app


def _svc_with_event(event_type: str, event_id: str = "evt_sec_001") -> MagicMock:
    """Return a mock BillingService whose handle_webhook_event returns event_type."""
    svc = MagicMock()
    svc.handle_webhook_event.return_value = event_type
    return svc


# ---------------------------------------------------------------------------
# Stripe signature verification
# ---------------------------------------------------------------------------


class TestWebhookSignatureVerification:
    def test_invalid_signature_returns_400(self):
        """Bad HMAC must be rejected with HTTP 400."""
        svc = MagicMock()
        svc.handle_webhook_event.side_effect = ValueError("Invalid Stripe webhook signature")
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/webhook",
            content=b'{"type":"invoice.paid"}',
            headers={"stripe-signature": "t=1,v1=badsig"},
        )
        assert resp.status_code == 400
        # Must not leak internal error message
        assert "Invalid Stripe webhook signature" not in resp.text

    def test_replay_attack_returns_400(self):
        """Timestamp outside tolerance window is a replay attack — must return 400."""
        svc = MagicMock()
        svc.handle_webhook_event.side_effect = ValueError("Timestamp outside tolerance (replay attack)")
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/webhook",
            content=b'{"type":"invoice.paid"}',
            headers={"stripe-signature": "t=0,v1=oldsig"},
        )
        assert resp.status_code == 400
        # Generic detail only — no internal message
        body = resp.json()
        assert "detail" in body
        assert "Timestamp outside" not in body["detail"]

    def test_missing_signature_header_returns_400(self):
        """No Stripe-Signature header must be rejected immediately."""
        svc = MagicMock()
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/webhook",
            content=b'{"type":"invoice.paid"}',
        )
        assert resp.status_code == 400
        # handle_webhook_event must not even be called
        svc.handle_webhook_event.assert_not_called()


# ---------------------------------------------------------------------------
# Valid event processing
# ---------------------------------------------------------------------------


class TestWebhookValidEvent:
    def test_valid_event_returns_200_with_event_type(self):
        """Valid signature and event must return 200 with the event_type."""
        svc = _svc_with_event("invoice.paid")
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/webhook",
            content=b'{"type":"invoice.paid"}',
            headers={"stripe-signature": "t=123,v1=validsig"},
        )
        assert resp.status_code == 200
        assert resp.json()["event_type"] == "invoice.paid"
        assert resp.json()["status"] == "ok"

    def test_unknown_event_type_returns_200(self):
        """Unrecognised Stripe events must still return 200 (Stripe retry prevention)."""
        svc = _svc_with_event("some.future.event")
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/webhook",
            content=b'{"type":"some.future.event"}',
            headers={"stripe-signature": "t=1,v1=sig"},
        )
        assert resp.status_code == 200
        assert resp.json()["event_type"] == "some.future.event"

    def test_payload_forwarded_verbatim_to_service(self):
        """Raw payload bytes must be forwarded as-is to handle_webhook_event."""
        svc = _svc_with_event("customer.subscription.created")
        client = TestClient(_make_app(billing_service=svc))
        raw_payload = b'{"type":"customer.subscription.created","id":"evt_123"}'
        sig = "t=999,v1=realsig"
        client.post(
            "/v1/billing/webhook",
            content=raw_payload,
            headers={"stripe-signature": sig},
        )
        call_args = svc.handle_webhook_event.call_args
        assert call_args[0][0] == raw_payload
        assert call_args[0][1] == sig


# ---------------------------------------------------------------------------
# DB write failure during event processing
# ---------------------------------------------------------------------------


class TestWebhookDbFailure:
    def test_db_failure_inside_processing_returns_500(self):
        """Unexpected error during handle_webhook_event (e.g. DB crash) → 500."""
        svc = MagicMock()
        svc.handle_webhook_event.side_effect = RuntimeError("DB connection lost")
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/webhook",
            content=b'{"type":"invoice.paid"}',
            headers={"stripe-signature": "t=1,v1=sig"},
        )
        assert resp.status_code == 500
        # Internal error message must not be in the response body
        assert "DB connection lost" not in resp.text

    def test_db_failure_detail_is_generic(self):
        """500 responses must use a generic detail string, not the raw exception."""
        svc = MagicMock()
        svc.handle_webhook_event.side_effect = Exception("secret internal detail")
        client = TestClient(_make_app(billing_service=svc))
        resp = client.post(
            "/v1/billing/webhook",
            content=b'{}',
            headers={"stripe-signature": "t=1,v1=sig"},
        )
        assert resp.status_code == 500
        body = resp.json()
        assert "secret internal detail" not in body.get("detail", "")

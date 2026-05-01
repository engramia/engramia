# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for the /v1/waitlist/request endpoint (cloud onboarding Variant A).

Covers the public submission flow:
  - Pydantic validation (email, country code, plan_interest enum,
    conditional use_case requirement)
  - DB persistence
  - Ack + admin-notify email best-effort dispatch
  - Failure modes (no engine, SMTP not configured)
"""

from __future__ import annotations

import datetime
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engramia.api.waitlist import router


@pytest.fixture
def captured_inserts():
    """Records every INSERT param dict for assertion."""
    return []


@pytest.fixture
def mock_engine(captured_inserts):
    engine = MagicMock()
    conn = MagicMock()

    def _execute(stmt, params=None):
        result = MagicMock()
        if params and "email" in (params or {}) and "plan" in (params or {}):
            captured_inserts.append(dict(params))
            row = MagicMock()
            row.__getitem__ = lambda self, idx: (
                uuid.uuid4() if idx == 0 else datetime.datetime(2026, 5, 1, 12, 0, 0)
            )
            result.fetchone.return_value = row
        return result

    conn.execute.side_effect = _execute
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    return engine


@pytest.fixture
def app(mock_engine):
    a = FastAPI()
    a.state.auth_engine = mock_engine
    a.include_router(router, prefix="/v1")
    return a


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


_VALID_BODY = {
    "email": "user@example.com",
    "name": "Jane Doe",
    "plan_interest": "developer",
    "country": "CZ",
    "use_case": None,
    "company_name": None,
    "referral_source": None,
}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestWaitlistRequestHappyPath:
    @patch("engramia.email.send_email")
    def test_developer_plan_no_use_case_returns_201(
        self, _send, client, captured_inserts
    ):
        resp = client.post("/v1/waitlist/request", json=_VALID_BODY)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "pending"
        assert "request_id" in body
        assert "2 business days" in body["next_step"]
        # DB INSERT received the right shape.
        assert len(captured_inserts) == 1
        assert captured_inserts[0]["email"] == "user@example.com"
        assert captured_inserts[0]["plan"] == "developer"
        assert captured_inserts[0]["country"] == "CZ"

    @patch("engramia.email.send_email")
    def test_pro_plan_with_use_case_accepted(self, _send, client, captured_inserts):
        body = {
            **_VALID_BODY,
            "plan_interest": "pro",
            "use_case": "Building an internal docs Q&A bot for ~50 employees.",
        }
        resp = client.post("/v1/waitlist/request", json=body)
        assert resp.status_code == 201
        assert captured_inserts[0]["plan"] == "pro"
        assert captured_inserts[0]["uc"].startswith("Building")

    @patch("engramia.email.send_email")
    def test_email_lowercased_before_persist(self, _send, client, captured_inserts):
        body = {**_VALID_BODY, "email": "MiXeD@Example.COM"}
        client.post("/v1/waitlist/request", json=body)
        assert captured_inserts[0]["email"] == "mixed@example.com"

    @patch("engramia.email.send_email")
    def test_country_uppercased_before_persist(
        self, _send, client, captured_inserts
    ):
        body = {**_VALID_BODY, "country": "cz"}
        client.post("/v1/waitlist/request", json=body)
        assert captured_inserts[0]["country"] == "CZ"

    @patch("engramia.email.send_email")
    def test_optional_fields_propagate(self, _send, client, captured_inserts):
        body = {
            **_VALID_BODY,
            "company_name": "Acme s.r.o.",
            "referral_source": "Hacker News",
        }
        client.post("/v1/waitlist/request", json=body)
        assert captured_inserts[0]["company"] == "Acme s.r.o."
        assert captured_inserts[0]["ref"] == "Hacker News"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestWaitlistValidation:
    def test_invalid_email_returns_422(self, client):
        body = {**_VALID_BODY, "email": "not-an-email"}
        resp = client.post("/v1/waitlist/request", json=body)
        assert resp.status_code == 422

    def test_invalid_country_code_returns_422(self, client):
        body = {**_VALID_BODY, "country": "Czech"}  # not 2-letter ISO
        resp = client.post("/v1/waitlist/request", json=body)
        assert resp.status_code == 422

    def test_unknown_plan_interest_returns_422(self, client):
        body = {**_VALID_BODY, "plan_interest": "platinum"}
        resp = client.post("/v1/waitlist/request", json=body)
        assert resp.status_code == 422

    def test_paid_plan_without_use_case_returns_422(self, client):
        body = {**_VALID_BODY, "plan_interest": "pro", "use_case": None}
        resp = client.post("/v1/waitlist/request", json=body)
        assert resp.status_code == 422
        body_json = resp.json()
        assert "use_case is required" in str(body_json).lower() or "use_case" in str(body_json).lower()

    def test_paid_plan_with_blank_use_case_returns_422(self, client):
        body = {**_VALID_BODY, "plan_interest": "team", "use_case": "   "}
        resp = client.post("/v1/waitlist/request", json=body)
        assert resp.status_code == 422

    def test_developer_plan_no_use_case_is_OK(self, client):
        body = {**_VALID_BODY, "plan_interest": "developer", "use_case": None}
        with patch("engramia.email.send_email"):
            resp = client.post("/v1/waitlist/request", json=body)
        assert resp.status_code == 201

    def test_missing_required_field_returns_422(self, client):
        for missing in ("email", "name", "plan_interest", "country"):
            body = {k: v for k, v in _VALID_BODY.items() if k != missing}
            resp = client.post("/v1/waitlist/request", json=body)
            assert resp.status_code == 422, f"missing {missing} should fail"

    def test_excessive_use_case_length_rejected(self, client):
        body = {
            **_VALID_BODY,
            "plan_interest": "pro",
            "use_case": "x" * 1001,
        }
        resp = client.post("/v1/waitlist/request", json=body)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Email best-effort dispatch
# ---------------------------------------------------------------------------


class TestWaitlistEmailDispatch:
    @patch("engramia.email.send_email")
    def test_both_emails_sent_on_success(self, mock_send, client):
        client.post("/v1/waitlist/request", json=_VALID_BODY)
        # 2 calls — ack + admin notify.
        assert mock_send.call_count == 2

    @patch("engramia.email.send_email")
    def test_admin_notify_goes_to_support_address(self, mock_send, client):
        client.post("/v1/waitlist/request", json=_VALID_BODY)
        # Find the admin notify call.
        admin_calls = [
            c for c in mock_send.call_args_list
            if c.kwargs.get("to") == "support@engramia.dev"
        ]
        assert len(admin_calls) == 1

    @patch("engramia.email.send_email")
    def test_admin_notify_address_overridable_via_env(
        self, mock_send, client, monkeypatch
    ):
        monkeypatch.setenv("ENGRAMIA_WAITLIST_ADMIN_EMAIL", "ops@example.com")
        client.post("/v1/waitlist/request", json=_VALID_BODY)
        admin_calls = [
            c for c in mock_send.call_args_list
            if c.kwargs.get("to") == "ops@example.com"
        ]
        assert len(admin_calls) == 1

    def test_smtp_not_configured_does_not_fail_request(
        self, client, captured_inserts
    ):
        from engramia.email import EmailNotConfigured

        with patch(
            "engramia.email.send_email",
            side_effect=EmailNotConfigured("test"),
        ):
            resp = client.post("/v1/waitlist/request", json=_VALID_BODY)
        # DB row still persisted; endpoint returns 201.
        assert resp.status_code == 201
        assert len(captured_inserts) == 1


# ---------------------------------------------------------------------------
# No engine
# ---------------------------------------------------------------------------


class TestWaitlistNoEngine:
    def test_503_when_no_auth_engine(self):
        a = FastAPI()
        a.state.auth_engine = None
        a.include_router(router, prefix="/v1")
        c = TestClient(a, raise_server_exceptions=False)

        resp = c.post("/v1/waitlist/request", json=_VALID_BODY)
        assert resp.status_code == 503

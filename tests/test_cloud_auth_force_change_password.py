# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for the force-change-password flow + register gate.

Phase 6.5 cloud onboarding (Variant A) introduced:

  - ``ENGRAMIA_REGISTRATION_ENABLED`` gate on POST /auth/register
  - ``LoginResponse.must_change_password`` field exposed to the Dashboard
  - POST /auth/change-password endpoint that clears the flag

This file exercises all three end-to-end via the FastAPI TestClient,
mocking the DB engine and password helpers.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engramia.api.cloud_auth import router


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    engine._conn = conn
    return engine


@pytest.fixture
def app(mock_engine):
    a = FastAPI()
    a.include_router(router, prefix="/auth")
    a.state.auth_engine = mock_engine
    return a


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Register gate
# ---------------------------------------------------------------------------


class TestRegisterGate:
    def test_disabled_by_default_returns_503(self, client, monkeypatch):
        monkeypatch.delenv("ENGRAMIA_REGISTRATION_ENABLED", raising=False)
        resp = client.post(
            "/auth/register",
            json={
                "email": "new@example.com",
                "password": "Aa1!aaaaaa",
                "name": "Test",
            },
        )
        assert resp.status_code == 503
        body = resp.json()
        # FastAPI nests structured detail under "detail"
        detail = body["detail"]
        assert detail["error_code"] == "REGISTRATION_CLOSED"
        assert "request access" in detail["detail"].lower()
        assert "engramia.dev/request-access" in detail["detail"]

    @pytest.mark.parametrize("flag_value", ["false", "0", "no", "off", ""])
    def test_falsy_flag_values_keep_gate_closed(
        self, client, monkeypatch, flag_value
    ):
        monkeypatch.setenv("ENGRAMIA_REGISTRATION_ENABLED", flag_value)
        resp = client.post(
            "/auth/register",
            json={
                "email": "x@e.cz",
                "password": "Aa1!aaaaaa",
                "name": "x",
            },
        )
        assert resp.status_code == 503

    @pytest.mark.parametrize("flag_value", ["true", "1", "yes", "on", "True"])
    def test_truthy_flag_opens_gate_to_existing_logic(
        self, client, mock_engine, monkeypatch, flag_value
    ):
        """When the flag is on, the endpoint reaches the existing logic
        (which then errors on missing engine wiring or duplicate email —
        we just verify the 503 gate doesn't fire)."""
        monkeypatch.setenv("ENGRAMIA_REGISTRATION_ENABLED", flag_value)
        # Force a duplicate-email path so we get a determined 409 (proves
        # we didn't 503).
        mock_engine._conn.execute.return_value.fetchone.return_value = (1,)

        resp = client.post(
            "/auth/register",
            json={
                "email": "dup@example.com",
                "password": "Aa1!aaaaaa",
                "name": "Dup",
            },
        )
        assert resp.status_code != 503  # not gated
        # Either 409 (duplicate) or another known code, not the closed 503.
        assert resp.status_code in (409, 422, 500)


# ---------------------------------------------------------------------------
# Login carries must_change_password
# ---------------------------------------------------------------------------


_FAKE_PAYLOAD = {
    "sub": "u-1",
    "tenant_id": "t-1",
    "email": "user@example.com",
    "type": "access",
}


class TestLoginMustChangePassword:
    @patch("engramia.api.cloud_auth._verify_password", return_value=True)
    @patch("engramia.api.cloud_auth._make_token", return_value="tok.access")
    @patch("engramia.api.cloud_auth._check_login_rate")
    def test_login_returns_must_change_true_when_flag_set(
        self, _rate, _make, _verify, client, mock_engine
    ):
        # SELECT cloud_users returns the new 5-column shape.
        mock_engine._conn.execute.return_value.fetchone.return_value = (
            "u-1", "$2b$fake", "t-1", True, True,  # must_change_password=true
        )
        resp = client.post(
            "/auth/login",
            json={"email": "user@example.com", "password": "old-password"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["must_change_password"] is True
        assert body["access_token"] == "tok.access"

    @patch("engramia.api.cloud_auth._verify_password", return_value=True)
    @patch("engramia.api.cloud_auth._make_token", return_value="tok.access")
    @patch("engramia.api.cloud_auth._check_login_rate")
    def test_login_returns_must_change_false_for_normal_user(
        self, _rate, _make, _verify, client, mock_engine
    ):
        mock_engine._conn.execute.return_value.fetchone.return_value = (
            "u-1", "$2b$fake", "t-1", True, False,  # must_change_password=false
        )
        resp = client.post(
            "/auth/login",
            json={"email": "user@example.com", "password": "real-password"},
        )
        assert resp.status_code == 200
        assert resp.json()["must_change_password"] is False


# ---------------------------------------------------------------------------
# /auth/change-password
# ---------------------------------------------------------------------------


class TestChangePassword:
    @patch("engramia.api.cloud_auth._decode_token", return_value=_FAKE_PAYLOAD)
    @patch("engramia.api.cloud_auth._verify_password", return_value=True)
    @patch("engramia.api.cloud_auth._hash_password", return_value="$2b$new")
    @patch("engramia.api.cloud_auth._make_token", return_value="tok.fresh")
    def test_happy_path_updates_hash_and_clears_flag(
        self, _make, _hash, _verify, _decode, client, mock_engine
    ):
        mock_engine._conn.execute.return_value.fetchone.return_value = (
            "$2b$old", True,
        )
        resp = client.post(
            "/auth/change-password",
            headers={"Authorization": "Bearer fake.jwt"},
            json={"current_password": "OldPass1!", "new_password": "NewPass1!"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["access_token"] == "tok.fresh"
        assert body["must_change_password"] is False

    def test_missing_bearer_returns_401(self, client):
        resp = client.post(
            "/auth/change-password",
            json={"current_password": "x", "new_password": "Aa1!aaaaaaa"},
        )
        assert resp.status_code == 401

    @patch("engramia.api.cloud_auth._decode_token", return_value=_FAKE_PAYLOAD)
    @patch("engramia.api.cloud_auth._verify_password", return_value=False)
    def test_wrong_current_password_returns_400(
        self, _verify, _decode, client, mock_engine
    ):
        mock_engine._conn.execute.return_value.fetchone.return_value = (
            "$2b$old", True,
        )
        resp = client.post(
            "/auth/change-password",
            headers={"Authorization": "Bearer fake.jwt"},
            json={"current_password": "wrong", "new_password": "NewPass1!"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["detail"]["error_code"] == "current_password_mismatch"

    @patch("engramia.api.cloud_auth._decode_token", return_value=_FAKE_PAYLOAD)
    @patch("engramia.api.cloud_auth._verify_password", return_value=True)
    def test_new_same_as_current_returns_400(
        self, _verify, _decode, client, mock_engine
    ):
        mock_engine._conn.execute.return_value.fetchone.return_value = (
            "$2b$old", True,
        )
        resp = client.post(
            "/auth/change-password",
            headers={"Authorization": "Bearer fake.jwt"},
            json={"current_password": "Same1!aaa", "new_password": "Same1!aaa"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["detail"]["error_code"] == "new_password_same_as_current"

    def test_weak_new_password_rejected_by_pydantic(self, client):
        # No bearer needed — Pydantic validation runs before auth check.
        resp = client.post(
            "/auth/change-password",
            headers={"Authorization": "Bearer fake.jwt"},
            json={"current_password": "old", "new_password": "weak"},
        )
        # Either 422 (Pydantic) or 400 (depending on order) — both acceptable.
        assert resp.status_code in (400, 422)

    @patch("engramia.api.cloud_auth._decode_token", return_value=_FAKE_PAYLOAD)
    def test_user_not_found_returns_404(self, _decode, client, mock_engine):
        mock_engine._conn.execute.return_value.fetchone.return_value = None
        resp = client.post(
            "/auth/change-password",
            headers={"Authorization": "Bearer fake.jwt"},
            json={"current_password": "x", "new_password": "NewPass1!"},
        )
        assert resp.status_code == 404

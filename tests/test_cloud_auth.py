# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Unit tests for cloud user registration and authentication endpoints.

All DB calls are mocked — no real database required.
passlib/PyJWT are patched so the tests run without the cloud-auth extra installed.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engramia.api.cloud_auth import router

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    conn = MagicMock()
    # Wire up both context-manager protocols used by the endpoints.
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


# Shared JWT payload returned by _decode_token mock.
_FAKE_PAYLOAD = {
    "sub": "user-abc",
    "tenant_id": "testuser",
    "email": "test@example.com",
    "role": "owner",
    "type": "access",
}

_FAKE_REFRESH_PAYLOAD = {**_FAKE_PAYLOAD, "type": "refresh"}

# Shared registration result returned by _create_registration mock.
_FAKE_REG = {
    "user_id": "user-abc",
    "tenant_id": "testuser",
    "project_id": "proj-xyz",
    "api_key": "engramia-deadbeef" + "0" * 24,
}


# ---------------------------------------------------------------------------
# test_register_success
# ---------------------------------------------------------------------------


@patch("engramia.api.cloud_auth._create_registration", return_value=_FAKE_REG)
@patch("engramia.api.cloud_auth._hash_password", return_value="$2b$fake")
@patch("engramia.api.cloud_auth._make_token", return_value="tok.access")
@patch("engramia.api.audit.log_event")
@patch("engramia.api.audit.log_db_event")
def test_register_success(mock_log_db, mock_log, mock_tok, mock_hash, mock_create, client, mock_engine):
    # No existing user with this email.
    mock_engine._conn.execute.return_value.fetchone.return_value = None

    resp = client.post(
        "/auth/register",
        json={"email": "test@example.com", "password": "securepass123"},
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "test@example.com"
    assert data["tenant_id"] == "testuser"
    assert data["api_key"].startswith("engramia-")
    assert "access_token" in data
    assert "refresh_token" in data
    mock_hash.assert_called_once_with("securepass123")
    mock_create.assert_called_once()


# ---------------------------------------------------------------------------
# test_register_duplicate_email
# ---------------------------------------------------------------------------


@patch("engramia.api.cloud_auth._check_register_rate")
def test_register_duplicate_email(mock_rate, client, mock_engine):
    # Simulate existing row for this email.
    mock_engine._conn.execute.return_value.fetchone.return_value = (1,)

    resp = client.post(
        "/auth/register",
        json={"email": "dupe@example.com", "password": "securepass123"},
    )

    assert resp.status_code == 409
    assert "already registered" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# test_register_invalid_email
# ---------------------------------------------------------------------------


@patch("engramia.api.cloud_auth._check_register_rate")
def test_register_invalid_email(mock_rate, client, mock_engine):
    resp = client.post(
        "/auth/register",
        json={"email": "not-an-email", "password": "securepass123"},
    )

    assert resp.status_code == 422
    assert "Invalid email" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# test_login_success
# ---------------------------------------------------------------------------


@patch("engramia.api.cloud_auth._verify_password", return_value=True)
@patch("engramia.api.cloud_auth._make_token", return_value="tok.access")
def test_login_success(mock_tok, mock_verify, client, mock_engine):
    mock_engine._conn.execute.return_value.fetchone.return_value = (
        "user-abc",
        "$2b$fake_hash",
        "testuser",
    )

    resp = client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "securepass123"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@example.com"
    assert data["tenant_id"] == "testuser"
    assert "access_token" in data
    assert "refresh_token" in data
    mock_verify.assert_called_once_with("securepass123", "$2b$fake_hash")


# ---------------------------------------------------------------------------
# test_login_wrong_password
# ---------------------------------------------------------------------------


@patch("engramia.api.cloud_auth._verify_password", return_value=False)
@patch("engramia.api.audit.log_event")
def test_login_wrong_password(mock_log, mock_verify, client, mock_engine):
    mock_engine._conn.execute.return_value.fetchone.return_value = (
        "user-abc",
        "$2b$fake_hash",
        "testuser",
    )

    resp = client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "wrongpassword"},
    )

    assert resp.status_code == 401
    assert "Invalid credentials" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# test_login_unknown_email
# ---------------------------------------------------------------------------


@patch("engramia.api.audit.log_event")
def test_login_unknown_email(mock_log, client, mock_engine):
    mock_engine._conn.execute.return_value.fetchone.return_value = None

    resp = client.post(
        "/auth/login",
        json={"email": "ghost@example.com", "password": "securepass123"},
    )

    assert resp.status_code == 401
    assert "Invalid credentials" in resp.json()["detail"]
    mock_log.assert_called_once()


# ---------------------------------------------------------------------------
# test_me_with_valid_token
# ---------------------------------------------------------------------------


@patch("engramia.api.cloud_auth._decode_token", return_value=_FAKE_PAYLOAD)
def test_me_with_valid_token(mock_decode, client, mock_engine):
    mock_engine._conn.execute.return_value.fetchone.return_value = (
        "user-abc",
        "test@example.com",
        "testuser",
        "Test User",
        "credentials",
        "2026-04-05T00:00:00",
    )

    resp = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer valid.token.here"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == "user-abc"
    assert data["email"] == "test@example.com"
    assert data["tenant_id"] == "testuser"
    assert data["provider"] == "credentials"
    mock_decode.assert_called_once_with("valid.token.here")


# ---------------------------------------------------------------------------
# test_me_with_invalid_token
# ---------------------------------------------------------------------------


def test_me_with_invalid_token(client, mock_engine):
    # No Authorization header at all.
    resp = client.get("/auth/me")
    assert resp.status_code == 401

    # Malformed header (no Bearer prefix).
    resp = client.get("/auth/me", headers={"Authorization": "Token abc"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# test_refresh_with_valid_refresh_token
# ---------------------------------------------------------------------------


@patch("engramia.api.cloud_auth._decode_token", return_value=_FAKE_REFRESH_PAYLOAD)
@patch("engramia.api.cloud_auth._make_token", return_value="new.access.token")
def test_refresh_with_valid_refresh_token(mock_make, mock_decode, client):
    resp = client.post(
        "/auth/refresh",
        headers={"Authorization": "Bearer valid.refresh.token"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] == "new.access.token"
    mock_decode.assert_called_once_with("valid.refresh.token", require_refresh=True)


# ---------------------------------------------------------------------------
# test_register_rate_limit
# ---------------------------------------------------------------------------


@patch("engramia.api.cloud_auth._check_register_rate", side_effect=Exception("rate limit hit"))
def test_register_rate_limit_called(mock_rate, client, mock_engine):
    """Rate limit check is invoked before any DB access."""
    client.post(
        "/auth/register",
        json={"email": "ratelimited@example.com", "password": "securepass123"},
    )
    # The mock raises a generic Exception which becomes a 500 in test mode,
    # but the important assertion is that _check_register_rate was called.
    mock_rate.assert_called_once()

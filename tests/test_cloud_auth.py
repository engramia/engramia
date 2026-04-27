# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Unit tests for cloud user registration and authentication endpoints.

All DB calls are mocked — no real database required.
passlib/PyJWT are patched so the tests run without the cloud-auth extra installed.
"""

from datetime import UTC
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
@patch("engramia.api.cloud_auth._create_verification_token", return_value="verify-token-xyz")
@patch("engramia.api.cloud_auth._send_verification_email", return_value=True)
@patch("engramia.api.audit.log_event")
@patch("engramia.api.audit.log_db_event")
def test_register_success(mock_log_db, mock_log, mock_send, mock_vtok, mock_hash, mock_create, client, mock_engine):
    # No existing user with this email.
    mock_engine._conn.execute.return_value.fetchone.return_value = None

    resp = client.post(
        "/auth/register",
        json={"email": "test@example.com", "password": "SecurePass123!"},
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "test@example.com"
    assert data["tenant_id"] == "testuser"
    assert data["api_key"].startswith("engramia-")
    # No tokens are returned until the user verifies their email.
    assert "access_token" not in data
    assert "refresh_token" not in data
    assert data["verification_required"] is True
    assert data["delivery_status"] == "sent"
    mock_hash.assert_called_once_with("SecurePass123!")
    mock_create.assert_called_once()
    mock_send.assert_called_once()


@patch("engramia.api.cloud_auth._create_registration", return_value=_FAKE_REG)
@patch("engramia.api.cloud_auth._hash_password", return_value="$2b$fake")
@patch("engramia.api.cloud_auth._create_verification_token", return_value="verify-token-xyz")
@patch("engramia.api.cloud_auth._send_verification_email", return_value=False)
@patch("engramia.api.audit.log_event")
@patch("engramia.api.audit.log_db_event")
def test_register_email_delivery_failed(
    mock_log_db, mock_log, mock_send, mock_vtok, mock_hash, mock_create, client, mock_engine
):
    """Registration still succeeds when SMTP is down; frontend gets delivery_status=failed."""
    mock_engine._conn.execute.return_value.fetchone.return_value = None

    resp = client.post(
        "/auth/register",
        json={"email": "test@example.com", "password": "SecurePass123!"},
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["delivery_status"] == "failed"
    assert data["verification_required"] is True


# ---------------------------------------------------------------------------
# test_register_duplicate_email
# ---------------------------------------------------------------------------


@patch("engramia.api.cloud_auth._check_register_rate")
def test_register_duplicate_email(mock_rate, client, mock_engine):
    # Simulate existing row for this email.
    mock_engine._conn.execute.return_value.fetchone.return_value = (1,)

    resp = client.post(
        "/auth/register",
        json={"email": "dupe@example.com", "password": "SecurePass123!"},
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
        json={"email": "not-an-email", "password": "SecurePass123!"},
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
        True,
    )

    resp = client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "SecurePass123!"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@example.com"
    assert data["tenant_id"] == "testuser"
    assert "access_token" in data
    assert "refresh_token" in data
    mock_verify.assert_called_once_with("SecurePass123!", "$2b$fake_hash")


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
        True,
    )

    resp = client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "WrongPass123!"},
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
        json={"email": "ghost@example.com", "password": "SecurePass123!"},
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
        json={"email": "ratelimited@example.com", "password": "SecurePass123!"},
    )
    # The mock raises a generic Exception which becomes a 500 in test mode,
    # but the important assertion is that _check_register_rate was called.
    mock_rate.assert_called_once()


# ---------------------------------------------------------------------------
# Login — email not verified
# ---------------------------------------------------------------------------


@patch("engramia.api.cloud_auth._verify_password", return_value=True)
@patch("engramia.api.audit.log_event")
def test_login_unverified_returns_structured_error(mock_log, mock_verify, client, mock_engine):
    """Login with valid password but unverified email returns 403 with structured code."""
    mock_engine._conn.execute.return_value.fetchone.return_value = (
        "user-abc",
        "$2b$fake_hash",
        "testuser",
        False,  # email_verified = False
    )

    resp = client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "SecurePass123!"},
    )

    assert resp.status_code == 403
    body = resp.json()
    # Dict-style detail bubbles up through the app-level exception handler
    # as error_code; in the bare TestClient it lives under detail or
    # error_code depending on whether _register_exception_handlers ran.
    # Both the bare router and create_app() expose the same info, just at
    # slightly different paths.
    combined = str(body)
    assert "email_not_verified" in combined
    mock_log.assert_called()


# ---------------------------------------------------------------------------
# /auth/verify
# ---------------------------------------------------------------------------


def _make_verify_row(expires_at, consumed_at=None, already_verified=False):
    """Build the row tuple returned by the /verify SELECT: (user_id, expires_at, consumed_at, email_verified)."""
    return ("user-abc", expires_at, consumed_at, already_verified)


def test_verify_success(client, mock_engine):
    from datetime import datetime, timedelta

    future = datetime.now(UTC) + timedelta(hours=12)
    mock_engine._conn.execute.return_value.fetchone.return_value = _make_verify_row(future)

    resp = client.post("/auth/verify", json={"token": "a" * 32})

    assert resp.status_code == 200
    body = resp.json()
    assert body["verified"] is True


def test_verify_token_expired(client, mock_engine):
    from datetime import datetime, timedelta

    past = datetime.now(UTC) - timedelta(hours=1)
    mock_engine._conn.execute.return_value.fetchone.return_value = _make_verify_row(past)

    resp = client.post("/auth/verify", json={"token": "a" * 32})

    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"].lower()


def test_verify_token_already_consumed(client, mock_engine):
    from datetime import datetime, timedelta

    future = datetime.now(UTC) + timedelta(hours=12)
    consumed = datetime.now(UTC) - timedelta(minutes=5)
    # User not yet verified but token already burned → 400 (rare race).
    mock_engine._conn.execute.return_value.fetchone.return_value = _make_verify_row(
        future, consumed_at=consumed, already_verified=False
    )

    resp = client.post("/auth/verify", json={"token": "a" * 32})

    assert resp.status_code == 400
    assert "already been used" in resp.json()["detail"].lower()


def test_verify_token_idempotent_when_already_verified(client, mock_engine):
    """Double-click on the verify link returns success if the user is already verified."""
    from datetime import datetime, timedelta

    future = datetime.now(UTC) + timedelta(hours=12)
    consumed = datetime.now(UTC) - timedelta(minutes=5)
    mock_engine._conn.execute.return_value.fetchone.return_value = _make_verify_row(
        future, consumed_at=consumed, already_verified=True
    )

    resp = client.post("/auth/verify", json={"token": "a" * 32})

    assert resp.status_code == 200
    body = resp.json()
    assert body["verified"] is True
    assert body["email_already_verified"] is True


def test_verify_token_not_found(client, mock_engine):
    mock_engine._conn.execute.return_value.fetchone.return_value = None

    resp = client.post("/auth/verify", json={"token": "a" * 32})

    assert resp.status_code == 400
    assert "invalid" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# /auth/resend-verification
# ---------------------------------------------------------------------------


@patch("engramia.api.cloud_auth._check_resend_rate")
@patch("engramia.api.cloud_auth._create_verification_token", return_value="new-token")
@patch("engramia.api.cloud_auth._send_verification_email", return_value=True)
def test_resend_verification_success(mock_send, mock_vtok, mock_rate, client, mock_engine):
    # Unverified user exists.
    mock_engine._conn.execute.return_value.fetchone.return_value = (
        "user-abc",
        "Test User",
        False,
    )

    resp = client.post("/auth/resend-verification", json={"email": "test@example.com"})

    assert resp.status_code == 202
    mock_send.assert_called_once()


@patch("engramia.api.cloud_auth._check_resend_rate")
@patch("engramia.api.cloud_auth._send_verification_email")
def test_resend_verification_unknown_email_returns_202(mock_send, mock_rate, client, mock_engine):
    """Unknown email returns 202 without sending — account-enumeration protection."""
    mock_engine._conn.execute.return_value.fetchone.return_value = None

    resp = client.post("/auth/resend-verification", json={"email": "ghost@example.com"})

    assert resp.status_code == 202
    mock_send.assert_not_called()


@patch("engramia.api.cloud_auth._check_resend_rate")
@patch("engramia.api.cloud_auth._send_verification_email")
def test_resend_verification_already_verified_silent(mock_send, mock_rate, client, mock_engine):
    """Already-verified users get 202 with no email sent — avoids leaking verification state."""
    mock_engine._conn.execute.return_value.fetchone.return_value = (
        "user-abc",
        "Test User",
        True,  # email_verified = True
    )

    resp = client.post("/auth/resend-verification", json={"email": "verified@example.com"})

    assert resp.status_code == 202
    mock_send.assert_not_called()


def test_resend_verification_invalid_email_format(client, mock_engine):
    """Malformed email short-circuits before DB access — still returns 202 (enumeration protection)."""
    resp = client.post("/auth/resend-verification", json={"email": "not-an-email"})
    assert resp.status_code == 202


def test_resend_verification_rate_limit():
    """The rate limiter raises 429 after 3 calls within a 60-second window."""
    from engramia.api.cloud_auth import _check_resend_rate

    # Burn 3 slots for the same (IP, email) within a minute — should be fine.
    for _ in range(3):
        _check_resend_rate("1.2.3.4", "burst@example.com")
    # 4th raises.
    with pytest.raises(Exception) as exc:
        _check_resend_rate("1.2.3.4", "burst@example.com")
    assert "Too many" in str(exc.value) or "429" in str(exc.value)


# ---------------------------------------------------------------------------
# Self-service account deletion — POST /me/deletion-request
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_deletion_rate_limiter():
    """Clear the deletion-request rate limiter between tests so per-test IP
    counters don't leak across cases (TestClient reuses 'testclient' as IP)."""
    from engramia.api.cloud_auth import _deletion_request_rate

    _deletion_request_rate.clear()
    yield
    _deletion_request_rate.clear()


@patch("engramia.api.cloud_auth._decode_token", return_value=_FAKE_PAYLOAD)
@patch("engramia.api.cloud_auth._has_pending_deletion_request", return_value=False)
@patch("engramia.api.cloud_auth._create_deletion_token", return_value="del-token-abc")
@patch("engramia.api.cloud_auth._send_deletion_email", return_value=True)
@patch("engramia.api.audit.log_db_event")
def test_request_deletion_success(mock_log_db, mock_send, mock_token, mock_pending, mock_decode, client, mock_engine):
    # cloud_user lookup: (email, name, deleted_at)
    mock_engine._conn.execute.return_value.fetchone.return_value = (
        "test@example.com",
        "Test User",
        None,
    )

    resp = client.post(
        "/auth/me/deletion-request",
        headers={"Authorization": "Bearer valid.token.here"},
        json={"reason": "no longer needed"},
    )

    assert resp.status_code == 202
    data = resp.json()
    assert data["delivery_status"] == "sent"
    assert "expires_at" in data

    mock_token.assert_called_once()
    # Reason is forwarded to the token writer for analytics.
    assert mock_token.call_args.kwargs.get("reason") == "no longer needed" or (
        len(mock_token.call_args.args) >= 3 and mock_token.call_args.args[2] == "no longer needed"
    )
    mock_send.assert_called_once()
    mock_log_db.assert_called_once()


@patch("engramia.api.cloud_auth._decode_token", return_value=_FAKE_PAYLOAD)
def test_request_deletion_user_already_soft_deleted(mock_decode, client, mock_engine):
    """If the user row was soft-deleted previously, the JWT is stale → 404."""
    import datetime

    mock_engine._conn.execute.return_value.fetchone.return_value = (
        "test@example.com",
        "Test User",
        datetime.datetime(2026, 4, 20, tzinfo=datetime.UTC),
    )

    resp = client.post(
        "/auth/me/deletion-request",
        headers={"Authorization": "Bearer stale.token"},
    )

    assert resp.status_code == 404


@patch("engramia.api.cloud_auth._decode_token", return_value=_FAKE_PAYLOAD)
@patch("engramia.api.cloud_auth._has_pending_deletion_request", return_value=True)
def test_request_deletion_already_pending(mock_pending, mock_decode, client, mock_engine):
    mock_engine._conn.execute.return_value.fetchone.return_value = (
        "test@example.com",
        "Test User",
        None,
    )

    resp = client.post(
        "/auth/me/deletion-request",
        headers={"Authorization": "Bearer valid.token.here"},
    )

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error_code"] == "deletion_already_pending"


def test_request_deletion_no_auth(client, mock_engine):
    resp = client.post("/auth/me/deletion-request")
    assert resp.status_code == 401


@patch("engramia.api.cloud_auth._decode_token", return_value=_FAKE_PAYLOAD)
@patch("engramia.api.cloud_auth._has_pending_deletion_request", return_value=False)
@patch("engramia.api.cloud_auth._create_deletion_token", return_value="del-token-abc")
@patch("engramia.api.cloud_auth._send_deletion_email", return_value=False)
@patch("engramia.api.audit.log_db_event")
def test_request_deletion_email_delivery_failed(
    mock_log_db, mock_send, mock_token, mock_pending, mock_decode, client, mock_engine
):
    """SMTP failure surfaces as delivery_status='failed' but the request still 202s.

    The user gets a 'resend' affordance in the dashboard rather than the request
    looking like a hard failure."""
    mock_engine._conn.execute.return_value.fetchone.return_value = (
        "test@example.com",
        "Test User",
        None,
    )

    resp = client.post(
        "/auth/me/deletion-request",
        headers={"Authorization": "Bearer valid.token.here"},
    )

    assert resp.status_code == 202
    assert resp.json()["delivery_status"] == "failed"


# ---------------------------------------------------------------------------
# Self-service account deletion — DELETE /me?token=...
# ---------------------------------------------------------------------------


def _row(*values):
    """Helper: build a sequence-like row that matches both row[i] and unpacking."""
    return tuple(values)


@patch("engramia.governance.deletion.ScopedDeletion")
@patch("engramia.api.deps.get_memory")
@patch("engramia.api.audit.log_db_event")
def test_delete_me_success(mock_log_db, mock_get_memory, mock_scoped_deletion_cls, client, mock_engine):
    # Phase 1 SELECT result: (user_id, expires_at, consumed_at, reason, tenant_id, user_deleted_at)
    import datetime

    from engramia.governance.deletion import DeletionResult

    future = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
    mock_engine._conn.execute.return_value.fetchone.return_value = _row(
        "user-abc", future, None, "leaving", "testuser", None
    )

    # ScopedDeletion result fixture
    fake_result = DeletionResult(
        tenant_id="testuser",
        project_id="*",
        patterns_deleted=42,
        keys_revoked=2,
        cloud_users_deleted=1,
    )
    mock_scoped_deletion = MagicMock()
    mock_scoped_deletion.delete_tenant.return_value = fake_result
    mock_scoped_deletion_cls.return_value = mock_scoped_deletion

    # Stub Memory facade
    mock_get_memory.return_value = MagicMock(storage=MagicMock())

    # BillingService stub on app.state — confirms Stripe path is exercised
    billing = MagicMock()
    billing.cancel_subscription_for_tenant.return_value = True
    client.app.state.billing_service = billing

    resp = client.delete("/auth/me?token=" + "a" * 32)

    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted"] is True
    assert data["tenant_id"] == "testuser"
    assert data["patterns_deleted"] == 42
    assert data["keys_revoked"] == 2
    assert data["stripe_subscription_cancelled"] is True

    billing.cancel_subscription_for_tenant.assert_called_once_with("testuser")
    mock_scoped_deletion.delete_tenant.assert_called_once()
    kwargs = mock_scoped_deletion.delete_tenant.call_args.kwargs
    assert kwargs["tenant_id"] == "testuser"
    assert kwargs["anonymise_users"] is True
    assert kwargs["deletion_reason"] == "leaving"


def test_delete_me_short_token_rejected(client, mock_engine):
    resp = client.delete("/auth/me?token=short")
    assert resp.status_code == 400


def test_delete_me_unknown_token(client, mock_engine):
    mock_engine._conn.execute.return_value.fetchone.return_value = None
    resp = client.delete("/auth/me?token=" + "z" * 32)
    assert resp.status_code == 400


def test_delete_me_token_consumed(client, mock_engine):
    import datetime

    future = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
    consumed = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=5)
    mock_engine._conn.execute.return_value.fetchone.return_value = _row(
        "user-abc", future, consumed, None, "testuser", None
    )
    resp = client.delete("/auth/me?token=" + "a" * 32)
    assert resp.status_code == 410


def test_delete_me_user_already_deleted(client, mock_engine):
    """JWT/token outlived the actual cloud_user row — return 410 idempotently."""
    import datetime

    future = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
    user_deleted = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)
    mock_engine._conn.execute.return_value.fetchone.return_value = _row(
        "user-abc", future, None, None, "testuser", user_deleted
    )
    resp = client.delete("/auth/me?token=" + "a" * 32)
    assert resp.status_code == 410


def test_delete_me_token_expired(client, mock_engine):
    import datetime

    past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    mock_engine._conn.execute.return_value.fetchone.return_value = _row("user-abc", past, None, None, "testuser", None)
    resp = client.delete("/auth/me?token=" + "a" * 32)
    assert resp.status_code == 400


@patch("engramia.governance.deletion.ScopedDeletion")
@patch("engramia.api.deps.get_memory")
@patch("engramia.api.audit.log_db_event")
def test_delete_me_stripe_failure_does_not_block_deletion(
    mock_log_db, mock_get_memory, mock_scoped_deletion_cls, client, mock_engine
):
    """A Stripe API outage must not strand the user with un-deleted data —
    the cascade still runs and the response reports stripe_cancelled=False."""
    import datetime

    from engramia.governance.deletion import DeletionResult

    future = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
    mock_engine._conn.execute.return_value.fetchone.return_value = _row(
        "user-abc", future, None, None, "testuser", None
    )

    fake_result = DeletionResult(tenant_id="testuser", project_id="*")
    mock_scoped_deletion = MagicMock()
    mock_scoped_deletion.delete_tenant.return_value = fake_result
    mock_scoped_deletion_cls.return_value = mock_scoped_deletion
    mock_get_memory.return_value = MagicMock(storage=MagicMock())

    billing = MagicMock()
    billing.cancel_subscription_for_tenant.side_effect = RuntimeError("Stripe API timeout")
    client.app.state.billing_service = billing

    resp = client.delete("/auth/me?token=" + "a" * 32)

    assert resp.status_code == 200
    assert resp.json()["stripe_subscription_cancelled"] is False
    mock_scoped_deletion.delete_tenant.assert_called_once()

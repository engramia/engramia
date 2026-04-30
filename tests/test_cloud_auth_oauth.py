# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""OAuth verification + login tests (Google + Apple).

Coverage gap closed by this file:
  - `_verify_google_token`: tokeninfo HTTP call, audience-claim validation,
    error mapping (HTTPError → 400, generic exception → 400, missing
    ENGRAMIA_GOOGLE_CLIENT_ID → 500).
  - `_verify_apple_token`: not implemented yet, must raise NotImplementedError.
  - `oauth_login` route: first-time-login creates a registration, returning
    user updates last_login_at, audience mismatch from provider → 400,
    missing email from provider → 400, Apple → 501.

All HTTP and DB I/O is mocked — these run without network or a database.
"""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engramia.api.cloud_auth import (
    _verify_apple_token,
    _verify_google_token,
    router,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def _tokeninfo_response(payload: dict) -> MagicMock:
    """Mimic urllib.request.urlopen() context manager returning JSON bytes."""
    body = json.dumps(payload).encode()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=io.BytesIO(body))
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# _verify_google_token (unit)
# ---------------------------------------------------------------------------


class TestVerifyGoogleToken:
    def test_happy_path_returns_email_sub_name(self, monkeypatch):
        monkeypatch.setenv("ENGRAMIA_GOOGLE_CLIENT_ID", "the-client.apps.googleusercontent.com")
        payload = {
            "aud": "the-client.apps.googleusercontent.com",
            "email": "user@gmail.com",
            "sub": "google-12345",
            "name": "Test User",
        }
        with patch("urllib.request.urlopen", return_value=_tokeninfo_response(payload)):
            email, provider_id, name = _verify_google_token("ID_TOKEN_OK")

        assert email == "user@gmail.com"
        assert provider_id == "google-12345"
        assert name == "Test User"

    def test_missing_client_id_env_returns_500(self, monkeypatch):
        """Misconfiguration must surface, not silently accept any audience."""
        monkeypatch.delenv("ENGRAMIA_GOOGLE_CLIENT_ID", raising=False)
        # Stub urlopen so we reach the env-check branch.
        payload = {"aud": "anything", "email": "a@b.cz", "sub": "x"}
        with patch("urllib.request.urlopen", return_value=_tokeninfo_response(payload)):
            with pytest.raises(Exception) as exc_info:
                _verify_google_token("ID_TOKEN")
        assert getattr(exc_info.value, "status_code", None) == 500
        assert "ENGRAMIA_GOOGLE_CLIENT_ID" in str(exc_info.value.detail)

    def test_audience_mismatch_returns_400(self, monkeypatch):
        """Tokens issued for OTHER Google apps must not be accepted."""
        monkeypatch.setenv("ENGRAMIA_GOOGLE_CLIENT_ID", "our-client-id")
        payload = {"aud": "some-other-client", "email": "a@b.cz", "sub": "x"}
        with patch("urllib.request.urlopen", return_value=_tokeninfo_response(payload)):
            with pytest.raises(Exception) as exc_info:
                _verify_google_token("ID_TOKEN")
        assert getattr(exc_info.value, "status_code", None) == 400
        assert "audience mismatch" in str(exc_info.value.detail)

    def test_http_error_from_google_returns_400(self, monkeypatch):
        monkeypatch.setenv("ENGRAMIA_GOOGLE_CLIENT_ID", "our-client")
        err = urllib.error.HTTPError(
            url="https://oauth2.googleapis.com/tokeninfo",
            code=400,
            msg="Bad Request",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(Exception) as exc_info:
                _verify_google_token("ID_TOKEN")
        assert getattr(exc_info.value, "status_code", None) == 400
        assert "Invalid Google token" in str(exc_info.value.detail)

    def test_network_error_returns_400(self, monkeypatch):
        monkeypatch.setenv("ENGRAMIA_GOOGLE_CLIENT_ID", "our-client")
        with patch("urllib.request.urlopen", side_effect=OSError("connection reset")):
            with pytest.raises(Exception) as exc_info:
                _verify_google_token("ID_TOKEN")
        assert getattr(exc_info.value, "status_code", None) == 400
        assert "verification failed" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# _verify_apple_token (stub, not yet implemented)
# ---------------------------------------------------------------------------


class TestVerifyAppleToken:
    def test_raises_not_implemented(self):
        """Until JWKS verification ships, the helper must hard-fail."""
        with pytest.raises(NotImplementedError) as exc_info:
            _verify_apple_token("any-id-token", name=None)
        assert "Apple" in str(exc_info.value)


# ---------------------------------------------------------------------------
# /auth/oauth route — registration / login dispatch
# ---------------------------------------------------------------------------


_FAKE_REG = {
    "user_id": "u-google-1",
    "tenant_id": "t-google-1",
    "project_id": "p-default",
    "api_key": "engramia-" + "a" * 32,
}


@pytest.fixture
def google_verify_ok(monkeypatch):
    """Patch _verify_google_token to return a deterministic identity."""
    fake = MagicMock(return_value=("user@gmail.com", "google-sub-1", "Test User"))
    monkeypatch.setattr("engramia.api.cloud_auth._verify_google_token", fake)
    return fake


class TestOAuthRouteFirstTimeLogin:
    @patch("engramia.api.cloud_auth._make_token", side_effect=["acc.tok", "ref.tok"])
    @patch("engramia.api.cloud_auth._create_registration", return_value=_FAKE_REG)
    @patch("engramia.api.audit.log_event")
    def test_creates_registration_when_email_unknown(
        self,
        _log,
        mock_create,
        _make,
        client,
        mock_engine,
        google_verify_ok,
    ):
        # SELECT returns no row → not found → registration path.
        mock_engine._conn.execute.return_value.fetchone.return_value = None

        resp = client.post(
            "/auth/oauth",
            json={"provider": "google", "provider_token": "ID_TOKEN"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["user_id"] == _FAKE_REG["user_id"]
        assert body["tenant_id"] == _FAKE_REG["tenant_id"]
        assert body["email"] == "user@gmail.com"  # lowercased
        assert body["access_token"] == "acc.tok"
        assert body["refresh_token"] == "ref.tok"
        assert body["api_key"] == _FAKE_REG["api_key"]

        # Registration was called with email_verified=True (provider already verified).
        kwargs = mock_create.call_args.kwargs
        assert kwargs["email_verified"] is True
        assert kwargs["provider"] == "google"
        assert kwargs["provider_id"] == "google-sub-1"
        assert kwargs["password_hash"] is None  # OAuth users have no password

    @patch("engramia.api.cloud_auth._make_token", side_effect=["acc.tok", "ref.tok"])
    def test_returning_user_no_new_registration(
        self,
        _make,
        client,
        mock_engine,
        google_verify_ok,
    ):
        # SELECT returns existing user.
        mock_engine._conn.execute.return_value.fetchone.return_value = (
            "u-existing-1",
            "t-existing-1",
        )

        with patch("engramia.api.cloud_auth._create_registration") as mock_create:
            resp = client.post(
                "/auth/oauth",
                json={"provider": "google", "provider_token": "ID_TOKEN"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["user_id"] == "u-existing-1"
        assert body["tenant_id"] == "t-existing-1"
        assert body["api_key"] == ""  # returning user — no new key issued
        # Crucially: no fresh registration row created.
        mock_create.assert_not_called()

    @patch("engramia.api.cloud_auth._make_token", side_effect=["acc.tok", "ref.tok"])
    def test_returning_user_email_lowercased_before_lookup(
        self, _make, client, mock_engine, monkeypatch
    ):
        """Provider returns mixed-case email; we MUST lowercase before SELECT."""
        monkeypatch.setattr(
            "engramia.api.cloud_auth._verify_google_token",
            MagicMock(return_value=("MiXeD@Gmail.COM", "sub-1", "M")),
        )
        mock_engine._conn.execute.return_value.fetchone.return_value = (
            "u-1",
            "t-1",
        )
        client.post(
            "/auth/oauth",
            json={"provider": "google", "provider_token": "ID_TOKEN"},
        )
        # First execute is the SELECT; check the email param is lowered.
        first_call = mock_engine._conn.execute.call_args_list[0]
        params = first_call.args[1]
        assert params["email"] == "mixed@gmail.com"


class TestOAuthRouteErrors:
    def test_provider_returns_no_email_returns_400(
        self, client, mock_engine, monkeypatch
    ):
        monkeypatch.setattr(
            "engramia.api.cloud_auth._verify_google_token",
            MagicMock(return_value=(None, "google-sub", "Name")),
        )
        resp = client.post(
            "/auth/oauth",
            json={"provider": "google", "provider_token": "ID_TOKEN"},
        )
        assert resp.status_code == 400
        assert "email" in resp.json()["detail"].lower()

    def test_apple_returns_501(self, client):
        resp = client.post(
            "/auth/oauth",
            json={"provider": "apple", "provider_token": "ID_TOKEN", "name": "Tim"},
        )
        assert resp.status_code == 501
        assert "Apple OAuth not yet implemented" in resp.json()["detail"]

    def test_unknown_provider_rejected_by_pydantic(self, client):
        """OAuthRequest is `Literal["google", "apple"]` — anything else 422s."""
        resp = client.post(
            "/auth/oauth",
            json={"provider": "github", "provider_token": "x"},
        )
        assert resp.status_code == 422

    def test_missing_provider_token_rejected_by_pydantic(self, client):
        resp = client.post("/auth/oauth", json={"provider": "google"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /auth/logout — JWT blocklist
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_blocklist():
    """Reset the in-memory blocklist before each test for full isolation."""
    from engramia.api import cloud_auth as ca

    ca._token_blocklist.clear()
    yield
    ca._token_blocklist.clear()


@pytest.fixture
def jwt_env(monkeypatch):
    """Configure a per-test HS256 secret and reset the cached _JWT_CONFIG."""
    monkeypatch.setenv(
        "ENGRAMIA_JWT_SECRET", "test-secret-do-not-use-in-prod-32bytes-min"
    )
    monkeypatch.delenv("ENGRAMIA_JWT_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("ENGRAMIA_JWT_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("ENGRAMIA_ENV", "test")
    from engramia.api import cloud_auth as ca

    ca._JWT_CONFIG = None
    yield
    ca._JWT_CONFIG = None


class TestLogout:
    def test_logout_blocklists_access_token(self, client, jwt_env):
        from engramia.api.cloud_auth import _decode_token, _make_token

        access = _make_token(user_id="u-1", tenant_id="t-1", email="a@b.cz")
        # Pre-condition: token decodes cleanly.
        _decode_token(access)

        resp = client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["message"].startswith("Logged out")

        # Second decode now fails with 401 — Token has been revoked.
        with pytest.raises(Exception) as exc_info:
            _decode_token(access)
        assert getattr(exc_info.value, "status_code", None) == 401
        assert "revoked" in str(exc_info.value.detail).lower()

    def test_logout_optional_refresh_token_also_blocklisted(self, client, jwt_env):
        from engramia.api.cloud_auth import _decode_token, _make_token

        access = _make_token(user_id="u-1", tenant_id="t-1", email="a@b.cz")
        refresh = _make_token(
            user_id="u-1", tenant_id="t-1", email="a@b.cz", is_refresh=True
        )

        client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {access}"},
            json={"refresh_token": refresh},
        )

        with pytest.raises(Exception) as exc_info:
            _decode_token(refresh, require_refresh=True)
        assert getattr(exc_info.value, "status_code", None) == 401
        assert "revoked" in str(exc_info.value.detail).lower()

    def test_logout_without_bearer_returns_401(self, client, jwt_env):
        resp = client.post("/auth/logout")
        assert resp.status_code == 401
        assert "Authorization" in resp.json()["detail"]

    def test_logout_with_malformed_bearer_returns_401(self, client, jwt_env):
        resp = client.post(
            "/auth/logout", headers={"Authorization": "NotBearer xyz"}
        )
        assert resp.status_code == 401

    def test_logout_with_garbage_token_does_not_500(self, client, jwt_env):
        """_blocklist_token swallows malformed tokens — endpoint stays 200."""
        resp = client.post(
            "/auth/logout",
            headers={"Authorization": "Bearer not.a.real.jwt"},
        )
        # The endpoint itself doesn't validate the token — only blocklists it.
        # Garbage tokens are silently dropped (intentional, see _blocklist_token).
        assert resp.status_code == 200

    def test_logout_idempotent_double_call_is_safe(self, client, jwt_env):
        from engramia.api.cloud_auth import _make_token

        access = _make_token(user_id="u-1", tenant_id="t-1", email="a@b.cz")
        for _ in range(2):
            resp = client.post(
                "/auth/logout",
                headers={"Authorization": f"Bearer {access}"},
            )
            assert resp.status_code == 200


class TestBlocklistInternals:
    def test_unknown_jti_is_not_blocked(self, jwt_env):
        from engramia.api.cloud_auth import _is_jti_blocked

        assert _is_jti_blocked("never-seen-this-jti") is False

    def test_blocklisted_jti_returns_true(self, jwt_env):
        from engramia.api.cloud_auth import (
            _blocklist_token,
            _is_jti_blocked,
            _make_token,
        )
        import jwt

        access = _make_token(user_id="u-1", tenant_id="t-1", email="a@b.cz")
        # Decode without verification just to extract the JTI.
        payload = jwt.decode(access, options={"verify_signature": False})
        jti = payload["jti"]

        assert _is_jti_blocked(jti) is False
        _blocklist_token(access)
        assert _is_jti_blocked(jti) is True

    def test_expired_blocklist_entry_is_dropped(self, jwt_env):
        """An entry whose exp has passed must not stay in memory forever."""
        from engramia.api import cloud_auth as ca

        ca._token_blocklist["jti-old"] = 0.0  # already expired
        # _is_jti_blocked treats expired entries as not blocked.
        assert ca._is_jti_blocked("jti-old") is False

    def test_blocklist_handles_garbage_token_silently(self, jwt_env):
        """Tampered or malformed tokens don't raise — they are dropped."""
        from engramia.api.cloud_auth import _blocklist_token

        _blocklist_token("not.a.jwt")  # must not raise

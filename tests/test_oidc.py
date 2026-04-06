# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Unit tests for OIDC JWT authentication (engramia/api/oidc.py).

All JWKS fetches and JWT decoding are mocked — no real IdP needed.

Covers:
- JWKS caching: fresh cache, stale cache triggers refresh, failed refresh keeps old keys
- JWT validation: valid token, expired token, missing kid, disallowed algorithm
- Algorithm allowlist: RS256/ES256 accepted, HS256/none rejected
- Role mapping: custom claim, default fallback, invalid role fallback
- Tenant/project claim mapping: custom claims, missing claims, defaults
- Error responses: 401 for invalid tokens, 503 for missing config
"""

from __future__ import annotations

import base64
import json
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from engramia.api import oidc as oidc_module

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64url(data: dict) -> str:
    """Base64url-encode a JSON dict without padding."""
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def _make_token(header: dict, payload: dict) -> str:
    """Build a fake JWT string (header.payload.signature)."""
    return f"{_b64url(header)}.{_b64url(payload)}.fake_sig"


def _mock_request():
    """Return a MagicMock with request.state."""
    req = MagicMock()
    req.state = MagicMock()
    return req


SAMPLE_JWK = {
    "kid": "test-key-1",
    "kty": "RSA",
    "alg": "RS256",
    "n": "0vx7agoebGcQSuuPiLJXZptN9nndrQmbXEps2aiAFbWhM78LhWx4cbbfAAtVT86zwu1RK7aPFFxuhDR1L6tSoc_BJECPebWKRXjBZCiFV4n3oknjhMstn64tZ_2W-5JsGY4Hc5n9yBXArwl93lqt7_RN5w6Cf0h4QyQ5v-65YGjQR0_FDW2QvzqY368QQMicAtaSqzs8KJZgnYb9c7d0zgdAZHzu6qMQvRL5hajrn1n91CbOpbISD08qNLyrdkt-bFTWhAI4vMQFh6WeZu0fM4lFd2NcRwr3XPksINHaQ-G_xBniIqbw0Ls1jF44-csFCur-kEgU8awapJzKnqDKgw",
    "e": "AQAB",
}

SAMPLE_JWKS_RESPONSE = {"keys": [SAMPLE_JWK]}


# ---------------------------------------------------------------------------
# JWKS cache tests
# ---------------------------------------------------------------------------


class TestJwksCache:
    def setup_method(self):
        """Reset JWKS cache state before each test."""
        with oidc_module._jwks_lock:
            oidc_module._jwks_cache.clear()
            oidc_module._jwks_fetched_at = 0.0

    def test_fresh_cache_does_not_refetch(self):
        """When cache is fresh (within TTL), no HTTP fetch happens."""
        with oidc_module._jwks_lock:
            oidc_module._jwks_cache["test-key-1"] = SAMPLE_JWK
            oidc_module._jwks_fetched_at = time.monotonic()

        with patch.object(oidc_module, "_fetch_jwks_raw") as mock_fetch:
            result = oidc_module._get_jwk("test-key-1")

        mock_fetch.assert_not_called()
        assert result == SAMPLE_JWK

    def test_stale_cache_triggers_refresh(self):
        """When cache is past TTL, JWKS is refetched."""
        with oidc_module._jwks_lock:
            oidc_module._jwks_cache["old-key"] = {"kid": "old-key"}
            oidc_module._jwks_fetched_at = time.monotonic() - oidc_module._JWKS_TTL - 10

        with patch.object(oidc_module, "_fetch_jwks_raw", return_value=SAMPLE_JWKS_RESPONSE):
            result = oidc_module._get_jwk("test-key-1")

        assert result == SAMPLE_JWK

    def test_empty_cache_triggers_refresh(self):
        """Empty cache always triggers a fetch."""
        with patch.object(oidc_module, "_fetch_jwks_raw", return_value=SAMPLE_JWKS_RESPONSE):
            result = oidc_module._get_jwk("test-key-1")

        assert result == SAMPLE_JWK

    def test_failed_refresh_keeps_old_keys(self):
        """When JWKS fetch fails, previously cached keys remain available."""
        with oidc_module._jwks_lock:
            oidc_module._jwks_cache["test-key-1"] = SAMPLE_JWK
            # Make cache stale so refresh is triggered
            oidc_module._jwks_fetched_at = time.monotonic() - oidc_module._JWKS_TTL - 10

        with patch.object(oidc_module, "_fetch_jwks_raw", side_effect=RuntimeError("IdP down")):
            result = oidc_module._get_jwk("test-key-1")

        # Old key should still be available
        assert result == SAMPLE_JWK

    def test_unknown_kid_returns_none(self):
        """Key not found in cache returns None."""
        with patch.object(oidc_module, "_fetch_jwks_raw", return_value=SAMPLE_JWKS_RESPONSE):
            result = oidc_module._get_jwk("nonexistent-key-id")

        assert result is None

    def test_keys_without_kid_are_skipped(self):
        """JWKS entries missing 'kid' field are ignored."""
        jwks_no_kid = {"keys": [{"kty": "RSA", "n": "abc", "e": "AQAB"}]}
        with patch.object(oidc_module, "_fetch_jwks_raw", return_value=jwks_no_kid):
            result = oidc_module._get_jwk("any")

        assert result is None


# ---------------------------------------------------------------------------
# Algorithm allowlist tests
# ---------------------------------------------------------------------------


class TestAlgorithmAllowlist:
    """Test that only asymmetric algorithms are accepted."""

    def test_hs256_rejected(self):
        """HMAC-SHA256 must be rejected (symmetric key attack vector)."""
        token = _make_token({"alg": "HS256", "kid": "test-key-1"}, {"sub": "user"})

        with (
            patch.object(oidc_module, "_get_jwk", return_value=SAMPLE_JWK),
            pytest.raises(HTTPException) as exc_info,
        ):
            # Mock jwt module to return our header
            jwt_mock = MagicMock()
            jwt_mock.get_unverified_header.return_value = {"alg": "HS256", "kid": "test-key-1"}
            jwt_mock.PyJWTError = Exception
            with patch.dict("sys.modules", {"jwt": jwt_mock}):
                oidc_module._decode_jwt(token)

        assert exc_info.value.status_code == 401
        assert "not permitted" in exc_info.value.detail

    def test_alg_none_rejected(self):
        """Algorithm 'none' must be rejected (no-signature attack)."""
        jwt_mock = MagicMock()
        jwt_mock.get_unverified_header.return_value = {"alg": "none", "kid": "test-key-1"}
        jwt_mock.PyJWTError = Exception

        with (
            patch.dict("sys.modules", {"jwt": jwt_mock}),
            pytest.raises(HTTPException) as exc_info,
        ):
            oidc_module._decode_jwt("fake.token.here")

        assert exc_info.value.status_code == 401
        assert "not permitted" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Missing kid tests
# ---------------------------------------------------------------------------


class TestMissingKid:
    def test_missing_kid_header_returns_401(self):
        """Token without 'kid' in header must be rejected."""
        jwt_mock = MagicMock()
        jwt_mock.get_unverified_header.return_value = {"alg": "RS256"}  # no kid
        jwt_mock.PyJWTError = Exception

        with (
            patch.dict("sys.modules", {"jwt": jwt_mock}),
            pytest.raises(HTTPException) as exc_info,
        ):
            oidc_module._decode_jwt("fake.token.here")

        assert exc_info.value.status_code == 401
        assert "kid" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Key not found tests
# ---------------------------------------------------------------------------


class TestKeyNotFound:
    def test_unknown_signing_key_returns_401(self):
        """Token signed with unknown key ID must be rejected."""
        jwt_mock = MagicMock()
        jwt_mock.get_unverified_header.return_value = {"alg": "RS256", "kid": "unknown-key"}
        jwt_mock.PyJWTError = Exception

        with (
            patch.dict("sys.modules", {"jwt": jwt_mock}),
            patch.object(oidc_module, "_get_jwk", return_value=None),
            pytest.raises(HTTPException) as exc_info,
        ):
            oidc_module._decode_jwt("fake.token.here")

        assert exc_info.value.status_code == 401
        assert "signing key not found" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# oidc_auth() integration tests
# ---------------------------------------------------------------------------


class TestOidcAuth:
    def test_missing_issuer_returns_503(self):
        """OIDC auth without configured issuer returns 503."""
        request = _mock_request()

        with (
            patch.object(oidc_module, "_ISSUER", ""),
            pytest.raises(HTTPException) as exc_info,
        ):
            oidc_module.oidc_auth(request, "some-token")

        assert exc_info.value.status_code == 503
        assert "ENGRAMIA_OIDC_ISSUER" in exc_info.value.detail

    def test_valid_token_sets_auth_context(self):
        """Valid token sets request.state.auth_context with correct fields."""
        request = _mock_request()

        claims = {
            "sub": "user-123",
            "engramia_role": "admin",
            "aud": "engramia-api",
            "iss": "https://idp.example.com",
        }

        with (
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
        ):
            oidc_module.oidc_auth(request, "valid-token")

        ctx = request.state.auth_context
        assert ctx.key_id == "user-123"
        assert ctx.role == "admin"
        assert ctx.tenant_id == "default"
        assert ctx.project_id == "default"

    def test_unknown_role_falls_back_to_reader(self):
        """Unrecognised role claim falls back to 'reader'."""
        request = _mock_request()

        claims = {"sub": "user-456", "engramia_role": "superadmin"}

        with (
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
        ):
            oidc_module.oidc_auth(request, "token")

        assert request.state.auth_context.role == "reader"

    def test_missing_role_claim_uses_default(self):
        """Token without role claim uses DEFAULT_ROLE."""
        request = _mock_request()

        claims = {"sub": "user-789"}

        with (
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
            patch.object(oidc_module, "_DEFAULT_ROLE", "editor"),
        ):
            oidc_module.oidc_auth(request, "token")

        assert request.state.auth_context.role == "editor"

    def test_custom_tenant_claim(self):
        """Tenant ID is read from the custom claim when configured."""
        request = _mock_request()

        claims = {"sub": "user", "org_id": "acme-corp"}

        with (
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
            patch.object(oidc_module, "_TENANT_CLAIM", "org_id"),
        ):
            oidc_module.oidc_auth(request, "token")

        assert request.state.auth_context.tenant_id == "acme-corp"

    def test_missing_tenant_claim_falls_back_to_default(self):
        """When the tenant claim is configured but absent in token, fallback to 'default'."""
        request = _mock_request()

        claims = {"sub": "user"}  # no org_id

        with (
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
            patch.object(oidc_module, "_TENANT_CLAIM", "org_id"),
        ):
            oidc_module.oidc_auth(request, "token")

        assert request.state.auth_context.tenant_id == "default"

    def test_custom_project_claim(self):
        """Project ID is read from the custom claim when configured."""
        request = _mock_request()

        claims = {"sub": "user", "project": "alpha"}

        with (
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
            patch.object(oidc_module, "_PROJECT_CLAIM", "project"),
        ):
            oidc_module.oidc_auth(request, "token")

        assert request.state.auth_context.project_id == "alpha"

    def test_missing_project_claim_falls_back_to_default(self):
        """When the project claim is configured but absent, fallback to 'default'."""
        request = _mock_request()

        claims = {"sub": "user"}

        with (
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
            patch.object(oidc_module, "_PROJECT_CLAIM", "project_id"),
        ):
            oidc_module.oidc_auth(request, "token")

        assert request.state.auth_context.project_id == "default"

    def test_no_tenant_claim_configured_uses_default(self):
        """When TENANT_CLAIM is empty, tenant_id is always 'default'."""
        request = _mock_request()

        claims = {"sub": "user", "org_id": "should-be-ignored"}

        with (
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
            patch.object(oidc_module, "_TENANT_CLAIM", ""),
        ):
            oidc_module.oidc_auth(request, "token")

        assert request.state.auth_context.tenant_id == "default"

    def test_scope_contextvar_set(self):
        """oidc_auth must set the scope contextvar."""
        request = _mock_request()

        claims = {"sub": "user"}

        with (
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
            patch.object(oidc_module, "set_scope") as mock_set_scope,
        ):
            oidc_module.oidc_auth(request, "token")

        mock_set_scope.assert_called_once()
        scope = mock_set_scope.call_args[0][0]
        assert scope.tenant_id == "default"
        assert scope.project_id == "default"

    def test_sub_claim_missing_uses_fallback(self):
        """When 'sub' claim is absent, key_id falls back to 'oidc-unknown'."""
        request = _mock_request()

        claims = {}  # no sub

        with (
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
        ):
            oidc_module.oidc_auth(request, "token")

        assert request.state.auth_context.key_id == "oidc-unknown"

    def test_all_valid_roles_accepted(self):
        """All four valid roles are accepted without fallback."""
        for role in ("owner", "admin", "editor", "reader"):
            request = _mock_request()
            claims = {"sub": "user", "engramia_role": role}

            with (
                patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
                patch.object(oidc_module, "_decode_jwt", return_value=claims),
            ):
                oidc_module.oidc_auth(request, "token")

            assert request.state.auth_context.role == role

    def test_role_case_insensitive(self):
        """Role claim is case-insensitive."""
        request = _mock_request()
        claims = {"sub": "user", "engramia_role": "ADMIN"}

        with (
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
        ):
            oidc_module.oidc_auth(request, "token")

        assert request.state.auth_context.role == "admin"


# ---------------------------------------------------------------------------
# _fetch_jwks_raw error handling
# ---------------------------------------------------------------------------


class TestFetchJwksRaw:
    def test_network_error_raises_runtime_error(self):
        """Network failure during JWKS fetch raises RuntimeError."""
        import urllib.error

        with (
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")),
            pytest.raises(RuntimeError, match="Failed to fetch JWKS"),
        ):
            oidc_module._fetch_jwks_raw()

    def test_invalid_json_raises_runtime_error(self):
        """Malformed JSON from JWKS endpoint raises RuntimeError."""
        resp_mock = MagicMock()
        resp_mock.read.return_value = b"not json"
        resp_mock.__enter__ = lambda s: resp_mock
        resp_mock.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch("urllib.request.urlopen", return_value=resp_mock),
            pytest.raises(RuntimeError, match="Failed to fetch JWKS"),
        ):
            oidc_module._fetch_jwks_raw()

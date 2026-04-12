# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for OIDC JWT authentication (engramia/api/oidc.py).

Two test layers:
1. Unit tests — mock _decode_jwt to verify AuthContext + Scope construction
   and error propagation, with no network calls or crypto deps.
2. Integration tests (marked ``oidc_crypto``) — generate a real RSA key pair,
   sign JWTs with it, inject the public key into the JWKS cache, and exercise
   the full validation path.  Requires ``pyjwt[crypto]`` + ``cryptography``.
   Run with:  pytest -m oidc_crypto
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import engramia.api.oidc as oidc_module
from engramia.api.oidc import oidc_auth
from engramia.types import Scope

pytestmark = pytest.mark.security


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_request() -> MagicMock:
    """Return a minimal mock Request with a writable state."""
    req = MagicMock()
    req.state = MagicMock()
    return req


def _claims(**overrides: Any) -> dict:
    """Return a minimal valid JWT claims dict with optional overrides."""
    base = {
        "sub": "user-abc",
        "engramia_role": "editor",
        "iss": "https://idp.example.com",
        "aud": "engramia-api",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Unit tests — _decode_jwt is mocked
# ---------------------------------------------------------------------------


class TestOidcAuthUnit:
    """Test oidc_auth() behaviour by mocking _decode_jwt."""

    def test_valid_claims_sets_auth_context(self):
        """Valid JWT → AuthContext with correct role, tenant, project on request.state."""
        req = _mock_request()
        claims = _claims(engramia_tenant="default")

        with (
            patch.dict(
                os.environ,
                {"ENGRAMIA_OIDC_ISSUER": "https://idp.example.com", "ENGRAMIA_OIDC_TENANT_CLAIM": "engramia_tenant"},
            ),
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_TENANT_CLAIM", "engramia_tenant"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
            patch.object(oidc_module, "set_scope") as mock_set_scope,
        ):
            oidc_auth(req, "fake.jwt.token")

        ctx = req.state.auth_context
        assert ctx.role == "editor"
        assert ctx.tenant_id == "default"
        assert ctx.project_id == "default"
        assert ctx.key_id == "user-abc"
        assert ctx.max_patterns is None
        mock_set_scope.assert_called_once_with(Scope(tenant_id="default", project_id="default"))

    def test_custom_tenant_and_project_claims(self):
        """JWT with tenant/project claims maps them into the scope."""
        req = _mock_request()
        claims = _claims(org="acme", proj="api-v2")

        with (
            patch.dict(
                os.environ,
                {
                    "ENGRAMIA_OIDC_ISSUER": "https://idp.example.com",
                    "ENGRAMIA_OIDC_TENANT_CLAIM": "org",
                    "ENGRAMIA_OIDC_PROJECT_CLAIM": "proj",
                },
            ),
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_TENANT_CLAIM", "org"),
            patch.object(oidc_module, "_PROJECT_CLAIM", "proj"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
            patch.object(oidc_module, "set_scope"),
        ):
            oidc_auth(req, "fake.jwt.token")

        ctx = req.state.auth_context
        assert ctx.tenant_id == "acme"
        assert ctx.project_id == "api-v2"

    def test_unknown_role_falls_back_to_reader(self):
        """JWT role claim value not in VALID_ROLES → falls back to 'reader'."""
        req = _mock_request()
        claims = _claims(engramia_role="superuser", engramia_tenant="default")

        with (
            patch.dict(
                os.environ,
                {"ENGRAMIA_OIDC_ISSUER": "https://idp.example.com", "ENGRAMIA_OIDC_TENANT_CLAIM": "engramia_tenant"},
            ),
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_TENANT_CLAIM", "engramia_tenant"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
            patch.object(oidc_module, "set_scope"),
        ):
            oidc_auth(req, "fake.jwt.token")

        assert req.state.auth_context.role == "reader"

    def test_missing_role_claim_uses_default(self):
        """No role claim in JWT → uses ENGRAMIA_OIDC_DEFAULT_ROLE (default 'reader')."""
        req = _mock_request()
        # claims without the role claim key at all
        claims = {k: v for k, v in _claims().items() if k != "engramia_role"}
        claims["engramia_tenant"] = "default"

        with (
            patch.dict(
                os.environ,
                {"ENGRAMIA_OIDC_ISSUER": "https://idp.example.com", "ENGRAMIA_OIDC_TENANT_CLAIM": "engramia_tenant"},
            ),
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_TENANT_CLAIM", "engramia_tenant"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
            patch.object(oidc_module, "set_scope"),
        ):
            oidc_auth(req, "fake.jwt.token")

        assert req.state.auth_context.role == "reader"

    def test_custom_default_role_env_var(self):
        """ENGRAMIA_OIDC_DEFAULT_ROLE is honoured when role claim is absent."""
        req = _mock_request()
        claims = {k: v for k, v in _claims().items() if k != "engramia_role"}
        claims["engramia_tenant"] = "default"

        with (
            patch.dict(
                os.environ,
                {
                    "ENGRAMIA_OIDC_ISSUER": "https://idp.example.com",
                    "ENGRAMIA_OIDC_DEFAULT_ROLE": "admin",
                    "ENGRAMIA_OIDC_TENANT_CLAIM": "engramia_tenant",
                },
            ),
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_TENANT_CLAIM", "engramia_tenant"),
            patch.object(oidc_module, "_DEFAULT_ROLE", "admin"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
            patch.object(oidc_module, "set_scope"),
        ):
            oidc_auth(req, "fake.jwt.token")

        assert req.state.auth_context.role == "admin"

    def test_issuer_not_configured_raises_503(self):
        """Missing ENGRAMIA_OIDC_ISSUER → 503 Service Unavailable."""
        req = _mock_request()

        env = {k: v for k, v in os.environ.items() if k != "ENGRAMIA_OIDC_ISSUER"}
        with patch.dict(os.environ, env, clear=True):
            # Also reset the module-level _ISSUER that was read at import time.
            with patch.object(oidc_module, "_ISSUER", ""):
                with pytest.raises(HTTPException) as exc_info:
                    oidc_auth(req, "fake.jwt.token")

        assert exc_info.value.status_code == 503

    def test_decode_jwt_raises_401_propagates(self):
        """An HTTPException(401) from _decode_jwt propagates unchanged."""
        req = _mock_request()

        with (
            patch.dict(
                os.environ,
                {"ENGRAMIA_OIDC_ISSUER": "https://idp.example.com", "ENGRAMIA_OIDC_TENANT_CLAIM": "engramia_tenant"},
            ),
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_TENANT_CLAIM", "engramia_tenant"),
            patch.object(
                oidc_module, "_decode_jwt", side_effect=HTTPException(status_code=401, detail="Token expired.")
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                oidc_auth(req, "expired.jwt.token")

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Token expired."


# ---------------------------------------------------------------------------
# Unit tests — _decode_jwt internals (no crypto)
# ---------------------------------------------------------------------------


class TestDecodeJwtUnit:
    """Test _decode_jwt error paths by mocking at the jwt library level."""

    def test_missing_kid_raises_401(self):
        """JWT header without 'kid' → 401."""
        import engramia.api.oidc as m

        fake_jwt = MagicMock()
        fake_jwt.get_unverified_header.return_value = {"alg": "RS256"}  # no 'kid'

        with (
            patch.dict(os.environ, {"ENGRAMIA_OIDC_ISSUER": "https://idp.example.com"}),
            patch.object(m, "_ISSUER", "https://idp.example.com"),
            patch.dict("sys.modules", {"jwt": fake_jwt, "jwt.algorithms": MagicMock()}),
        ):
            with pytest.raises(HTTPException) as exc_info:
                m._decode_jwt("any.token")

        assert exc_info.value.status_code == 401
        assert "kid" in exc_info.value.detail

    def test_pyjwt_not_installed_raises_runtime_error(self):
        """ImportError for pyjwt → RuntimeError with install hint."""
        import builtins

        real_import = builtins.__import__

        def _block_jwt(name, *args, **kwargs):
            if name == "jwt":
                raise ImportError("No module named 'jwt'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_block_jwt):
            with pytest.raises(RuntimeError, match="engramia\\[oidc\\]"):
                oidc_module._decode_jwt("any.token")


# ---------------------------------------------------------------------------
# Integration tests — real RSA JWT (requires pyjwt[crypto] + cryptography)
# ---------------------------------------------------------------------------

pytestmark_oidc = pytest.mark.oidc_crypto


@pytest.fixture(scope="module")
def rsa_key_pair():
    """Generate a one-time RSA key pair for OIDC integration tests."""
    cryptography = pytest.importorskip("cryptography", reason="cryptography not installed")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _sign_jwt(private_pem: bytes, claims: dict, kid: str = "test-key-1") -> str:
    """Sign a JWT with the given RSA private key."""
    jwt = pytest.importorskip("jwt")
    return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": kid})


def _jwk_from_public_pem(public_pem: bytes, kid: str = "test-key-1") -> dict:
    """Build a minimal JWK dict from a PEM public key (for cache injection)."""
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    import base64, struct

    pub = load_pem_public_key(public_pem)
    pub_numbers = pub.public_key().public_numbers() if hasattr(pub, "public_key") else pub.public_numbers()

    def _b64url(n: int) -> str:
        byte_length = (n.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(n.to_bytes(byte_length, "big")).rstrip(b"=").decode()

    return {
        "kty": "RSA",
        "kid": kid,
        "alg": "RS256",
        "use": "sig",
        "n": _b64url(pub_numbers.n),
        "e": _b64url(pub_numbers.e),
    }


@pytest.mark.oidc_crypto
def test_valid_signed_jwt_accepted(rsa_key_pair):
    """A JWT signed with a known RSA key is accepted and AuthContext is set."""
    import time

    jwt = pytest.importorskip("jwt")

    private_pem, public_pem = rsa_key_pair
    kid = "test-key-1"
    issuer = "https://idp.example.com"
    audience = "engramia-api"

    claims = {
        "sub": "user-xyz",
        "engramia_role": "admin",
        "engramia_tenant": "default",
        "iss": issuer,
        "aud": audience,
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    token = _sign_jwt(private_pem, claims, kid=kid)
    jwk = _jwk_from_public_pem(public_pem, kid=kid)

    req = _mock_request()

    with (
        patch.dict(
            os.environ,
            {"ENGRAMIA_OIDC_ISSUER": issuer, "ENGRAMIA_OIDC_AUDIENCE": audience},
        ),
        patch.object(oidc_module, "_ISSUER", issuer),
        patch.object(oidc_module, "_AUDIENCE", audience),
        patch.object(oidc_module, "_TENANT_CLAIM", "engramia_tenant"),
        patch.object(oidc_module, "_jwks_cache", {kid: jwk}),
        patch.object(oidc_module, "_jwks_fetched_at", float("inf")),  # cache is fresh
        patch.object(oidc_module, "set_scope"),
    ):
        oidc_auth(req, token)

    ctx = req.state.auth_context
    assert ctx.role == "admin"
    assert ctx.key_id == "user-xyz"


@pytest.mark.oidc_crypto
def test_expired_jwt_raises_401(rsa_key_pair):
    """An expired JWT is rejected with 401."""
    import time

    jwt = pytest.importorskip("jwt")

    private_pem, public_pem = rsa_key_pair
    kid = "test-key-1"
    issuer = "https://idp.example.com"
    audience = "engramia-api"

    claims = {
        "sub": "user-xyz",
        "iss": issuer,
        "aud": audience,
        "exp": int(time.time()) - 10,  # already expired
        "iat": int(time.time()) - 70,
    }
    token = _sign_jwt(private_pem, claims, kid=kid)
    jwk = _jwk_from_public_pem(public_pem, kid=kid)

    req = _mock_request()

    with (
        patch.dict(
            os.environ,
            {"ENGRAMIA_OIDC_ISSUER": issuer, "ENGRAMIA_OIDC_AUDIENCE": audience},
        ),
        patch.object(oidc_module, "_ISSUER", issuer),
        patch.object(oidc_module, "_AUDIENCE", audience),
        patch.object(oidc_module, "_TENANT_CLAIM", "engramia_tenant"),
        patch.object(oidc_module, "_jwks_cache", {kid: jwk}),
        patch.object(oidc_module, "_jwks_fetched_at", float("inf")),
        patch.object(oidc_module, "set_scope"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            oidc_auth(req, token)

    assert exc_info.value.status_code == 401


@pytest.mark.oidc_crypto
def test_unknown_kid_raises_401(rsa_key_pair):
    """JWT signed with a key whose kid is not in the JWKS cache → 401."""
    import time

    jwt = pytest.importorskip("jwt")

    private_pem, _ = rsa_key_pair
    issuer = "https://idp.example.com"
    audience = "engramia-api"

    claims = {
        "sub": "user-xyz",
        "iss": issuer,
        "aud": audience,
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    token = _sign_jwt(private_pem, claims, kid="unknown-key")

    req = _mock_request()

    with (
        patch.dict(
            os.environ,
            {"ENGRAMIA_OIDC_ISSUER": issuer, "ENGRAMIA_OIDC_AUDIENCE": audience},
        ),
        patch.object(oidc_module, "_ISSUER", issuer),
        patch.object(oidc_module, "_AUDIENCE", audience),
        patch.object(oidc_module, "_TENANT_CLAIM", "engramia_tenant"),
        patch.object(oidc_module, "_jwks_cache", {}),  # empty cache
        patch.object(oidc_module, "_jwks_fetched_at", float("inf")),
        patch.object(oidc_module, "set_scope"),
        patch.object(oidc_module, "_fetch_jwks_raw", side_effect=RuntimeError("network")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            oidc_auth(req, token)

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Additional unit tests for uncovered code paths (#6 coverage)
# ---------------------------------------------------------------------------


class TestJwksHelpers:
    """Tests for _jwks_url, _fetch_jwks_raw, _refresh_jwks, _get_jwk."""

    def test_jwks_url_includes_issuer(self):
        with patch.object(oidc_module, "_ISSUER", "https://idp.example.com"):
            url = oidc_module._jwks_url()
        assert url == "https://idp.example.com/.well-known/jwks.json"

    def test_fetch_jwks_raw_network_error_raises_runtime(self):
        import urllib.error

        with (
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")),
        ):
            with pytest.raises(RuntimeError, match="Failed to fetch JWKS"):
                oidc_module._fetch_jwks_raw()

    def test_refresh_jwks_populates_cache(self):
        jwks_data = {"keys": [{"kid": "k1", "kty": "RSA", "use": "sig"}]}
        with (
            patch.object(oidc_module, "_fetch_jwks_raw", return_value=jwks_data),
            patch.object(oidc_module, "_jwks_cache", {}),
            patch.object(oidc_module, "_jwks_fetched_at", 0.0),
        ):
            oidc_module._refresh_jwks()
            assert "k1" in oidc_module._jwks_cache

    def test_refresh_jwks_skips_when_fresh(self):
        import time

        with (
            patch.object(oidc_module, "_fetch_jwks_raw") as mock_fetch,
            patch.object(oidc_module, "_jwks_cache", {"k1": {}}),
            patch.object(oidc_module, "_jwks_fetched_at", time.monotonic()),
        ):
            oidc_module._refresh_jwks()
        mock_fetch.assert_not_called()

    def test_refresh_jwks_network_failure_keeps_old_cache(self):
        with (
            patch.object(oidc_module, "_fetch_jwks_raw", side_effect=RuntimeError("network error")),
            patch.object(oidc_module, "_jwks_fetched_at", 0.0),
            patch.object(oidc_module, "_jwks_cache", {"old-key": {"kid": "old-key"}}),
        ):
            # Should not raise; old cache survives
            oidc_module._refresh_jwks()

    def test_get_jwk_returns_key_after_refresh(self):
        jwks_data = {"keys": [{"kid": "my-key", "kty": "RSA"}]}
        with (
            patch.object(oidc_module, "_fetch_jwks_raw", return_value=jwks_data),
            patch.object(oidc_module, "_jwks_cache", {}),
            patch.object(oidc_module, "_jwks_fetched_at", 0.0),
        ):
            result = oidc_module._get_jwk("my-key")
            assert result["kid"] == "my-key"

    def test_get_jwk_returns_none_for_unknown_kid(self):
        with (
            patch.object(oidc_module, "_fetch_jwks_raw", return_value={"keys": []}),
            patch.object(oidc_module, "_jwks_cache", {}),
            patch.object(oidc_module, "_jwks_fetched_at", 0.0),
        ):
            result = oidc_module._get_jwk("nonexistent")
            assert result is None


class TestDecodeJwtAlgorithmAllowlist:
    """Test the algorithm allowlist in _decode_jwt."""

    def test_hmac_algorithm_rejected(self):
        """HS256 must be rejected (HMAC attack using public key as secret)."""
        fake_jwt = MagicMock()
        fake_jwt.get_unverified_header.return_value = {"kid": "k1", "alg": "HS256"}
        fake_jwt.PyJWTError = Exception

        with patch.dict("sys.modules", {"jwt": fake_jwt, "jwt.algorithms": MagicMock()}):
            with pytest.raises(HTTPException) as exc_info:
                oidc_module._decode_jwt("some.jwt.token")
        assert exc_info.value.status_code == 401
        assert "HS256" in exc_info.value.detail

    def test_rs256_algorithm_missing_key_raises_401(self):
        """RS256 is accepted; missing key → 401 signing key not found."""
        fake_jwt = MagicMock()
        fake_jwt.get_unverified_header.return_value = {"kid": "k1", "alg": "RS256"}
        fake_jwt.PyJWTError = Exception
        fake_alg_module = MagicMock()
        fake_alg_module.get_default_algorithms.return_value = {"RS256": MagicMock()}

        with (
            patch.dict("sys.modules", {"jwt": fake_jwt, "jwt.algorithms": fake_alg_module}),
            patch.object(oidc_module, "_get_jwk", return_value=None),
        ):
            with pytest.raises(HTTPException) as exc_info:
                oidc_module._decode_jwt("rs256.token")
        assert exc_info.value.status_code == 401
        assert "signing key" in exc_info.value.detail.lower()

    def test_malformed_jwt_header_raises_401(self):
        """A JWT that raises PyJWTError during header parse -> 401."""
        fake_jwt = MagicMock()
        fake_jwt.PyJWTError = ValueError
        fake_jwt.get_unverified_header.side_effect = ValueError("malformed")

        with patch.dict("sys.modules", {"jwt": fake_jwt, "jwt.algorithms": MagicMock()}):
            with pytest.raises(HTTPException) as exc_info:
                oidc_module._decode_jwt("bad.token")
        assert exc_info.value.status_code == 401


class TestOidcAuthTenantProjectClaims:
    """Test oidc_auth() with tenant/project claims present but missing from token."""

    def test_missing_tenant_claim_falls_back_to_default(self):
        """When tenant claim is configured but missing from token, raises 401."""
        req = _mock_request()
        claims = _claims()  # no 'org' claim
        with (
            patch.dict(
                os.environ, {"ENGRAMIA_OIDC_ISSUER": "https://idp.example.com", "ENGRAMIA_OIDC_TENANT_CLAIM": "org"}
            ),
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_TENANT_CLAIM", "org"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
            patch.object(oidc_module, "set_scope"),
            pytest.raises(HTTPException) as exc_info,
        ):
            oidc_auth(req, "token")
        assert exc_info.value.status_code == 401
        assert "org" in exc_info.value.detail

    def test_missing_project_claim_falls_back_to_default(self):
        req = _mock_request()
        claims = _claims(org="acme")  # has tenant claim, no project claim
        with (
            patch.dict(
                os.environ, {"ENGRAMIA_OIDC_ISSUER": "https://idp.example.com", "ENGRAMIA_OIDC_TENANT_CLAIM": "org"}
            ),
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_TENANT_CLAIM", "org"),
            patch.object(oidc_module, "_PROJECT_CLAIM", "proj"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
            patch.object(oidc_module, "set_scope"),
        ):
            oidc_auth(req, "token")
        assert req.state.auth_context.project_id == "default"

    def test_tenant_claim_set_when_present(self):
        req = _mock_request()
        claims = _claims(org="acme-corp")
        with (
            patch.dict(os.environ, {"ENGRAMIA_OIDC_ISSUER": "https://idp.example.com"}),
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_TENANT_CLAIM", "org"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
            patch.object(oidc_module, "set_scope"),
        ):
            oidc_auth(req, "token")
        assert req.state.auth_context.tenant_id == "acme-corp"

    def test_project_claim_set_when_present(self):
        req = _mock_request()
        claims = _claims(proj="backend", org="acme")  # has both tenant and project claims
        with (
            patch.dict(
                os.environ, {"ENGRAMIA_OIDC_ISSUER": "https://idp.example.com", "ENGRAMIA_OIDC_TENANT_CLAIM": "org"}
            ),
            patch.object(oidc_module, "_ISSUER", "https://idp.example.com"),
            patch.object(oidc_module, "_TENANT_CLAIM", "org"),
            patch.object(oidc_module, "_PROJECT_CLAIM", "proj"),
            patch.object(oidc_module, "_decode_jwt", return_value=claims),
            patch.object(oidc_module, "set_scope"),
        ):
            oidc_auth(req, "token")
        assert req.state.auth_context.project_id == "backend"

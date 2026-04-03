# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""OIDC JWT authentication for the Engramia API (enterprise optional auth mode).

Validates Bearer tokens issued by any standards-compliant OIDC provider
(Okta, Auth0, Azure AD, Google, Keycloak, ...).

Configuration (env vars):
    ENGRAMIA_OIDC_ISSUER        Required. Token issuer URL, e.g.
                                 ``https://company.okta.com/oauth2/default``.
    ENGRAMIA_OIDC_AUDIENCE      Required. Expected ``aud`` claim in the token.
    ENGRAMIA_OIDC_ROLE_CLAIM    JWT claim that maps to an Engramia role.
                                 Default: ``engramia_role``.
    ENGRAMIA_OIDC_DEFAULT_ROLE  Fallback role when the claim is absent.
                                 Default: ``reader``.
    ENGRAMIA_OIDC_TENANT_CLAIM  JWT claim for tenant_id. Default: use ``default``.
    ENGRAMIA_OIDC_PROJECT_CLAIM JWT claim for project_id. Default: use ``default``.

JWKS keys are fetched once from ``{issuer}/.well-known/jwks.json`` and cached
for 1 hour. A failed refresh keeps the previous keys until the next successful
fetch so a transient IdP outage does not lock out active sessions.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import urllib.error
import urllib.request
from json import JSONDecodeError
from typing import Any

from fastapi import HTTPException, Request, status

from engramia._context import set_scope
from engramia.types import AuthContext, Scope

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ISSUER = os.environ.get("ENGRAMIA_OIDC_ISSUER", "").rstrip("/")
_AUDIENCE = os.environ.get("ENGRAMIA_OIDC_AUDIENCE", "")
_ROLE_CLAIM = os.environ.get("ENGRAMIA_OIDC_ROLE_CLAIM", "engramia_role")
_DEFAULT_ROLE = os.environ.get("ENGRAMIA_OIDC_DEFAULT_ROLE", "reader")
_TENANT_CLAIM = os.environ.get("ENGRAMIA_OIDC_TENANT_CLAIM", "")
_PROJECT_CLAIM = os.environ.get("ENGRAMIA_OIDC_PROJECT_CLAIM", "")

_VALID_ROLES = {"owner", "admin", "editor", "reader"}

# ---------------------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------------------

_jwks_lock = threading.Lock()
_jwks_cache: dict[str, Any] = {}  # kid → key data
_jwks_fetched_at: float = 0.0
_JWKS_TTL = 3600.0  # 1 hour


def _jwks_url() -> str:
    return f"{_ISSUER}/.well-known/jwks.json"


def _fetch_jwks_raw() -> dict:
    """Fetch JWKS from the IdP. Raises on network/parse error."""
    url = _jwks_url()
    req = urllib.request.Request(url, headers={"User-Agent": "engramia-oidc/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            import json

            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Failed to fetch JWKS from {url}: {exc}") from exc
    return data


def _refresh_jwks() -> None:
    """Refresh the in-memory JWKS cache (no-op if still fresh)."""
    global _jwks_fetched_at  # noqa: PLW0603

    now = time.monotonic()
    with _jwks_lock:
        if now - _jwks_fetched_at < _JWKS_TTL and _jwks_cache:
            return  # still fresh

    try:
        data = _fetch_jwks_raw()
        keys = {k["kid"]: k for k in data.get("keys", []) if "kid" in k}
        with _jwks_lock:
            _jwks_cache.clear()
            _jwks_cache.update(keys)
            _jwks_fetched_at = now
        _log.debug("OIDC: refreshed JWKS (%d keys from %s)", len(keys), _jwks_url())
    except RuntimeError as exc:
        _log.warning("OIDC: JWKS refresh failed, using cached keys: %s", exc)


def _get_jwk(kid: str) -> dict | None:
    """Return the JWK for the given key ID, refreshing if necessary."""
    _refresh_jwks()
    with _jwks_lock:
        return _jwks_cache.get(kid)


# ---------------------------------------------------------------------------
# JWT validation
# ---------------------------------------------------------------------------


def _decode_jwt(token: str) -> dict:
    """Decode and validate a JWT using the JWKS-sourced public key.

    Raises HTTPException on any validation failure.
    """
    try:
        import jwt as _jwt
        from jwt import PyJWTError
    except ImportError as exc:
        raise RuntimeError(
            "OIDC auth requires the 'oidc' extra: pip install 'engramia[oidc]'"
        ) from exc

    # Peek at the header to get the key ID without full validation.
    try:
        header = _jwt.get_unverified_header(token)
    except PyJWTError as exc:
        _log.warning("OIDC: malformed JWT header: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.") from exc

    kid = header.get("kid")
    alg = header.get("alg", "RS256")

    if kid is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing 'kid' header.")

    jwk = _get_jwk(kid)
    if jwk is None:
        # Key not found even after refresh — unknown key or very stale cache.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token signing key not found.",
        )

    try:
        from jwt.algorithms import get_default_algorithms

        algorithms = get_default_algorithms()
        if alg not in algorithms:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Unsupported signing algorithm: {alg}",
            )
        public_key = algorithms[alg].from_jwk(jwk)
    except (KeyError, ValueError, Exception) as exc:
        _log.warning("OIDC: failed to load public key from JWK: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signing key.") from exc

    try:
        claims: dict = _jwt.decode(
            token,
            key=public_key,
            algorithms=[alg],
            audience=_AUDIENCE or None,
            issuer=_ISSUER or None,
            options={"verify_exp": True, "verify_iat": True},
        )
    except PyJWTError as exc:
        _log.info("OIDC: token validation failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token validation failed.") from exc

    return claims


# ---------------------------------------------------------------------------
# Main entry point called from auth.py
# ---------------------------------------------------------------------------


def oidc_auth(request: Request, token: str) -> None:
    """Validate an OIDC Bearer token and set the auth context + scope.

    Called by ``require_auth`` when ``ENGRAMIA_AUTH_MODE=oidc``.
    """
    if not _ISSUER:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC auth is enabled but ENGRAMIA_OIDC_ISSUER is not configured.",
        )

    claims = _decode_jwt(token)

    # Map JWT claims to Engramia constructs.
    role = str(claims.get(_ROLE_CLAIM, _DEFAULT_ROLE)).lower()
    if role not in _VALID_ROLES:
        _log.warning("OIDC: unrecognised role %r in claim %r; falling back to reader", role, _ROLE_CLAIM)
        role = "reader"

    tenant_id = str(claims.get(_TENANT_CLAIM, "default")) if _TENANT_CLAIM else "default"
    project_id = str(claims.get(_PROJECT_CLAIM, "default")) if _PROJECT_CLAIM else "default"

    scope = Scope(tenant_id=tenant_id, project_id=project_id)

    # Use ``sub`` as a stable key identifier (no storage key in OIDC mode).
    subject = str(claims.get("sub", "oidc-unknown"))

    request.state.auth_context = AuthContext(
        key_id=subject,
        tenant_id=tenant_id,
        project_id=project_id,
        role=role,
        max_patterns=None,
        scope=scope,
    )
    set_scope(scope)

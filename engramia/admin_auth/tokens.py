# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Admin JWT issuance and verification.

Distinct from ``engramia.api.cloud_auth`` JWTs:
  * issuer claim ``engramia-admin`` (vs ``engramia-cloud``)
  * audience claim ``engramia-admin-api``
  * separate signing key ``ENGRAMIA_ADMIN_JWT_SECRET`` (HS256)

Two token kinds:

  * intermediate token — short-lived (5 min), single hop between
    ``POST /v1/admin/auth/login`` and ``POST /v1/admin/auth/totp``. Carries
    ``admin_user_id`` and ``stage='totp_required'``. Cannot be used to call
    any admin endpoint other than ``/v1/admin/auth/totp``.

  * admin token — proper bearer (15 min). Carries ``admin_user_id``,
    ``session_id`` (= ``admin_sessions.id``), and ``totp_issued_at``
    (Unix ts; the freshness anchor for ``require_fresh_totp``).

Refresh tokens are *opaque random strings* hashed at rest in
``admin_sessions.refresh_token_hash`` — not JWTs. Treating them as opaque
makes one-time-use rotation trivial and avoids the JWT-revocation tarpit.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass

import jwt

ADMIN_JWT_ISSUER = "engramia-admin"
ADMIN_JWT_AUDIENCE = "engramia-admin-api"

_ALGORITHM = "HS256"

_ACCESS_TOKEN_TTL_SECONDS = 15 * 60  # 15 min — short, refresh handles the rest
_INTERMEDIATE_TOKEN_TTL_SECONDS = 5 * 60  # 5 min — TOTP must arrive quickly

_TOKEN_TYPE_ACCESS = "admin_access"
_TOKEN_TYPE_INTERMEDIATE = "admin_intermediate"


def _secret() -> str:
    """Resolve the admin JWT signing secret.

    Required env var. We *do not* fall back to ``ENGRAMIA_JWT_SECRET`` —
    the whole point of ADR-007 is preventing tenant tokens from passing
    admin verification.
    """
    raw = os.environ.get("ENGRAMIA_ADMIN_JWT_SECRET", "").strip()
    if not raw:
        raise RuntimeError(
            "ENGRAMIA_ADMIN_JWT_SECRET is not set. Generate one with "
            "`python -c 'import secrets; print(secrets.token_urlsafe(48))'` "
            "and add it to your environment. Distinct from "
            "ENGRAMIA_JWT_SECRET (tenant) by design — see "
            "Admin/ARCHITECTURE.md ADR-007."
        )
    return raw


@dataclass(frozen=True)
class AdminTokenClaims:
    """Decoded claims from a verified admin access token."""

    admin_user_id: int
    session_id: str
    totp_issued_at: int  # Unix ts; freshness anchor
    issued_at: int
    expires_at: int


def issue_admin_token(
    *,
    admin_user_id: int,
    session_id: str,
    totp_issued_at: int,
) -> str:
    """Mint a 15-minute admin access JWT."""
    now = int(time.time())
    payload = {
        "iss": ADMIN_JWT_ISSUER,
        "aud": ADMIN_JWT_AUDIENCE,
        "type": _TOKEN_TYPE_ACCESS,
        "sub": str(admin_user_id),
        "admin_user_id": admin_user_id,
        "session_id": session_id,
        "totp_issued_at": totp_issued_at,
        "iat": now,
        "exp": now + _ACCESS_TOKEN_TTL_SECONDS,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def issue_intermediate_token(*, admin_user_id: int) -> str:
    """Mint a 5-minute single-purpose token for the password→TOTP hand-off."""
    now = int(time.time())
    payload = {
        "iss": ADMIN_JWT_ISSUER,
        "aud": ADMIN_JWT_AUDIENCE,
        "type": _TOKEN_TYPE_INTERMEDIATE,
        "sub": str(admin_user_id),
        "admin_user_id": admin_user_id,
        "stage": "totp_required",
        "iat": now,
        "exp": now + _INTERMEDIATE_TOKEN_TTL_SECONDS,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def verify_admin_token(token: str) -> AdminTokenClaims:
    """Verify an admin access token. Raises ``jwt.PyJWTError`` on any failure."""
    payload = jwt.decode(
        token,
        _secret(),
        algorithms=[_ALGORITHM],
        issuer=ADMIN_JWT_ISSUER,
        audience=ADMIN_JWT_AUDIENCE,
        options={"require": ["exp", "iat", "iss", "aud", "type"]},
    )
    if payload.get("type") != _TOKEN_TYPE_ACCESS:
        raise jwt.InvalidTokenError("Wrong token type for admin endpoint")
    return AdminTokenClaims(
        admin_user_id=int(payload["admin_user_id"]),
        session_id=str(payload["session_id"]),
        totp_issued_at=int(payload["totp_issued_at"]),
        issued_at=int(payload["iat"]),
        expires_at=int(payload["exp"]),
    )


def verify_intermediate_token(token: str) -> int:
    """Verify an intermediate token and return the ``admin_user_id``."""
    payload = jwt.decode(
        token,
        _secret(),
        algorithms=[_ALGORITHM],
        issuer=ADMIN_JWT_ISSUER,
        audience=ADMIN_JWT_AUDIENCE,
        options={"require": ["exp", "iat", "iss", "aud", "type"]},
    )
    if payload.get("type") != _TOKEN_TYPE_INTERMEDIATE:
        raise jwt.InvalidTokenError("Wrong token type for TOTP step")
    if payload.get("stage") != "totp_required":
        raise jwt.InvalidTokenError("Intermediate token is missing the TOTP stage marker")
    return int(payload["admin_user_id"])

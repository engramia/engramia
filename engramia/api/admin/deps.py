# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""FastAPI dependencies for admin routes.

Two gates layered on every ``/v1/admin/*`` mutation:

  * :func:`require_super_admin` — verifies the bearer JWT, looks up the
    session, returns an :class:`AdminContext` carrying the
    ``admin_user_id``, ``session_id``, and current freshness anchor.

  * :func:`require_fresh_totp` — factory that wraps the above and rejects
    when ``now - totp_issued_at > window_seconds``. Default 300 s. Use it
    on any destructive endpoint (delete, plan override, force credential
    clear, GDPR action).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC

import jwt
from fastapi import Depends, HTTPException, Request, status

from engramia.admin_auth.service import AdminAuthService
from engramia.admin_auth.tokens import verify_admin_token


@dataclass(frozen=True)
class AdminContext:
    """Per-request context for admin route handlers."""

    admin_user_id: int
    session_id: str
    totp_issued_at: int  # Unix ts — fresh-TOTP gate reads this
    request_ip: str


def get_admin_auth_service(request: Request) -> AdminAuthService:
    """Construct an AdminAuthService bound to the auth DB engine."""
    engine = getattr(request.app.state, "auth_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin endpoints require ENGRAMIA_DATABASE_URL (DB auth mode)",
        )
    # Cheap to instantiate — it's a thin wrapper around the engine.
    return AdminAuthService(engine)


def _client_ip(request: Request) -> str:
    """Best-effort client IP. ``X-Forwarded-For`` first hop, then ``request.client``."""
    xff = request.headers.get("x-forwarded-for", "").strip()
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def require_super_admin(
    request: Request,
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> AdminContext:
    """Verify the admin JWT and confirm the underlying session is still alive.

    Reads ``totp_issued_at`` *from the session row*, not from the JWT.
    This way :func:`require_fresh_totp` reflects ``/auth/totp/reauth``
    bumps even on tokens issued before the bump.
    """
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin endpoint requires Bearer admin_jwt",
            headers={"WWW-Authenticate": 'Bearer realm="engramia-admin"'},
        )
    token = auth.split(" ", 1)[1].strip()
    try:
        claims = verify_admin_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid admin token: {exc}",
        ) from exc

    fresh_at = svc.session_freshness(session_id=claims.session_id)
    if fresh_at is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin session revoked or expired",
        )

    return AdminContext(
        admin_user_id=claims.admin_user_id,
        session_id=claims.session_id,
        totp_issued_at=int(fresh_at.replace(tzinfo=UTC).timestamp())
        if fresh_at.tzinfo is None
        else int(fresh_at.timestamp()),
        request_ip=_client_ip(request),
    )


def require_fresh_totp(window_seconds: int = 300):
    """Return a dependency that rejects stale TOTP for destructive routes.

    Usage::

        @router.delete("/users/{id}", dependencies=[Depends(require_fresh_totp())])
        async def hard_delete_user(...): ...
    """

    def _gate(ctx: AdminContext = Depends(require_super_admin)) -> AdminContext:
        age = int(time.time()) - ctx.totp_issued_at
        if age > window_seconds:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Fresh TOTP required for this action. "
                    f"Last TOTP verification was {age}s ago "
                    f"(limit {window_seconds}s). Re-authenticate via "
                    "POST /v1/admin/auth/totp/reauth."
                ),
                headers={"X-Reauth-Required": "totp"},
            )
        return ctx

    return _gate

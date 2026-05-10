# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Admin Dashboard auth endpoints — ``/v1/admin/auth/*``.

Two-step login (password → TOTP) with per-action TOTP re-prompt for
destructive routes. See ``Admin/ARCHITECTURE.md`` § 5.1 and § 4.2.1.
"""

from __future__ import annotations

import logging

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status

from engramia.admin_auth.service import AdminAuthService
from engramia.admin_auth.tokens import verify_intermediate_token
from engramia.api.admin.audit import log_admin_event, update_admin_event_status
from engramia.api.admin.deps import (
    AdminContext,
    _client_ip,
    get_admin_auth_service,
    require_super_admin,
)
from engramia.api.admin.schemas import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    MeResponse,
    ReauthTotpRequest,
    ReauthTotpResponse,
    RefreshRequest,
    RefreshResponse,
    TotpRequest,
    TotpResponse,
)

_log = logging.getLogger(__name__)

# /admin prefix is added by the parent ``app.include_router(..., prefix="/v1/admin")``.
router = APIRouter(prefix="/admin", tags=["Admin Auth"])


def _environment(request: Request) -> str:
    """The ``environment`` field on admin_audit_log rows.

    Reads ``ENGRAMIA_ENVIRONMENT`` — Core sets this per-deployment
    (``staging`` / ``prod``). Falls back to ``unknown`` so we never crash
    just because the var is unset in dev.
    """
    import os as _os
    return _os.environ.get("ENGRAMIA_ENVIRONMENT", "unknown").strip().lower() or "unknown"


# ---------------------------------------------------------------------------
# /auth/login — password step
# ---------------------------------------------------------------------------


@router.post("/auth/login", response_model=LoginResponse, summary="Admin login (step 1: password)")
async def admin_login(
    request: Request,
    body: LoginRequest,
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> LoginResponse:
    outcome = svc.attempt_login(
        email=body.email,
        password=body.password,
        ip=_client_ip(request),
    )
    return LoginResponse(
        kind=outcome.kind,
        intermediate_token=outcome.intermediate_token,
        detail=outcome.detail,
    )


# ---------------------------------------------------------------------------
# /auth/totp — TOTP step
# ---------------------------------------------------------------------------


@router.post("/auth/totp", response_model=TotpResponse, summary="Admin login (step 2: TOTP)")
async def admin_totp(
    request: Request,
    body: TotpRequest,
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> TotpResponse:
    try:
        admin_user_id = verify_intermediate_token(body.intermediate_token)
    except jwt.PyJWTError as exc:
        return TotpResponse(kind="invalid_token", detail=str(exc))

    outcome = svc.attempt_totp(
        admin_user_id=admin_user_id,
        code=body.code,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    if outcome.kind == "ok":
        # Audit the successful login so admin_audit_log carries a row
        # *every* time a session is minted — even before any subsequent
        # admin action runs.
        try:
            event_id = log_admin_event(
                request.app.state.auth_engine,
                actor_admin_user_id=admin_user_id,
                action="auth.login",
                resource_type="admin_session",
                resource_id=outcome.session_id,
                environment=_environment(request),
                ip_address=_client_ip(request),
                detail={"user_agent": request.headers.get("user-agent")},
            )
            update_admin_event_status(
                request.app.state.auth_engine,
                event_id=event_id,
                status="succeeded",
            )
        except Exception as exc:  # noqa: BLE001 — audit failure must not block login
            _log.error("Failed to write admin_audit_log row for login: %s", exc)

    return TotpResponse(
        kind=outcome.kind,
        admin_jwt=outcome.admin_jwt,
        refresh_token=outcome.refresh_token,
        refresh_expires_at=outcome.expires_at,
        totp_issued_at=outcome.totp_issued_at,
        detail=outcome.detail,
    )


# ---------------------------------------------------------------------------
# /auth/totp/reauth — bump fresh-TOTP anchor without minting a new session
# ---------------------------------------------------------------------------


@router.post(
    "/auth/totp/reauth",
    response_model=ReauthTotpResponse,
    summary="Re-verify TOTP for destructive actions",
)
async def admin_totp_reauth(
    request: Request,
    body: ReauthTotpRequest,
    ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> ReauthTotpResponse:
    outcome = svc.reauth_totp(
        admin_user_id=ctx.admin_user_id,
        session_id=ctx.session_id,
        code=body.code,
        ip=_client_ip(request),
    )
    return ReauthTotpResponse(
        kind=outcome.kind,
        totp_issued_at=outcome.totp_issued_at,
        detail=outcome.detail,
    )


# ---------------------------------------------------------------------------
# /auth/refresh — rotate refresh token
# ---------------------------------------------------------------------------


@router.post("/auth/refresh", response_model=RefreshResponse, summary="Rotate admin refresh token")
async def admin_refresh(
    request: Request,
    body: RefreshRequest,
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> RefreshResponse:
    outcome = svc.refresh(refresh_token=body.refresh_token, ip=_client_ip(request))
    return RefreshResponse(
        kind=outcome.kind,
        admin_jwt=outcome.admin_jwt,
        refresh_token=outcome.refresh_token,
        refresh_expires_at=outcome.expires_at,
        detail=outcome.detail,
    )


# ---------------------------------------------------------------------------
# /auth/logout
# ---------------------------------------------------------------------------


@router.post("/auth/logout", response_model=LogoutResponse, summary="Revoke current admin session")
async def admin_logout(
    ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> LogoutResponse:
    svc.logout(session_id=ctx.session_id)
    return LogoutResponse()


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------


@router.get("/auth/me", response_model=MeResponse, summary="Current admin profile")
async def admin_me(
    ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> MeResponse:
    from sqlalchemy import text
    engine = svc._engine  # noqa: SLF001 — small, controlled coupling
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT id, email, status, totp_enrolled, last_login_at, last_login_ip "
                "FROM admin_users WHERE id = :id"
            ),
            {"id": ctx.admin_user_id},
        ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin user not found",
        )
    return MeResponse(
        id=row[0],
        email=row[1],
        status=row[2],
        totp_enrolled=row[3],
        last_login_at=row[4],
        last_login_ip=row[5],
    )

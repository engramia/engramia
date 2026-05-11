# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Admin Dashboard user/tenant management endpoints.

Phase 1 surface — list, search, detail, force email verification, delete.
Each mutating endpoint writes an ``admin_audit_log`` row (status='attempted'
→ 'succeeded'/'failed') for the SOC2 trail.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from engramia.admin_auth.service import AdminAuthService
from engramia.api.admin.audit import log_admin_event, update_admin_event_status
from engramia.api.admin.deps import (
    AdminContext,
    _client_ip,
    get_admin_auth_service,
    require_fresh_totp,
    require_super_admin,
)

router = APIRouter(prefix="/admin/users", tags=["Admin Users"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class UserSummary(BaseModel):
    id: str  # uuid
    # NOTE: ``str`` (not ``EmailStr``) — admin UI is read-only display; we
    # must surface whatever the row holds even if it does not pass strict
    # RFC validation. Strict email validation belongs at write time
    # (registration / waitlist input), not when listing existing rows.
    email: str
    name: str | None = None
    tenant_id: str
    plan_tier: str
    email_verified: bool
    provider: str
    must_change_password: bool = False
    created_at: datetime
    last_login_at: datetime | None = None
    deleted_at: datetime | None = None


class UserListResponse(BaseModel):
    items: list[UserSummary]
    total: int
    page: int
    page_size: int


class UserDetail(UserSummary):
    deletion_reason: str | None = None
    pending_deletion_token: str | None = None


class VerifyEmailResponse(BaseModel):
    user: UserDetail


class DeleteUserResponse(BaseModel):
    ok: bool = True
    mode: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _environment() -> str:
    import os as _os
    return _os.environ.get("ENGRAMIA_ENVIRONMENT", "unknown").strip().lower() or "unknown"


def _row_to_summary(row) -> UserSummary:
    return UserSummary(
        id=str(row[0]),
        email=str(row[1]),
        name=str(row[2]) if row[2] else None,
        tenant_id=str(row[3]),
        plan_tier=str(row[4] or "free"),
        email_verified=bool(row[5]),
        provider=str(row[6] or "credentials"),
        must_change_password=bool(row[7]) if row[7] is not None else False,
        created_at=row[8],
        last_login_at=row[9],
        deleted_at=row[10] if len(row) > 10 else None,
    )


_BASE_SELECT = (
    "SELECT u.id, u.email, u.name, u.tenant_id, t.plan_tier, "
    "u.email_verified, u.provider, u.must_change_password, "
    "u.created_at, u.last_login_at, u.deleted_at "
    "FROM cloud_users u LEFT JOIN tenants t ON t.id = u.tenant_id"
)


# ---------------------------------------------------------------------------
# GET /v1/admin/users — list + search
# ---------------------------------------------------------------------------


@router.get("", response_model=UserListResponse, summary="List users")
async def list_users(
    q: str | None = Query(None, description="Substring search across email + name"),
    plan: str | None = Query(None, description="Filter by tenant plan_tier"),
    status_filter: str = Query(
        "active",
        alias="status",
        description="'active' | 'deleted' | 'all'",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> UserListResponse:
    where = []
    params: dict = {}
    if q:
        where.append("(LOWER(u.email) LIKE :q OR LOWER(COALESCE(u.name, '')) LIKE :q)")
        params["q"] = f"%{q.lower()}%"
    if plan:
        where.append("t.plan_tier = :plan")
        params["plan"] = plan
    if status_filter == "active":
        where.append("u.deleted_at IS NULL")
    elif status_filter == "deleted":
        where.append("u.deleted_at IS NOT NULL")
    elif status_filter != "all":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown status filter: {status_filter}",
        )

    where_clause = (" WHERE " + " AND ".join(where)) if where else ""

    offset = (page - 1) * page_size
    params["limit"] = page_size
    params["offset"] = offset

    engine = svc._engine  # noqa: SLF001
    with engine.begin() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM cloud_users u LEFT JOIN tenants t ON t.id = u.tenant_id{where_clause}"),
            params,
        ).scalar_one()

        rows = conn.execute(
            text(
                f"{_BASE_SELECT}{where_clause} "
                "ORDER BY u.created_at DESC LIMIT :limit OFFSET :offset",
            ),
            params,
        ).fetchall()

    return UserListResponse(
        items=[_row_to_summary(r) for r in rows],
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /v1/admin/users/{id} — detail
# ---------------------------------------------------------------------------


@router.get("/{user_id}", response_model=UserDetail, summary="User detail")
async def get_user(
    user_id: str,
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> UserDetail:
    engine = svc._engine  # noqa: SLF001
    with engine.begin() as conn:
        row = conn.execute(
            text(f"{_BASE_SELECT} WHERE u.id::text = :uid"),
            {"uid": user_id},
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        summary = _row_to_summary(row)

        # Surface any pending Art.17 deletion request — non-fatal if the
        # table is missing on very old deployments.
        deletion_reason = None
        try:
            dr = conn.execute(
                text(
                    "SELECT reason FROM account_deletion_requests "
                    "WHERE user_id::text = :uid AND completed_at IS NULL "
                    "ORDER BY requested_at DESC LIMIT 1",
                ),
                {"uid": user_id},
            ).first()
            if dr:
                deletion_reason = str(dr[0]) if dr[0] else None
        except Exception:
            pass

    return UserDetail(
        **summary.model_dump(),
        deletion_reason=deletion_reason,
    )


# ---------------------------------------------------------------------------
# POST /v1/admin/users/{id}/verify-email
# ---------------------------------------------------------------------------


@router.post(
    "/{user_id}/verify-email",
    response_model=VerifyEmailResponse,
    summary="Force email verification (skip token flow)",
)
async def force_verify_email(
    request: Request,
    user_id: str,
    ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> VerifyEmailResponse:
    engine = svc._engine  # noqa: SLF001
    event_id = log_admin_event(
        engine,
        actor_admin_user_id=ctx.admin_user_id,
        action="user.verify_email",
        resource_type="cloud_user",
        resource_id=user_id,
        environment=_environment(),
        ip_address=_client_ip(request),
        detail={"target_user_id": user_id},
    )
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    "UPDATE cloud_users SET email_verified = true, "
                    "email_verified_at = COALESCE(email_verified_at, now()) "
                    "WHERE id::text = :uid AND email_verified = false "
                    "RETURNING id",
                ),
                {"uid": user_id},
            ).first()
            if result is None:
                # Either user doesn't exist or already verified — either way,
                # treat as idempotent OK and return current state.
                pass
            row = conn.execute(
                text(f"{_BASE_SELECT} WHERE u.id::text = :uid"),
                {"uid": user_id},
            ).first()
            if row is None:
                update_admin_event_status(
                    engine, event_id=event_id, status="failed", error="user_not_found",
                )
                raise HTTPException(status_code=404, detail="User not found")
        update_admin_event_status(
            engine, event_id=event_id, status="succeeded",
        )
        return VerifyEmailResponse(user=UserDetail(**_row_to_summary(row).model_dump()))
    except HTTPException:
        raise
    except Exception as exc:
        update_admin_event_status(
            engine, event_id=event_id, status="failed", error=str(exc),
        )
        raise


# ---------------------------------------------------------------------------
# DELETE /v1/admin/users/{id} — soft or hard
# ---------------------------------------------------------------------------


class DeleteUserBody(BaseModel):
    mode: Literal["soft", "hard"] = Field(
        "soft",
        description=(
            "soft = mark deleted_at + 30-day grace (existing CLI semantics). "
            "hard = wipe rows (cloud_users + api_keys; tenant kept). "
            "Soft is the GDPR-friendly default."
        ),
    )
    reason: str | None = None


@router.delete(
    "/{user_id}",
    response_model=DeleteUserResponse,
    summary="Soft- or hard-delete a user",
    dependencies=[Depends(require_fresh_totp())],
)
async def delete_user(
    request: Request,
    user_id: str,
    body: DeleteUserBody = Body(default_factory=DeleteUserBody),
    ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> DeleteUserResponse:
    engine = svc._engine  # noqa: SLF001
    event_id = log_admin_event(
        engine,
        actor_admin_user_id=ctx.admin_user_id,
        action=f"user.delete.{body.mode}",
        resource_type="cloud_user",
        resource_id=user_id,
        environment=_environment(),
        ip_address=_client_ip(request),
        detail={"mode": body.mode, "reason": body.reason},
    )

    try:
        with engine.begin() as conn:
            existing = conn.execute(
                text("SELECT id, tenant_id, deleted_at FROM cloud_users WHERE id::text = :uid"),
                {"uid": user_id},
            ).first()
            if existing is None:
                update_admin_event_status(engine, event_id=event_id, status="failed", error="user_not_found")
                raise HTTPException(status_code=404, detail="User not found")

            if body.mode == "soft":
                # Mirrors `engramia cloud delete-account` soft path:
                # set deleted_at, leave 30-day grace; cleanup cron will sweep
                # the data later.
                conn.execute(
                    text(
                        "UPDATE cloud_users SET deleted_at = now(), "
                        "deletion_reason = :reason "
                        "WHERE id::text = :uid AND deleted_at IS NULL",
                    ),
                    {
                        "uid": user_id,
                        "reason": body.reason or f"admin:{ctx.admin_user_id}",
                    },
                )
            else:  # hard
                # Mirror the CLI hard-delete path. Tables with ON DELETE
                # CASCADE on tenant_id (tenant_credentials, billing_*, etc.)
                # are wiped together with the tenant. Here we keep the
                # tenant intact (history of consumption may still be
                # billed/reported) but remove all per-user rows.
                conn.execute(
                    text("DELETE FROM api_keys WHERE tenant_id = (SELECT tenant_id FROM cloud_users WHERE id::text = :uid)"),
                    {"uid": user_id},
                )
                conn.execute(
                    text("DELETE FROM cloud_users WHERE id::text = :uid"),
                    {"uid": user_id},
                )

        update_admin_event_status(
            engine, event_id=event_id, status="succeeded",
            result_detail={"mode": body.mode},
        )
        return DeleteUserResponse(mode=body.mode)
    except HTTPException:
        raise
    except Exception as exc:
        update_admin_event_status(engine, event_id=event_id, status="failed", error=str(exc))
        raise

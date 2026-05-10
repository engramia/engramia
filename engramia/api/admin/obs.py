# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Admin Dashboard observability slices.

Phase 3 surface — small per-tenant slices that an operator scrolls to
when a customer reports an issue. Not a Grafana replacement; deep dives
deep-link out to Grafana.

All endpoints are read-only and do NOT write admin_audit_log (would
swamp the trail with noise on every operator page-load).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text

from engramia.admin_auth.service import AdminAuthService
from engramia.api.admin.deps import (
    AdminContext,
    get_admin_auth_service,
    require_super_admin,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/obs", tags=["Admin Observability"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ErrorSample(BaseModel):
    created_at: datetime
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    actor_user_id: str | None = None
    detail_summary: str | None = None


class ErrorsResponse(BaseModel):
    tenant_id: str
    period: str
    total_errors: int
    samples: list[ErrorSample]


class UsageBucket(BaseModel):
    action: str
    count: int


class UsageResponse(BaseModel):
    tenant_id: str
    period: str
    total_requests: int
    by_action: list[UsageBucket]
    distinct_users: int
    grafana_url: str | None = None


class LastLoginEntry(BaseModel):
    user_id: str
    email: str
    last_login_at: datetime | None = None
    created_at: datetime
    email_verified: bool


class LastLoginResponse(BaseModel):
    tenant_id: str
    users: list[LastLoginEntry]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_period(period: str) -> timedelta:
    """Parse '1h', '24h', '7d', '30d' shorthand."""
    if period.endswith("h"):
        return timedelta(hours=int(period[:-1]))
    if period.endswith("d"):
        return timedelta(days=int(period[:-1]))
    if period.endswith("m"):
        return timedelta(minutes=int(period[:-1]))
    return timedelta(hours=24)


def _grafana_url_for(tenant_id: str) -> str | None:
    """Stub — operator can configure a tenant dashboard URL template later."""
    import os as _os
    template = _os.environ.get("ENGRAMIA_GRAFANA_TENANT_URL_TEMPLATE", "").strip()
    if not template:
        return None
    return template.replace("{tenant_id}", tenant_id)


# ---------------------------------------------------------------------------
# GET /v1/admin/obs/{tenant_id}/errors
# ---------------------------------------------------------------------------


@router.get(
    "/{tenant_id}/errors",
    response_model=ErrorsResponse,
    summary="Recent error-flagged audit events for a tenant",
)
async def tenant_errors(
    tenant_id: str,
    since: str = Query("24h", description="Lookback window — '1h', '24h', '7d', etc."),
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> ErrorsResponse:
    cutoff = datetime.utcnow() - _parse_period(since)
    engine = svc._engine  # noqa: SLF001
    with engine.begin() as conn:
        total = conn.execute(
            text(
                "SELECT COUNT(*) FROM audit_log "
                "WHERE tenant_id = :tid AND created_at >= :cutoff "
                "  AND (action LIKE '%error%' OR action LIKE '%fail%' "
                "       OR action LIKE '%reject%' OR action LIKE '%unauthorized%')",
            ),
            {"tid": tenant_id, "cutoff": cutoff},
        ).scalar_one()

        samples = conn.execute(
            text(
                "SELECT created_at, action, resource_type, resource_id, "
                "actor_user_id, detail "
                "FROM audit_log "
                "WHERE tenant_id = :tid AND created_at >= :cutoff "
                "  AND (action LIKE '%error%' OR action LIKE '%fail%' "
                "       OR action LIKE '%reject%' OR action LIKE '%unauthorized%') "
                "ORDER BY created_at DESC LIMIT 25",
            ),
            {"tid": tenant_id, "cutoff": cutoff},
        ).fetchall()

    return ErrorsResponse(
        tenant_id=tenant_id,
        period=since,
        total_errors=int(total or 0),
        samples=[
            ErrorSample(
                created_at=r[0],
                action=str(r[1]),
                resource_type=str(r[2]) if r[2] else None,
                resource_id=str(r[3]) if r[3] else None,
                actor_user_id=str(r[4]) if r[4] else None,
                detail_summary=_summarize_detail(r[5]),
            )
            for r in samples
        ],
    )


# ---------------------------------------------------------------------------
# GET /v1/admin/obs/{tenant_id}/usage
# ---------------------------------------------------------------------------


@router.get(
    "/{tenant_id}/usage",
    response_model=UsageResponse,
    summary="API call counts for a tenant over a period",
)
async def tenant_usage(
    tenant_id: str,
    period: str = Query("7d"),
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> UsageResponse:
    cutoff = datetime.utcnow() - _parse_period(period)
    engine = svc._engine  # noqa: SLF001
    with engine.begin() as conn:
        total = conn.execute(
            text(
                "SELECT COUNT(*) FROM audit_log WHERE tenant_id = :tid AND created_at >= :cutoff",
            ),
            {"tid": tenant_id, "cutoff": cutoff},
        ).scalar_one()

        buckets = conn.execute(
            text(
                "SELECT action, COUNT(*) AS n FROM audit_log "
                "WHERE tenant_id = :tid AND created_at >= :cutoff "
                "GROUP BY action ORDER BY n DESC LIMIT 20",
            ),
            {"tid": tenant_id, "cutoff": cutoff},
        ).fetchall()

        distinct_users = conn.execute(
            text(
                "SELECT COUNT(DISTINCT COALESCE(actor_user_id, key_id)) "
                "FROM audit_log WHERE tenant_id = :tid AND created_at >= :cutoff",
            ),
            {"tid": tenant_id, "cutoff": cutoff},
        ).scalar_one()

    return UsageResponse(
        tenant_id=tenant_id,
        period=period,
        total_requests=int(total or 0),
        by_action=[UsageBucket(action=str(r[0]), count=int(r[1])) for r in buckets],
        distinct_users=int(distinct_users or 0),
        grafana_url=_grafana_url_for(tenant_id),
    )


# ---------------------------------------------------------------------------
# GET /v1/admin/obs/{tenant_id}/last-login
# ---------------------------------------------------------------------------


@router.get(
    "/{tenant_id}/last-login",
    response_model=LastLoginResponse,
    summary="Last login per cloud_user in the tenant",
)
async def tenant_last_login(
    tenant_id: str,
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> LastLoginResponse:
    engine = svc._engine  # noqa: SLF001
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id::text, email, last_login_at, created_at, email_verified "
                "FROM cloud_users WHERE tenant_id = :tid AND deleted_at IS NULL "
                "ORDER BY last_login_at DESC NULLS LAST",
            ),
            {"tid": tenant_id},
        ).fetchall()

    return LastLoginResponse(
        tenant_id=tenant_id,
        users=[
            LastLoginEntry(
                user_id=str(r[0]),
                email=str(r[1]),
                last_login_at=r[2],
                created_at=r[3],
                email_verified=bool(r[4]),
            )
            for r in rows
        ],
    )


def _summarize_detail(detail) -> str | None:
    """Pluck the first ~120 chars of the audit detail JSON for the table view."""
    if detail is None:
        return None
    s = str(detail)
    return s[:120] + ("…" if len(s) > 120 else "")

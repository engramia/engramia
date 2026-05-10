# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Admin Dashboard audit viewer.

Two read-only endpoints:

  * ``GET /v1/admin/audit`` — tenant ``audit_log`` table (every customer-facing
    auth/API event). Used to investigate suspicious tenant activity.
  * ``GET /v1/admin/admin-audit`` — operator ``admin_audit_log`` table.
    Used by the admin to review their own actions or future compliance audit.

Pure reads — no audit row is written for viewing the audit log.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from engramia.admin_auth.service import AdminAuthService
from engramia.api.admin.deps import (
    AdminContext,
    get_admin_auth_service,
    require_super_admin,
)

router = APIRouter(prefix="/admin", tags=["Admin Audit"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TenantAuditEntry(BaseModel):
    id: int
    tenant_id: str | None = None
    project_id: str | None = None
    key_id: str | None = None
    actor_user_id: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    ip_address: str | None = None
    detail: dict[str, Any] | None = None
    # Parsed via ``_parse_audit_timestamp`` below — ``audit_log.created_at``
    # is a TEXT column whose ``now()::text`` shape (``+TT`` offset without
    # colon) Pydantic v2's strict RFC 3339 parser rejects, so the constructor
    # pre-parses with ``datetime.fromisoformat`` (Python 3.11+).
    created_at: datetime


class TenantAuditListResponse(BaseModel):
    items: list[TenantAuditEntry]
    total: int


class AdminAuditEntry(BaseModel):
    id: int
    actor_admin_user_id: int
    actor_email: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    target_tenant_id: int | None = None
    status: str
    environment: str
    ip_address: str | None = None
    detail: dict[str, Any] | None = None
    created_at: datetime
    completed_at: datetime | None = None


class AdminAuditListResponse(BaseModel):
    items: list[AdminAuditEntry]
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_detail(raw) -> dict | None:
    """Best-effort JSON parse of the ``detail`` column.

    PostgreSQL JSONB returns a dict via psycopg2 already; SQLite returns
    string. Tolerate both.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
    return {"raw": str(raw)}


def _parse_audit_timestamp(raw) -> datetime:
    """Coerce ``audit_log.created_at`` to a real ``datetime``.

    The column is ``TEXT`` populated by ``now()::text`` (see
    ``engramia.api.audit:log_db_event``), which yields strings like
    ``'2026-05-11 22:16:25.123456+00'``. Pydantic v2's strict ISO-8601
    parser rejects the single-digit timezone offset; Python's
    ``datetime.fromisoformat`` (3.11+) accepts it. Idempotent for
    drivers that already return ``datetime``.
    """
    if isinstance(raw, datetime):
        return raw
    return datetime.fromisoformat(str(raw))


# ---------------------------------------------------------------------------
# GET /v1/admin/audit — tenant audit_log
# ---------------------------------------------------------------------------


@router.get(
    "/audit",
    response_model=TenantAuditListResponse,
    summary="View tenant audit_log (customer-facing events)",
)
async def list_tenant_audit(
    tenant_id: str | None = Query(None),
    action: str | None = Query(None, description="Substring match on action name"),
    actor_user_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> TenantAuditListResponse:
    where: list[str] = []
    params: dict = {}
    if tenant_id:
        where.append("tenant_id = :tid")
        params["tid"] = tenant_id
    if action:
        where.append("action LIKE :action")
        params["action"] = f"%{action}%"
    if actor_user_id:
        where.append("(actor_user_id = :auid OR key_id = :auid)")
        params["auid"] = actor_user_id

    where_clause = (" WHERE " + " AND ".join(where)) if where else ""
    offset = (page - 1) * page_size
    params["limit"] = page_size
    params["offset"] = offset

    engine = svc._engine  # noqa: SLF001
    with engine.begin() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM audit_log{where_clause}"),
            params,
        ).scalar_one()
        rows = conn.execute(
            text(
                "SELECT id, tenant_id, project_id, key_id, actor_user_id, action, "
                "resource_type, resource_id, ip_address, detail, created_at "
                f"FROM audit_log{where_clause} "
                "ORDER BY created_at DESC LIMIT :limit OFFSET :offset",
            ),
            params,
        ).fetchall()

    return TenantAuditListResponse(
        items=[
            TenantAuditEntry(
                id=int(r[0]),
                tenant_id=str(r[1]) if r[1] else None,
                project_id=str(r[2]) if r[2] else None,
                key_id=str(r[3]) if r[3] else None,
                actor_user_id=str(r[4]) if r[4] else None,
                action=str(r[5]),
                resource_type=str(r[6]) if r[6] else None,
                resource_id=str(r[7]) if r[7] else None,
                ip_address=str(r[8]) if r[8] else None,
                detail=_parse_detail(r[9]),
                created_at=_parse_audit_timestamp(r[10]),
            )
            for r in rows
        ],
        total=int(total or 0),
    )


@router.get(
    "/audit/{event_id}",
    response_model=TenantAuditEntry,
    summary="Tenant audit_log row detail",
)
async def get_tenant_audit_entry(
    event_id: int,
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> TenantAuditEntry:
    engine = svc._engine  # noqa: SLF001
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT id, tenant_id, project_id, key_id, actor_user_id, action, "
                "resource_type, resource_id, ip_address, detail, created_at "
                "FROM audit_log WHERE id = :id",
            ),
            {"id": event_id},
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Audit entry not found")
    return TenantAuditEntry(
        id=int(row[0]),
        tenant_id=str(row[1]) if row[1] else None,
        project_id=str(row[2]) if row[2] else None,
        key_id=str(row[3]) if row[3] else None,
        actor_user_id=str(row[4]) if row[4] else None,
        action=str(row[5]),
        resource_type=str(row[6]) if row[6] else None,
        resource_id=str(row[7]) if row[7] else None,
        ip_address=str(row[8]) if row[8] else None,
        detail=_parse_detail(row[9]),
        created_at=_parse_audit_timestamp(row[10]),
    )


# ---------------------------------------------------------------------------
# GET /v1/admin/admin-audit — admin_audit_log (operator actions)
# ---------------------------------------------------------------------------


@router.get(
    "/admin-audit",
    response_model=AdminAuditListResponse,
    summary="View admin_audit_log (operator actions)",
)
async def list_admin_audit(
    action: str | None = Query(None, description="Substring match"),
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> AdminAuditListResponse:
    where: list[str] = []
    params: dict = {}
    if action:
        where.append("a.action LIKE :action")
        params["action"] = f"%{action}%"
    if status_filter:
        if status_filter not in {"attempted", "succeeded", "failed"}:
            raise HTTPException(status_code=400, detail=f"Unknown status: {status_filter}")
        where.append("a.status = :status")
        params["status"] = status_filter

    where_clause = (" WHERE " + " AND ".join(where)) if where else ""
    offset = (page - 1) * page_size
    params["limit"] = page_size
    params["offset"] = offset

    engine = svc._engine  # noqa: SLF001
    with engine.begin() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM admin_audit_log a{where_clause}"),
            params,
        ).scalar_one()
        rows = conn.execute(
            text(
                "SELECT a.id, a.actor_admin_user_id, u.email, a.action, "
                "a.resource_type, a.resource_id, a.target_tenant_id, a.status, "
                "a.environment, a.ip_address, a.detail, a.created_at, a.completed_at "
                "FROM admin_audit_log a "
                "LEFT JOIN admin_users u ON u.id = a.actor_admin_user_id"
                f"{where_clause} "
                "ORDER BY a.created_at DESC LIMIT :limit OFFSET :offset",
            ),
            params,
        ).fetchall()

    return AdminAuditListResponse(
        items=[
            AdminAuditEntry(
                id=int(r[0]),
                actor_admin_user_id=int(r[1]),
                actor_email=str(r[2]) if r[2] else None,
                action=str(r[3]),
                resource_type=str(r[4]) if r[4] else None,
                resource_id=str(r[5]) if r[5] else None,
                target_tenant_id=int(r[6]) if r[6] is not None else None,
                status=str(r[7]),
                environment=str(r[8]),
                ip_address=str(r[9]) if r[9] else None,
                detail=_parse_detail(r[10]),
                created_at=r[11],
                completed_at=r[12],
            )
            for r in rows
        ],
        total=int(total or 0),
    )

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Admin Dashboard overview/home endpoint.

Returns the small set of counters shown on the admin home page (pending
pilots, active users, recent admin actions). Read-only — no audit log
entry is written for this endpoint.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from engramia.admin_auth.service import AdminAuthService
from engramia.api.admin.deps import (
    AdminContext,
    get_admin_auth_service,
    require_super_admin,
)

router = APIRouter(prefix="/admin", tags=["Admin Overview"])


class RecentAdminAction(BaseModel):
    id: int
    action: str
    actor_email: str | None = None
    target_tenant_id: int | None = None
    status: str
    created_at: datetime


class OverviewResponse(BaseModel):
    pending_pilots: int
    active_users: int
    locked_admins: int
    admin_audit_total: int
    recent_admin_actions: list[RecentAdminAction]


@router.get("/overview", response_model=OverviewResponse, summary="Admin home page counters")
async def admin_overview(
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> OverviewResponse:
    engine = svc._engine  # noqa: SLF001 — controlled coupling
    with engine.begin() as conn:
        pending_pilots = conn.execute(
            text("SELECT COUNT(*) FROM waitlist_requests WHERE status = 'pending'"),
        ).scalar_one()

        # active = not soft-deleted (deleted_at IS NULL is the live flag).
        active_users = conn.execute(
            text(
                "SELECT COUNT(*) FROM cloud_users WHERE deleted_at IS NULL"
                if _column_exists(conn, "cloud_users", "deleted_at")
                else "SELECT COUNT(*) FROM cloud_users"
            ),
        ).scalar_one()

        locked_admins = conn.execute(
            text("SELECT COUNT(*) FROM admin_users WHERE status != 'active'"),
        ).scalar_one()

        audit_total = conn.execute(
            text("SELECT COUNT(*) FROM admin_audit_log"),
        ).scalar_one()

        # 5 most recent admin actions with actor email joined in.
        recent_rows = conn.execute(
            text(
                "SELECT a.id, a.action, u.email, a.target_tenant_id, a.status, a.created_at "
                "FROM admin_audit_log a "
                "LEFT JOIN admin_users u ON u.id = a.actor_admin_user_id "
                "ORDER BY a.created_at DESC LIMIT 5",
            ),
        ).fetchall()

    return OverviewResponse(
        pending_pilots=int(pending_pilots or 0),
        active_users=int(active_users or 0),
        locked_admins=int(locked_admins or 0),
        admin_audit_total=int(audit_total or 0),
        recent_admin_actions=[
            RecentAdminAction(
                id=int(r[0]),
                action=str(r[1]),
                actor_email=str(r[2]) if r[2] else None,
                target_tenant_id=int(r[3]) if r[3] is not None else None,
                status=str(r[4]),
                created_at=r[5],
            )
            for r in recent_rows
        ],
    )


def _column_exists(conn, table: str, column: str) -> bool:
    """Defensive check — older Core deployments may not have soft-delete columns yet."""
    try:
        row = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c LIMIT 1",
            ),
            {"t": table, "c": column},
        ).first()
        return row is not None
    except Exception:
        return False

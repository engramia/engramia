# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Admin Dashboard GDPR / Governance endpoints.

Phase 3 surface — unified deletion-request queue (Art.17 self-service
token flow + free-form DSR queue) and read-only DSR overview.

Art.20 export is currently triggered via the existing
``engramia governance export`` CLI subcommand; wiring it through HTTP
is intentionally deferred until the job-queue export pipeline is
hardened. The admin UI surfaces a workaround note for the operator.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
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

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/governance", tags=["Admin Governance"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


DeletionRequestKind = Literal["account_deletion", "dsr"]


class DeletionRequest(BaseModel):
    """Unified DTO that bridges account_deletion_requests + dsr_requests rows."""

    kind: DeletionRequestKind
    id: str  # token_hash for account_deletion; id for dsr_requests
    user_id: str | None = None
    user_email: str | None = None  # not EmailStr — read-only admin display
    tenant_id: str | None = None
    request_type: str | None = None  # for dsr_requests
    status: str  # pending | consumed | canceled | rejected | completed
    reason: str | None = None
    created_at: datetime
    expires_at: datetime | None = None  # account_deletion only
    deadline: datetime | None = None  # dsr only
    consumed_at: datetime | None = None
    completed_at: datetime | None = None


class DeletionRequestListResponse(BaseModel):
    items: list[DeletionRequest]
    total: int


class CancelBody(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class CancelResponse(BaseModel):
    kind: str
    id: str
    new_status: str


class ApproveResponse(BaseModel):
    kind: str
    id: str
    new_status: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _environment() -> str:
    import os as _os
    return _os.environ.get("ENGRAMIA_ENVIRONMENT", "unknown").strip().lower() or "unknown"


# ---------------------------------------------------------------------------
# GET /v1/admin/governance/deletion-requests
# ---------------------------------------------------------------------------


@router.get(
    "/deletion-requests",
    response_model=DeletionRequestListResponse,
    summary="Unified list of Art.17 deletion requests + DSR queue",
)
async def list_deletion_requests(
    status_filter: str = Query(
        "pending",
        alias="status",
        description="'pending' | 'all' (account_deletion rows are 'pending' when consumed_at IS NULL).",
    ),
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> DeletionRequestListResponse:
    engine = svc._engine  # noqa: SLF001
    items: list[DeletionRequest] = []

    with engine.begin() as conn:
        # account_deletion_requests — join cloud_users for context.
        # 'pending' = not yet consumed; we surface the 24h token window.
        adr_where = "WHERE adr.consumed_at IS NULL" if status_filter == "pending" else ""
        try:
            adr_rows = conn.execute(
                text(
                    "SELECT adr.token_hash, adr.user_id, adr.reason, "
                    "adr.created_at, adr.expires_at, adr.consumed_at, "
                    "cu.email, cu.tenant_id "
                    "FROM account_deletion_requests adr "
                    "LEFT JOIN cloud_users cu ON cu.id = adr.user_id "
                    f"{adr_where} "
                    "ORDER BY adr.created_at DESC LIMIT 500",
                ),
            ).fetchall()
            for r in adr_rows:
                token_hash_partial = str(r[0])[:16]
                items.append(
                    DeletionRequest(
                        kind="account_deletion",
                        id=token_hash_partial,
                        user_id=str(r[1]) if r[1] else None,
                        user_email=str(r[6]) if r[6] else None,
                        tenant_id=str(r[7]) if r[7] else None,
                        status="pending" if r[5] is None else "consumed",
                        reason=str(r[2]) if r[2] else None,
                        created_at=r[3],
                        expires_at=r[4],
                        consumed_at=r[5],
                    )
                )
        except Exception as exc:  # noqa: BLE001
            _log.debug("account_deletion_requests query failed: %s", exc)

        # dsr_requests — broader Art.15-20 queue.
        dsr_where = (
            "WHERE status = 'pending'"
            if status_filter == "pending"
            else ""
        )
        try:
            dsr_rows = conn.execute(
                text(
                    "SELECT id, tenant_id, request_type, subject_email, status, "
                    "created_at, deadline, completed_at, notes "
                    "FROM dsr_requests "
                    f"{dsr_where} "
                    "ORDER BY created_at DESC LIMIT 500",
                ),
            ).fetchall()
            for r in dsr_rows:
                created_at = r[5]
                deadline = r[6]
                completed_at = r[7]
                # dsr_requests stores ISO strings in TEXT columns historically;
                # parse where needed for the DTO.
                items.append(
                    DeletionRequest(
                        kind="dsr",
                        id=str(r[0]),
                        user_email=str(r[3]) if r[3] else None,
                        tenant_id=str(r[1]) if r[1] else None,
                        request_type=str(r[2]) if r[2] else None,
                        status=str(r[4]),
                        reason=str(r[8]) if r[8] else None,
                        created_at=_parse_iso(created_at),
                        deadline=_parse_iso(deadline),
                        completed_at=_parse_iso(completed_at) if completed_at else None,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            _log.debug("dsr_requests query failed: %s", exc)

    # Sort unified list newest-first.
    items.sort(key=lambda x: x.created_at, reverse=True)
    return DeletionRequestListResponse(items=items, total=len(items))


def _parse_iso(value) -> datetime:
    """Tolerate either real timestamps or ISO strings in TEXT columns."""
    if isinstance(value, datetime):
        return value
    if value is None:
        # Use epoch so sorting still works
        return datetime.fromtimestamp(0)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.fromtimestamp(0)


# ---------------------------------------------------------------------------
# POST /v1/admin/governance/deletion-requests/{kind}/{id}/approve
# ---------------------------------------------------------------------------


@router.post(
    "/deletion-requests/{kind}/{request_id}/approve",
    response_model=ApproveResponse,
    summary="Approve/complete a deletion request (advances state)",
    dependencies=[Depends(require_fresh_totp())],
)
async def approve_deletion_request(
    request: Request,
    kind: str,
    request_id: str,
    ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> ApproveResponse:
    if kind not in {"account_deletion", "dsr"}:
        raise HTTPException(status_code=400, detail=f"Unknown kind: {kind}")

    engine = svc._engine  # noqa: SLF001
    event_id = log_admin_event(
        engine,
        actor_admin_user_id=ctx.admin_user_id,
        action=f"governance.{kind}.approve",
        resource_type=kind,
        resource_id=request_id,
        environment=_environment(),
        ip_address=_client_ip(request),
        detail={"kind": kind, "id": request_id},
    )

    try:
        with engine.begin() as conn:
            if kind == "account_deletion":
                # Match either full token_hash or a prefix from the unified view.
                row = conn.execute(
                    text(
                        "SELECT token_hash, user_id, consumed_at FROM account_deletion_requests "
                        "WHERE token_hash = :rid OR LEFT(token_hash, 16) = :rid",
                    ),
                    {"rid": request_id},
                ).first()
                if row is None:
                    update_admin_event_status(
                        engine, event_id=event_id, status="failed", error="not_found",
                    )
                    raise HTTPException(status_code=404, detail="Deletion request not found")
                if row[2] is not None:
                    update_admin_event_status(
                        engine, event_id=event_id, status="failed", error="already_consumed",
                    )
                    raise HTTPException(status_code=409, detail="Already consumed")
                # Mark consumed + soft-delete the user (same effect as the user
                # would have triggered via the email-confirm link).
                conn.execute(
                    text(
                        "UPDATE account_deletion_requests SET consumed_at = now() "
                        "WHERE token_hash = :rid",
                    ),
                    {"rid": row[0]},
                )
                conn.execute(
                    text(
                        "UPDATE cloud_users SET deleted_at = COALESCE(deleted_at, now()), "
                        "deletion_reason = COALESCE(deletion_reason, :reason) "
                        "WHERE id = :uid",
                    ),
                    {"uid": row[1], "reason": f"admin-approved:{ctx.admin_user_id}"},
                )
                new_status = "consumed"
            else:  # dsr
                row = conn.execute(
                    text("SELECT id, status FROM dsr_requests WHERE id = :rid"),
                    {"rid": request_id},
                ).first()
                if row is None:
                    update_admin_event_status(
                        engine, event_id=event_id, status="failed", error="not_found",
                    )
                    raise HTTPException(status_code=404, detail="DSR not found")
                if row[1] != "pending":
                    update_admin_event_status(
                        engine, event_id=event_id, status="failed",
                        error=f"already_{row[1]}",
                    )
                    raise HTTPException(status_code=409, detail=f"DSR already {row[1]}")
                conn.execute(
                    text(
                        "UPDATE dsr_requests SET status='completed', "
                        "completed_at=:ts, updated_at=:ts WHERE id = :rid",
                    ),
                    {"rid": request_id, "ts": datetime.utcnow().isoformat()},
                )
                new_status = "completed"

        update_admin_event_status(
            engine, event_id=event_id, status="succeeded",
            result_detail={"new_status": new_status},
        )
        return ApproveResponse(kind=kind, id=request_id, new_status=new_status)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        update_admin_event_status(engine, event_id=event_id, status="failed", error=str(exc))
        raise


# ---------------------------------------------------------------------------
# POST /v1/admin/governance/deletion-requests/{kind}/{id}/cancel
# ---------------------------------------------------------------------------


@router.post(
    "/deletion-requests/{kind}/{request_id}/cancel",
    response_model=CancelResponse,
    summary="Cancel a deletion request",
    dependencies=[Depends(require_fresh_totp())],
)
async def cancel_deletion_request(
    request: Request,
    kind: str,
    request_id: str,
    body: CancelBody = Body(default_factory=CancelBody),
    ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> CancelResponse:
    if kind not in {"account_deletion", "dsr"}:
        raise HTTPException(status_code=400, detail=f"Unknown kind: {kind}")

    engine = svc._engine  # noqa: SLF001
    event_id = log_admin_event(
        engine,
        actor_admin_user_id=ctx.admin_user_id,
        action=f"governance.{kind}.cancel",
        resource_type=kind,
        resource_id=request_id,
        environment=_environment(),
        ip_address=_client_ip(request),
        detail={"reason": body.reason},
    )

    try:
        with engine.begin() as conn:
            if kind == "account_deletion":
                # Cancel = delete the row (token is one-use; removing it means
                # the user has to start the flow over from /settings/account).
                result = conn.execute(
                    text(
                        "DELETE FROM account_deletion_requests "
                        "WHERE (token_hash = :rid OR LEFT(token_hash, 16) = :rid) "
                        "  AND consumed_at IS NULL",
                    ),
                    {"rid": request_id},
                )
                if result.rowcount == 0:
                    update_admin_event_status(
                        engine, event_id=event_id, status="failed",
                        error="not_found_or_consumed",
                    )
                    raise HTTPException(status_code=404, detail="Pending request not found")
                new_status = "canceled"
            else:  # dsr
                result = conn.execute(
                    text(
                        "UPDATE dsr_requests SET status='canceled', "
                        "updated_at=:ts, notes = COALESCE(notes, '') || :note "
                        "WHERE id = :rid AND status = 'pending'",
                    ),
                    {
                        "rid": request_id,
                        "ts": datetime.utcnow().isoformat(),
                        "note": f"\n[admin {ctx.admin_user_id} canceled]: {body.reason or ''}",
                    },
                )
                if result.rowcount == 0:
                    update_admin_event_status(
                        engine, event_id=event_id, status="failed",
                        error="not_found_or_completed",
                    )
                    raise HTTPException(status_code=404, detail="Pending DSR not found")
                new_status = "canceled"

        update_admin_event_status(
            engine, event_id=event_id, status="succeeded",
            result_detail={"new_status": new_status},
        )
        return CancelResponse(kind=kind, id=request_id, new_status=new_status)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        update_admin_event_status(engine, event_id=event_id, status="failed", error=str(exc))
        raise

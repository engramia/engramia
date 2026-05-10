# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Admin Dashboard non-infra operations.

Phase 2 surface — wrap the most common ``engramia cleanup …`` / ``engramia
cloud …`` CLI flows in HTTP endpoints, plus an inspector + retry control
over the job queue (``jobs`` table from migration 004).

Cleanup endpoints are split into a preview (count-only, idempotent)
and an execute (mutating, audited, fresh-TOTP gated). The execute path
mirrors the SQL used by the CLI subcommands so the behaviour is
identical between operator paths.
"""

from __future__ import annotations

import logging
import uuid
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

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/ops", tags=["Admin Ops"])


CleanupKind = Literal[
    "unverified_users_7d",
    "unverified_users_14d",
    "deleted_accounts_grace_30d",
    "expired_verification_tokens",
]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CleanupPreviewBody(BaseModel):
    kind: CleanupKind


class CleanupPreviewResponse(BaseModel):
    kind: str
    will_delete_count: int
    sample: list[dict] = Field(default_factory=list)
    description: str


class CleanupExecuteBody(BaseModel):
    kind: CleanupKind
    confirmed_count: int = Field(
        ge=0,
        description=(
            "Operator-supplied expected count from the preview step. "
            "If it diverges from the live count by more than 20% the "
            "endpoint refuses — protects against new rows arriving "
            "between preview and execute."
        ),
    )


class CleanupExecuteResponse(BaseModel):
    kind: str
    deleted_count: int
    job_id: str


class JobSummary(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    operation: str
    status: str
    attempts: int
    max_attempts: int
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


class JobListResponse(BaseModel):
    items: list[JobSummary]
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _environment() -> str:
    import os as _os
    return _os.environ.get("ENGRAMIA_ENVIRONMENT", "unknown").strip().lower() or "unknown"


# Each cleanup kind: (description, COUNT sql, sample sql, DELETE sql).
# All SQL is parameterless — these are time-bounded, not user-input bounded.
_CLEANUP_DEFS: dict[CleanupKind, dict[str, str]] = {
    "unverified_users_7d": {
        "description": (
            "cloud_users where email_verified=false AND created_at < now() - 7 days. "
            "Mirrors `engramia cleanup unverified-users --age-days 7` CLI flow."
        ),
        "count": (
            "SELECT COUNT(*) FROM cloud_users "
            "WHERE provider = 'credentials' "
            "  AND email_verified = false "
            "  AND created_at < now() - INTERVAL '7 days'"
        ),
        "sample": (
            "SELECT email, created_at FROM cloud_users "
            "WHERE provider = 'credentials' "
            "  AND email_verified = false "
            "  AND created_at < now() - INTERVAL '7 days' "
            "ORDER BY created_at LIMIT 5"
        ),
        "delete": (
            "DELETE FROM cloud_users "
            "WHERE provider = 'credentials' "
            "  AND email_verified = false "
            "  AND created_at < now() - INTERVAL '7 days'"
        ),
    },
    "unverified_users_14d": {
        "description": (
            "cloud_users where email_verified=false AND created_at < now() - 14 days "
            "(more conservative — second sweep)."
        ),
        "count": (
            "SELECT COUNT(*) FROM cloud_users "
            "WHERE provider = 'credentials' "
            "  AND email_verified = false "
            "  AND created_at < now() - INTERVAL '14 days'"
        ),
        "sample": (
            "SELECT email, created_at FROM cloud_users "
            "WHERE provider = 'credentials' "
            "  AND email_verified = false "
            "  AND created_at < now() - INTERVAL '14 days' "
            "ORDER BY created_at LIMIT 5"
        ),
        "delete": (
            "DELETE FROM cloud_users "
            "WHERE provider = 'credentials' "
            "  AND email_verified = false "
            "  AND created_at < now() - INTERVAL '14 days'"
        ),
    },
    "deleted_accounts_grace_30d": {
        "description": (
            "Soft-deleted accounts where deleted_at < now() - 30 days. "
            "Mirrors `engramia cleanup deleted-accounts` CLI flow — wipes "
            "api_keys, cloud_users; tenant retained for billing history."
        ),
        "count": (
            "SELECT COUNT(*) FROM cloud_users "
            "WHERE deleted_at IS NOT NULL "
            "  AND deleted_at < now() - INTERVAL '30 days'"
        ),
        "sample": (
            "SELECT email, deleted_at FROM cloud_users "
            "WHERE deleted_at IS NOT NULL "
            "  AND deleted_at < now() - INTERVAL '30 days' "
            "ORDER BY deleted_at LIMIT 5"
        ),
        "delete": (
            "DELETE FROM cloud_users "
            "WHERE deleted_at IS NOT NULL "
            "  AND deleted_at < now() - INTERVAL '30 days'"
        ),
    },
    "expired_verification_tokens": {
        "description": (
            "email_verification_tokens past their expires_at timestamp. "
            "Cheap housekeeping — no user-facing impact."
        ),
        "count": "SELECT COUNT(*) FROM email_verification_tokens WHERE expires_at < now()",
        "sample": (
            "SELECT user_id, expires_at FROM email_verification_tokens "
            "WHERE expires_at < now() ORDER BY expires_at LIMIT 5"
        ),
        "delete": "DELETE FROM email_verification_tokens WHERE expires_at < now()",
    },
}


def _row_to_dict(row) -> dict:
    out: dict = {}
    for i, val in enumerate(row):
        out[f"col_{i}"] = (
            val.isoformat() if isinstance(val, datetime) else str(val) if val is not None else None
        )
    return out


# ---------------------------------------------------------------------------
# POST /v1/admin/ops/cleanup/preview
# ---------------------------------------------------------------------------


@router.post(
    "/cleanup/preview",
    response_model=CleanupPreviewResponse,
    summary="Preview a cleanup kind — count + sample, no mutations",
)
async def cleanup_preview(
    body: CleanupPreviewBody = Body(...),
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> CleanupPreviewResponse:
    cfg = _CLEANUP_DEFS.get(body.kind)
    if cfg is None:
        raise HTTPException(status_code=400, detail=f"Unknown cleanup kind: {body.kind}")

    engine = svc._engine  # noqa: SLF001
    try:
        with engine.begin() as conn:
            total = conn.execute(text(cfg["count"])).scalar_one()
            samples = conn.execute(text(cfg["sample"])).fetchall()
    except Exception as exc:  # noqa: BLE001
        # Most likely a missing column/table on older DBs; surface gracefully.
        raise HTTPException(
            status_code=500,
            detail=f"Preview query failed: {exc}",
        ) from exc

    return CleanupPreviewResponse(
        kind=body.kind,
        will_delete_count=int(total or 0),
        sample=[_row_to_dict(r) for r in samples],
        description=cfg["description"],
    )


# ---------------------------------------------------------------------------
# POST /v1/admin/ops/cleanup/execute
# ---------------------------------------------------------------------------


@router.post(
    "/cleanup/execute",
    response_model=CleanupExecuteResponse,
    summary="Execute a cleanup kind — destructive, fresh-TOTP gated",
    dependencies=[Depends(require_fresh_totp())],
)
async def cleanup_execute(
    request: Request,
    body: CleanupExecuteBody = Body(...),
    ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> CleanupExecuteResponse:
    cfg = _CLEANUP_DEFS.get(body.kind)
    if cfg is None:
        raise HTTPException(status_code=400, detail=f"Unknown cleanup kind: {body.kind}")

    engine = svc._engine  # noqa: SLF001
    event_id = log_admin_event(
        engine,
        actor_admin_user_id=ctx.admin_user_id,
        action=f"ops.cleanup.{body.kind}",
        resource_type="cleanup",
        resource_id=body.kind,
        environment=_environment(),
        ip_address=_client_ip(request),
        detail={"confirmed_count": body.confirmed_count},
    )

    try:
        with engine.begin() as conn:
            current = conn.execute(text(cfg["count"])).scalar_one()
            current_count = int(current or 0)
            # 20% drift tolerance — protects against new rows arriving between
            # preview and execute. Tightening to exact match would be too
            # brittle for daily ops on a live env.
            if body.confirmed_count > 0 and current_count > body.confirmed_count * 1.2:
                update_admin_event_status(
                    engine, event_id=event_id, status="failed",
                    error=f"drift: confirmed={body.confirmed_count} actual={current_count}",
                )
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Row count drifted from preview "
                        f"(confirmed={body.confirmed_count}, current={current_count}). "
                        "Re-run preview and confirm again."
                    ),
                )

            deleted = conn.execute(text(cfg["delete"]))

        # Synthetic job_id so the UI has a correlation handle (mirrors what
        # an async job queue would expose). The cleanup itself ran inline —
        # no background task involved — but we still write it as a row in
        # the audit trail for trail consistency.
        job_id = uuid.uuid4().hex
        update_admin_event_status(
            engine, event_id=event_id, status="succeeded",
            result_detail={"deleted_count": int(deleted.rowcount or 0), "job_id": job_id},
        )
        return CleanupExecuteResponse(
            kind=body.kind,
            deleted_count=int(deleted.rowcount or 0),
            job_id=job_id,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        update_admin_event_status(engine, event_id=event_id, status="failed", error=str(exc))
        raise


# ---------------------------------------------------------------------------
# GET /v1/admin/ops/jobs
# ---------------------------------------------------------------------------


@router.get(
    "/jobs",
    response_model=JobListResponse,
    summary="Inspect the background job queue",
)
async def list_jobs(
    status_filter: str | None = Query(None, alias="status"),
    operation: str | None = Query(None),
    tenant_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> JobListResponse:
    where: list[str] = []
    params: dict = {}
    if status_filter:
        where.append("status = :status")
        params["status"] = status_filter
    if operation:
        where.append("operation LIKE :operation")
        params["operation"] = f"%{operation}%"
    if tenant_id:
        where.append("tenant_id = :tenant_id")
        params["tenant_id"] = tenant_id

    where_clause = (" WHERE " + " AND ".join(where)) if where else ""
    offset = (page - 1) * page_size
    params["limit"] = page_size
    params["offset"] = offset

    engine = svc._engine  # noqa: SLF001
    with engine.begin() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM jobs{where_clause}"), params,
        ).scalar_one()
        rows = conn.execute(
            text(
                "SELECT id, tenant_id, project_id, operation, status, attempts, "
                "max_attempts, created_at, started_at, completed_at, error "
                f"FROM jobs{where_clause} ORDER BY created_at DESC "
                "LIMIT :limit OFFSET :offset",
            ),
            params,
        ).fetchall()

    return JobListResponse(
        items=[
            JobSummary(
                id=str(r[0]),
                tenant_id=str(r[1]),
                project_id=str(r[2]),
                operation=str(r[3]),
                status=str(r[4]),
                attempts=int(r[5] or 0),
                max_attempts=int(r[6] or 3),
                created_at=str(r[7]) if r[7] else "",
                started_at=str(r[8]) if r[8] else None,
                completed_at=str(r[9]) if r[9] else None,
                error=str(r[10]) if r[10] else None,
            )
            for r in rows
        ],
        total=int(total or 0),
    )


# ---------------------------------------------------------------------------
# POST /v1/admin/ops/jobs/{id}/retry
# ---------------------------------------------------------------------------


@router.post(
    "/jobs/{job_id}/retry",
    response_model=JobSummary,
    summary="Re-queue a failed/expired job",
)
async def retry_job(
    request: Request,
    job_id: str,
    ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> JobSummary:
    engine = svc._engine  # noqa: SLF001
    event_id = log_admin_event(
        engine,
        actor_admin_user_id=ctx.admin_user_id,
        action="ops.job_retry",
        resource_type="job",
        resource_id=job_id,
        environment=_environment(),
        ip_address=_client_ip(request),
        detail={"job_id": job_id},
    )

    try:
        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT id, status, attempts FROM jobs WHERE id = :id"),
                {"id": job_id},
            ).first()
            if row is None:
                update_admin_event_status(engine, event_id=event_id, status="failed", error="not_found")
                raise HTTPException(status_code=404, detail="Job not found")
            current_status = str(row[1])
            if current_status in {"pending", "running"}:
                update_admin_event_status(
                    engine, event_id=event_id, status="failed",
                    error=f"already_{current_status}",
                )
                raise HTTPException(
                    status_code=409, detail=f"Job already {current_status}",
                )

            # Reset to pending so the next worker tick picks it up. Keep the
            # attempts counter — it's a useful signal that this is a retry.
            conn.execute(
                text(
                    "UPDATE jobs SET status = 'pending', error = NULL, "
                    "started_at = NULL, completed_at = NULL, "
                    "scheduled_at = NULL "
                    "WHERE id = :id",
                ),
                {"id": job_id},
            )

            new_row = conn.execute(
                text(
                    "SELECT id, tenant_id, project_id, operation, status, attempts, "
                    "max_attempts, created_at, started_at, completed_at, error "
                    "FROM jobs WHERE id = :id",
                ),
                {"id": job_id},
            ).first()

        update_admin_event_status(
            engine, event_id=event_id, status="succeeded",
            result_detail={"previous_status": current_status},
        )
        return JobSummary(
            id=str(new_row[0]),
            tenant_id=str(new_row[1]),
            project_id=str(new_row[2]),
            operation=str(new_row[3]),
            status=str(new_row[4]),
            attempts=int(new_row[5] or 0),
            max_attempts=int(new_row[6] or 3),
            created_at=str(new_row[7]) if new_row[7] else "",
            started_at=str(new_row[8]) if new_row[8] else None,
            completed_at=str(new_row[9]) if new_row[9] else None,
            error=str(new_row[10]) if new_row[10] else None,
        )

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        update_admin_event_status(engine, event_id=event_id, status="failed", error=str(exc))
        raise



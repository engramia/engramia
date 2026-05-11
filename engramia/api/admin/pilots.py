# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Admin Dashboard pilot/waitlist approval endpoints.

Phase 1 surface — list pending waitlist requests, approve (provisions
tenant + cloud_user + sends credentials email) or reject (sends polite
decline). Wraps the same business logic as ``engramia waitlist approve``
/ ``engramia waitlist reject`` CLI commands so the audit trail and email
templates are identical between operator paths.
"""

from __future__ import annotations

import logging
import secrets
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

router = APIRouter(prefix="/admin/pilots", tags=["Admin Pilots"])

_VALID_PLANS = {"developer", "pro", "team", "business", "enterprise"}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PilotSummary(BaseModel):
    id: str  # uuid
    # ``str`` not ``EmailStr`` — see UserSummary.email rationale.
    email: str
    name: str
    plan_interest: str
    country: str
    use_case: str | None = None
    company_name: str | None = None
    referral_source: str | None = None
    status: str
    rejection_reason: str | None = None
    tenant_id: str | None = None
    created_at: datetime
    approved_at: datetime | None = None
    rejected_at: datetime | None = None


class PilotListResponse(BaseModel):
    items: list[PilotSummary]
    total: int


class ApproveBody(BaseModel):
    plan: str | None = Field(
        None,
        description=(
            "Override plan_tier. Defaults to the request's plan_interest. "
            "One of: developer | pro | team | business | enterprise"
        ),
    )


class ApprovedResult(BaseModel):
    pilot: PilotSummary
    tenant_id: str
    one_time_password: str
    email_status: Literal["sent", "skipped", "failed"]
    email_detail: str | None = None


class RejectBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class RejectedResult(BaseModel):
    pilot: PilotSummary
    email_status: Literal["sent", "skipped", "failed"]
    email_detail: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _environment() -> str:
    import os as _os
    return _os.environ.get("ENGRAMIA_ENVIRONMENT", "unknown").strip().lower() or "unknown"


def _row_to_pilot(row) -> PilotSummary:
    return PilotSummary(
        id=str(row[0]),
        email=str(row[1]),
        name=str(row[2]),
        plan_interest=str(row[3]),
        country=str(row[4]),
        use_case=str(row[5]) if row[5] else None,
        company_name=str(row[6]) if row[6] else None,
        referral_source=str(row[7]) if row[7] else None,
        status=str(row[8]),
        rejection_reason=str(row[9]) if row[9] else None,
        tenant_id=str(row[10]) if row[10] else None,
        created_at=row[11],
        approved_at=row[12],
        rejected_at=row[13],
    )


_SELECT = (
    "SELECT id, email, name, plan_interest, country, use_case, company_name, "
    "referral_source, status, rejection_reason, tenant_id, created_at, "
    "approved_at, rejected_at FROM waitlist_requests"
)


# ---------------------------------------------------------------------------
# GET /v1/admin/pilots
# ---------------------------------------------------------------------------


@router.get("", response_model=PilotListResponse, summary="List waitlist requests")
async def list_pilots(
    status_filter: str = Query(
        "pending",
        alias="status",
        description="'pending' | 'approved' | 'rejected' | 'all'",
    ),
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> PilotListResponse:
    if status_filter not in {"pending", "approved", "rejected", "all"}:
        raise HTTPException(status_code=400, detail=f"Unknown status: {status_filter}")

    where = "" if status_filter == "all" else " WHERE status = :status"
    params = {} if status_filter == "all" else {"status": status_filter}

    engine = svc._engine  # noqa: SLF001
    with engine.begin() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM waitlist_requests{where}"),
            params,
        ).scalar_one()
        rows = conn.execute(
            text(f"{_SELECT}{where} ORDER BY created_at DESC LIMIT 500"),
            params,
        ).fetchall()

    return PilotListResponse(
        items=[_row_to_pilot(r) for r in rows],
        total=int(total or 0),
    )


# ---------------------------------------------------------------------------
# GET /v1/admin/pilots/{id}
# ---------------------------------------------------------------------------


@router.get("/{pilot_id}", response_model=PilotSummary, summary="Pilot detail")
async def get_pilot(
    pilot_id: str,
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> PilotSummary:
    engine = svc._engine  # noqa: SLF001
    with engine.begin() as conn:
        row = conn.execute(
            text(f"{_SELECT} WHERE id::text = :rid"),
            {"rid": pilot_id},
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Pilot request not found")
    return _row_to_pilot(row)


# ---------------------------------------------------------------------------
# POST /v1/admin/pilots/{id}/approve
# ---------------------------------------------------------------------------


@router.post(
    "/{pilot_id}/approve",
    response_model=ApprovedResult,
    summary="Approve a waitlist request and provision the tenant",
)
async def approve_pilot(
    request: Request,
    pilot_id: str,
    body: ApproveBody = Body(default_factory=ApproveBody),
    ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> ApprovedResult:
    # Lazy imports — heavy modules and email templates only loaded when
    # this endpoint is actually called.
    from engramia.api.cloud_auth import _create_registration, _hash_password

    engine = svc._engine  # noqa: SLF001
    event_id = log_admin_event(
        engine,
        actor_admin_user_id=ctx.admin_user_id,
        action="pilot.approve",
        resource_type="waitlist_request",
        resource_id=pilot_id,
        environment=_environment(),
        ip_address=_client_ip(request),
        detail={"override_plan": body.plan},
    )

    try:
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT id::text, email, name, plan_interest, status "
                    "FROM waitlist_requests WHERE id::text = :rid",
                ),
                {"rid": pilot_id},
            ).first()
            if row is None:
                update_admin_event_status(engine, event_id=event_id, status="failed", error="not_found")
                raise HTTPException(status_code=404, detail="Pilot request not found")
            full_id, email, name, plan_interest, current_status = (
                str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]),
            )
            if current_status != "pending":
                update_admin_event_status(
                    engine, event_id=event_id, status="failed",
                    error=f"already_{current_status}",
                )
                raise HTTPException(
                    status_code=409,
                    detail=f"Pilot request already {current_status}",
                )

        target_plan = (body.plan or plan_interest).lower()
        if target_plan not in _VALID_PLANS:
            update_admin_event_status(engine, event_id=event_id, status="failed", error="bad_plan")
            raise HTTPException(status_code=400, detail=f"Invalid plan: {target_plan}")

        # Mirror engramia waitlist approve CLI flow.
        one_time_password = secrets.token_urlsafe(16)
        password_hash = _hash_password(one_time_password)

        result = _create_registration(
            engine,
            email=email,
            password_hash=password_hash,
            name=name,
            provider="credentials",
            provider_id=None,
            email_verified=True,
            create_api_key=False,
        )

        with engine.begin() as conn:
            if target_plan != "developer":
                conn.execute(
                    text("UPDATE tenants SET plan_tier = :plan WHERE id = :tid"),
                    {"plan": target_plan, "tid": result["tenant_id"]},
                )
            conn.execute(
                text("UPDATE cloud_users SET must_change_password = true WHERE id = :uid"),
                {"uid": result["user_id"]},
            )
            conn.execute(
                text(
                    "UPDATE waitlist_requests SET status='approved', approved_at=now(), "
                    "tenant_id = :tid WHERE id::text = :rid",
                ),
                {"tid": result["tenant_id"], "rid": full_id},
            )

            # Re-read for response
            pilot_row = conn.execute(
                text(f"{_SELECT} WHERE id::text = :rid"),
                {"rid": full_id},
            ).first()

        # Send credentials email. Failures here MUST not fail the approval —
        # tenant is already provisioned. We surface email status separately.
        email_status: Literal["sent", "skipped", "failed"]
        email_detail: str | None = None
        try:
            from engramia.email import EmailNotConfigured, send_email
            from engramia.email.templates import credentials_email
            import os as _os

            dashboard_url = (
                _os.environ.get("ENGRAMIA_DASHBOARD_URL", "https://app.engramia.dev")
                .strip()
                .rstrip("/")
            )
            subj, txt, html = credentials_email(
                recipient_name=name,
                login_email=email,
                one_time_password=one_time_password,
                dashboard_url=dashboard_url,
                plan_tier=target_plan,
            )
            send_email(to=email, subject=subj, html=html, text=txt)
            email_status = "sent"
        except EmailNotConfigured:
            email_status = "skipped"
            email_detail = "SMTP not configured"
        except Exception as exc:  # noqa: BLE001
            email_status = "failed"
            email_detail = str(exc)
            _log.error("Credentials email failed for %s: %s", email, exc)

        update_admin_event_status(
            engine, event_id=event_id, status="succeeded",
            result_detail={
                "tenant_id": result["tenant_id"],
                "user_id": result["user_id"],
                "plan": target_plan,
                "email_status": email_status,
            },
        )
        return ApprovedResult(
            pilot=_row_to_pilot(pilot_row),
            tenant_id=result["tenant_id"],
            one_time_password=one_time_password,
            email_status=email_status,
            email_detail=email_detail,
        )

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        update_admin_event_status(engine, event_id=event_id, status="failed", error=str(exc))
        raise


# ---------------------------------------------------------------------------
# POST /v1/admin/pilots/{id}/reject
# ---------------------------------------------------------------------------


@router.post(
    "/{pilot_id}/reject",
    response_model=RejectedResult,
    summary="Reject a waitlist request and send the customer a polite decline email",
)
async def reject_pilot(
    request: Request,
    pilot_id: str,
    body: RejectBody = Body(...),
    ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> RejectedResult:
    engine = svc._engine  # noqa: SLF001
    event_id = log_admin_event(
        engine,
        actor_admin_user_id=ctx.admin_user_id,
        action="pilot.reject",
        resource_type="waitlist_request",
        resource_id=pilot_id,
        environment=_environment(),
        ip_address=_client_ip(request),
        detail={"reason": body.reason[:200]},
    )

    try:
        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT email, name, status FROM waitlist_requests WHERE id::text = :rid"),
                {"rid": pilot_id},
            ).first()
            if row is None:
                update_admin_event_status(engine, event_id=event_id, status="failed", error="not_found")
                raise HTTPException(status_code=404, detail="Pilot request not found")
            email, name, current_status = str(row[0]), str(row[1]), str(row[2])
            if current_status != "pending":
                update_admin_event_status(
                    engine, event_id=event_id, status="failed",
                    error=f"already_{current_status}",
                )
                raise HTTPException(
                    status_code=409, detail=f"Pilot request already {current_status}",
                )

            conn.execute(
                text(
                    "UPDATE waitlist_requests SET status='rejected', rejected_at=now(), "
                    "rejection_reason = :reason WHERE id::text = :rid",
                ),
                {"reason": body.reason, "rid": pilot_id},
            )
            pilot_row = conn.execute(
                text(f"{_SELECT} WHERE id::text = :rid"),
                {"rid": pilot_id},
            ).first()

        email_status: Literal["sent", "skipped", "failed"]
        email_detail: str | None = None
        try:
            from engramia.email import EmailNotConfigured, send_email
            from engramia.email.templates import rejection_email

            subj, txt, html = rejection_email(
                recipient_name=name, reason=body.reason,
            )
            send_email(to=email, subject=subj, html=html, text=txt)
            email_status = "sent"
        except EmailNotConfigured:
            email_status = "skipped"
            email_detail = "SMTP not configured"
        except Exception as exc:  # noqa: BLE001
            email_status = "failed"
            email_detail = str(exc)
            _log.error("Rejection email failed for %s: %s", email, exc)

        update_admin_event_status(
            engine, event_id=event_id, status="succeeded",
            result_detail={"email_status": email_status},
        )
        return RejectedResult(
            pilot=_row_to_pilot(pilot_row),
            email_status=email_status,
            email_detail=email_detail,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        update_admin_event_status(engine, event_id=event_id, status="failed", error=str(exc))
        raise

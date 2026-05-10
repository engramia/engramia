# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Admin Dashboard billing operations.

Phase 2 surface — read tenant subscription state, override plan
(grant trial extension / comp), change dunning state, retry failed
payments, generate credit notes. All Stripe-touching calls tolerate
Stripe SDK / billing service being unconfigured so the read endpoints
remain usable on env-var auth deployments.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
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

router = APIRouter(prefix="/admin/billing", tags=["Admin Billing"])

_VALID_PLANS = {"sandbox", "developer", "pro", "team", "business", "enterprise"}
_VALID_DUNNING_STATES = {"active", "past_due", "canceled", "paid_offline", "escaped"}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class FailedPayment(BaseModel):
    invoice_id: str
    amount_cents: int
    currency: str
    failed_at: datetime | None = None
    attempts: int
    next_retry_at: datetime | None = None


class TenantBillingState(BaseModel):
    tenant_id: str
    tenant_name: str | None = None
    plan_tier: str
    source: Literal["stripe_subscription", "admin_override", "default"]
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    status: str  # active | past_due | canceled | ...
    billing_interval: str | None = None
    current_period_end: datetime | None = None
    past_due_since: datetime | None = None
    cancel_at_period_end: bool = False
    eval_runs_limit: int | None = None
    patterns_limit: int | None = None
    projects_limit: int | None = None
    failed_payments: list[FailedPayment] = []
    stripe_dashboard_url: str | None = None


class PlanOverrideBody(BaseModel):
    plan: str = Field(description="developer | pro | team | business | enterprise | sandbox")
    reason: str | None = None
    notify_tenant: bool = False


class PlanOverrideResponse(BaseModel):
    tenant_id: str
    previous_plan: str
    new_plan: str


class DunningStateBody(BaseModel):
    state: str = Field(description="active | past_due | canceled | paid_offline | escaped")
    note: str | None = None


class DunningStateResponse(BaseModel):
    tenant_id: str
    previous_state: str | None
    new_state: str


class RetryPaymentBody(BaseModel):
    invoice_id: str


class RetryPaymentResponse(BaseModel):
    invoice_id: str
    status: str
    detail: str | None = None


class CreditNoteBody(BaseModel):
    invoice_id: str = Field(min_length=1)
    amount_cents: int = Field(gt=0)
    reason: str = Field(min_length=3)


class CreditNoteResponse(BaseModel):
    stripe_credit_note_id: str
    invoice_id: str
    amount_cents: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _environment() -> str:
    import os as _os
    return _os.environ.get("ENGRAMIA_ENVIRONMENT", "unknown").strip().lower() or "unknown"


def _stripe_or_none():
    """Return the stripe module with api_key set, or None if not configured."""
    import os as _os

    api_key = _os.environ.get("STRIPE_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import stripe as _stripe

        _stripe.api_key = api_key
        return _stripe
    except ImportError:
        return None


def _stripe_dashboard_url(stripe_customer_id: str | None, env: str) -> str | None:
    if not stripe_customer_id:
        return None
    # Stripe test-mode customers are at /test/, live customers at /
    test_prefix = "test/" if env != "prod" else ""
    return f"https://dashboard.stripe.com/{test_prefix}customers/{stripe_customer_id}"


# ---------------------------------------------------------------------------
# GET /v1/admin/billing/{tenant_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{tenant_id}",
    response_model=TenantBillingState,
    summary="Read tenant billing state (subscription + recent failed payments)",
)
async def get_tenant_billing(
    tenant_id: str,
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> TenantBillingState:
    engine = svc._engine  # noqa: SLF001
    with engine.begin() as conn:
        tenant_row = conn.execute(
            text("SELECT id, name, plan_tier FROM tenants WHERE id = :tid"),
            {"tid": tenant_id},
        ).first()
        if tenant_row is None:
            raise HTTPException(status_code=404, detail="Tenant not found")

        sub_row = conn.execute(
            text(
                "SELECT stripe_customer_id, stripe_subscription_id, plan_tier, "
                "billing_interval, status, eval_runs_limit, patterns_limit, "
                "projects_limit, current_period_end, past_due_since, "
                "cancel_at_period_end "
                "FROM billing_subscriptions WHERE tenant_id = :tid",
            ),
            {"tid": tenant_id},
        ).first()

        # Failed payment attempts in the last 30 days. processed_webhook_events
        # stores raw payloads (per migration 011); rather than parsing JSONB
        # here, we just count the recent invoice.payment_failed events linked
        # to this customer. Best-effort — falls back to empty list if the
        # table or columns aren't present.
        failed_payments: list[FailedPayment] = []
        if sub_row and sub_row[0]:
            try:
                fp_rows = conn.execute(
                    text(
                        "SELECT event_type, payload, created_at FROM processed_webhook_events "
                        "WHERE event_type = 'invoice.payment_failed' "
                        "  AND payload->'data'->'object'->>'customer' = :cid "
                        "ORDER BY created_at DESC LIMIT 10",
                    ),
                    {"cid": sub_row[0]},
                ).fetchall()
                for r in fp_rows:
                    payload = r[1]
                    if isinstance(payload, str):
                        import json as _json
                        try:
                            payload = _json.loads(payload)
                        except _json.JSONDecodeError:
                            payload = {}
                    invoice = (payload or {}).get("data", {}).get("object", {})
                    failed_payments.append(
                        FailedPayment(
                            invoice_id=str(invoice.get("id", "")),
                            amount_cents=int(invoice.get("amount_due", 0) or 0),
                            currency=str(invoice.get("currency", "usd")).upper(),
                            failed_at=r[2],
                            attempts=int(invoice.get("attempt_count", 0) or 0),
                            next_retry_at=None,
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                _log.debug("Failed payments lookup error for tenant=%s: %s", tenant_id, exc)

    plan_from_stripe = sub_row[2] if sub_row else None
    plan_from_tenant = tenant_row[2]
    if sub_row:
        source = "stripe_subscription"
        effective_plan = plan_from_stripe or plan_from_tenant or "free"
    elif plan_from_tenant and plan_from_tenant != "free":
        source = "admin_override"
        effective_plan = plan_from_tenant
    else:
        source = "default"
        effective_plan = "free"

    return TenantBillingState(
        tenant_id=str(tenant_row[0]),
        tenant_name=str(tenant_row[1]) if tenant_row[1] else None,
        plan_tier=str(effective_plan),
        source=source,  # type: ignore[arg-type]
        stripe_customer_id=str(sub_row[0]) if sub_row and sub_row[0] else None,
        stripe_subscription_id=str(sub_row[1]) if sub_row and sub_row[1] else None,
        status=str(sub_row[4]) if sub_row else "active",
        billing_interval=str(sub_row[3]) if sub_row and sub_row[3] else None,
        current_period_end=sub_row[8] if sub_row else None,
        past_due_since=sub_row[9] if sub_row else None,
        cancel_at_period_end=bool(sub_row[10]) if sub_row else False,
        eval_runs_limit=int(sub_row[5]) if sub_row and sub_row[5] is not None else None,
        patterns_limit=int(sub_row[6]) if sub_row and sub_row[6] is not None else None,
        projects_limit=int(sub_row[7]) if sub_row and sub_row[7] is not None else None,
        failed_payments=failed_payments,
        stripe_dashboard_url=_stripe_dashboard_url(
            str(sub_row[0]) if sub_row and sub_row[0] else None,
            _environment(),
        ),
    )


# ---------------------------------------------------------------------------
# PUT /v1/admin/billing/{tenant_id}/plan
# ---------------------------------------------------------------------------


@router.put(
    "/{tenant_id}/plan",
    response_model=PlanOverrideResponse,
    summary="Override tenant plan (admin grant — does not touch Stripe sub)",
    dependencies=[Depends(require_fresh_totp())],
)
async def override_plan(
    request: Request,
    tenant_id: str,
    body: PlanOverrideBody = Body(...),
    ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> PlanOverrideResponse:
    if body.plan not in _VALID_PLANS:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    engine = svc._engine  # noqa: SLF001
    event_id = log_admin_event(
        engine,
        actor_admin_user_id=ctx.admin_user_id,
        action="billing.plan_override",
        resource_type="tenant",
        resource_id=tenant_id,
        environment=_environment(),
        ip_address=_client_ip(request),
        detail={"plan": body.plan, "reason": body.reason},
    )

    try:
        with engine.begin() as conn:
            previous = conn.execute(
                text("SELECT plan_tier FROM tenants WHERE id = :tid"),
                {"tid": tenant_id},
            ).first()
            if previous is None:
                update_admin_event_status(engine, event_id=event_id, status="failed", error="tenant_not_found")
                raise HTTPException(status_code=404, detail="Tenant not found")
            previous_plan = str(previous[0])

            conn.execute(
                text("UPDATE tenants SET plan_tier = :plan WHERE id = :tid"),
                {"plan": body.plan, "tid": tenant_id},
            )

        update_admin_event_status(
            engine, event_id=event_id, status="succeeded",
            result_detail={"previous_plan": previous_plan, "new_plan": body.plan},
        )
        return PlanOverrideResponse(
            tenant_id=tenant_id, previous_plan=previous_plan, new_plan=body.plan,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        update_admin_event_status(engine, event_id=event_id, status="failed", error=str(exc))
        raise


# ---------------------------------------------------------------------------
# PUT /v1/admin/billing/{tenant_id}/dunning
# ---------------------------------------------------------------------------


@router.put(
    "/{tenant_id}/dunning",
    response_model=DunningStateResponse,
    summary="Manually change tenant dunning/subscription state",
    dependencies=[Depends(require_fresh_totp())],
)
async def change_dunning_state(
    request: Request,
    tenant_id: str,
    body: DunningStateBody = Body(...),
    ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> DunningStateResponse:
    if body.state not in _VALID_DUNNING_STATES:
        raise HTTPException(status_code=400, detail=f"Unknown state: {body.state}")

    engine = svc._engine  # noqa: SLF001
    event_id = log_admin_event(
        engine,
        actor_admin_user_id=ctx.admin_user_id,
        action="billing.dunning_change",
        resource_type="tenant",
        resource_id=tenant_id,
        environment=_environment(),
        ip_address=_client_ip(request),
        detail={"state": body.state, "note": body.note},
    )

    try:
        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT status FROM billing_subscriptions WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            ).first()
            if row is None:
                update_admin_event_status(
                    engine, event_id=event_id, status="failed", error="no_subscription_row",
                )
                raise HTTPException(
                    status_code=404,
                    detail="No billing_subscriptions row for this tenant (admin-override plans only).",
                )
            previous_state = str(row[0])

            # When moving back to 'active' or 'paid_offline', clear past_due_since
            past_due_clear = "" if body.state == "past_due" else ", past_due_since = NULL"
            conn.execute(
                text(
                    f"UPDATE billing_subscriptions SET status = :state{past_due_clear}, "
                    "updated_at = NOW() WHERE tenant_id = :tid",
                ),
                {"state": body.state, "tid": tenant_id},
            )

        update_admin_event_status(
            engine, event_id=event_id, status="succeeded",
            result_detail={"previous_state": previous_state, "new_state": body.state},
        )
        return DunningStateResponse(
            tenant_id=tenant_id, previous_state=previous_state, new_state=body.state,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        update_admin_event_status(engine, event_id=event_id, status="failed", error=str(exc))
        raise


# ---------------------------------------------------------------------------
# POST /v1/admin/billing/{tenant_id}/retry
# ---------------------------------------------------------------------------


@router.post(
    "/{tenant_id}/retry",
    response_model=RetryPaymentResponse,
    summary="Trigger Stripe to retry a failed invoice payment",
)
async def retry_payment(
    request: Request,
    tenant_id: str,
    body: RetryPaymentBody = Body(...),
    ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> RetryPaymentResponse:
    stripe = _stripe_or_none()
    if stripe is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured on this environment (STRIPE_API_KEY missing).",
        )

    engine = svc._engine  # noqa: SLF001
    event_id = log_admin_event(
        engine,
        actor_admin_user_id=ctx.admin_user_id,
        action="billing.retry_payment",
        resource_type="invoice",
        resource_id=body.invoice_id,
        environment=_environment(),
        ip_address=_client_ip(request),
        detail={"tenant_id": tenant_id, "invoice_id": body.invoice_id},
    )

    try:
        invoice = stripe.Invoice.pay(body.invoice_id)
        result = RetryPaymentResponse(
            invoice_id=body.invoice_id,
            status=str(invoice.get("status", "unknown")),
            detail=None,
        )
        update_admin_event_status(
            engine, event_id=event_id, status="succeeded",
            result_detail={"stripe_status": result.status},
        )
        return result
    except Exception as exc:  # noqa: BLE001
        update_admin_event_status(engine, event_id=event_id, status="failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Stripe retry failed: {exc}")


# ---------------------------------------------------------------------------
# POST /v1/admin/billing/{tenant_id}/credit-note
# ---------------------------------------------------------------------------


@router.post(
    "/{tenant_id}/credit-note",
    response_model=CreditNoteResponse,
    summary="Issue a Stripe credit note against a paid invoice",
    dependencies=[Depends(require_fresh_totp())],
)
async def issue_credit_note(
    request: Request,
    tenant_id: str,
    body: CreditNoteBody = Body(...),
    ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> CreditNoteResponse:
    stripe = _stripe_or_none()
    if stripe is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured on this environment (STRIPE_API_KEY missing).",
        )

    engine = svc._engine  # noqa: SLF001
    event_id = log_admin_event(
        engine,
        actor_admin_user_id=ctx.admin_user_id,
        action="billing.credit_note",
        resource_type="invoice",
        resource_id=body.invoice_id,
        environment=_environment(),
        ip_address=_client_ip(request),
        detail={
            "tenant_id": tenant_id,
            "invoice_id": body.invoice_id,
            "amount_cents": body.amount_cents,
            "reason": body.reason[:200],
        },
    )

    try:
        cn = stripe.CreditNote.create(
            invoice=body.invoice_id,
            credit_amount=body.amount_cents,
            memo=body.reason,
        )
        update_admin_event_status(
            engine, event_id=event_id, status="succeeded",
            result_detail={"credit_note_id": cn.id},
        )
        return CreditNoteResponse(
            stripe_credit_note_id=str(cn.id),
            invoice_id=body.invoice_id,
            amount_cents=body.amount_cents,
        )
    except Exception as exc:  # noqa: BLE001
        update_admin_event_status(engine, event_id=event_id, status="failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Stripe credit note failed: {exc}")

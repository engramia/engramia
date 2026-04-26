# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Billing router — Stripe webhook + tenant-facing billing endpoints.

The ``/webhook`` endpoint does NOT use ``require_auth`` — Stripe calls it
directly using a shared signing secret (``STRIPE_WEBHOOK_SECRET``).
Authenticity is verified via ``Stripe-Signature`` HMAC-SHA256.

All other endpoints (``/status``, ``/checkout``, ``/portal``, ``/overage``)
require authentication via ``require_auth``.
"""

import logging
import os
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from engramia.api.auth import require_auth

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/billing")


def _allowed_return_netlocs(request: Request) -> set[str]:
    """Hosts permitted as ``return_url`` for the customer portal redirect.

    Always includes the API's own origin (so direct curl/SDK callers work).
    Adds the dashboard origin from ``ENGRAMIA_DASHBOARD_URL`` when set, since
    the dashboard runs on a separate subdomain (e.g. ``app.engramia.dev``)
    from the API (``api.engramia.dev``).
    """
    netlocs = {urlparse(str(request.base_url)).netloc}
    dashboard = os.environ.get("ENGRAMIA_DASHBOARD_URL", "").strip()
    if dashboard:
        dashboard_netloc = urlparse(dashboard).netloc
        if dashboard_netloc:
            netlocs.add(dashboard_netloc)
    return netlocs


@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,  # hide from public Swagger docs
)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="stripe-signature"),
) -> Response:
    """Receive and process Stripe webhook events.

    Verifies the ``Stripe-Signature`` header before dispatching to
    ``BillingService.handle_webhook_event``. Returns 200 for all
    successfully verified events (Stripe retries on non-2xx).
    """
    billing_svc = getattr(request.app.state, "billing_service", None)
    if billing_svc is None:
        # Stripe configured but billing service not initialised — accept
        # the webhook to prevent Stripe from disabling the endpoint.
        _log.warning("stripe_webhook: billing_service not on app.state — ignoring event")
        return Response(content='{"status":"ignored"}', media_type="application/json")

    if not stripe_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe-Signature header.",
        )

    payload = await request.body()
    try:
        event_type = billing_svc.handle_webhook_event(payload, stripe_signature)
    except ValueError as exc:
        # Signature verification failed — do not return 200 (Stripe won't retry)
        _log.warning("stripe_webhook: invalid signature — %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature.",
        ) from exc
    except Exception as exc:
        _log.error("stripe_webhook: unhandled error processing event", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error processing webhook.",
        ) from exc

    _log.info("stripe_webhook: processed event_type=%s", event_type)
    return Response(
        content=f'{{"status":"ok","event_type":"{event_type}"}}',
        media_type="application/json",
    )


@router.get(
    "/status",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_auth)],
)
def billing_status(request: Request) -> Any:
    """Return current plan, usage counters and limits for the authenticated tenant.

    Returns a minimal sandbox response when billing is not configured.
    """
    from engramia.billing.models import BillingStatus

    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required for billing operations",
        )

    billing_svc = getattr(request.app.state, "billing_service", None)
    tenant_id = auth_context.tenant_id

    if billing_svc is None:
        return BillingStatus(
            plan_tier="sandbox",
            status="active",
            billing_interval="month",
            eval_runs_used=0,
            eval_runs_limit=None,
            patterns_used=0,
            patterns_limit=None,
            projects_used=0,
            projects_limit=None,
            period_end=None,
            overage_enabled=False,
            overage_budget_cap_cents=None,
        )

    memory = request.app.state.memory
    pattern_count = memory._storage.count_patterns("patterns/")
    return billing_svc.get_status(tenant_id, pattern_count)


_VALID_PLANS = {"pro", "team"}
_VALID_INTERVALS = {"monthly", "yearly"}


@router.post(
    "/checkout",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_auth)],
)
async def create_checkout(request: Request) -> Any:
    """Create a Stripe Checkout Session and return the redirect URL.

    Expects JSON body::

        {
          "plan": "pro" | "team",
          "interval": "monthly" | "yearly",
          "success_url": "https://app.engramia.dev/setup?checkout=success",
          "cancel_url":  "https://app.engramia.dev/setup?checkout=cancelled",
          "customer_email": "user@example.com"   // optional, pre-fills hosted page
        }

    The actual Stripe price_id is resolved server-side from
    ``STRIPE_PRICE_{PRO,TEAM}_{MONTHLY,YEARLY}`` env vars so the dashboard
    never has to know Stripe identifiers.
    """
    import json

    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required for billing operations",
        )

    billing_svc = getattr(request.app.state, "billing_service", None)
    if billing_svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing not configured.",
        )

    body_bytes = await request.body()
    try:
        body = json.loads(body_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from exc

    tenant_id = auth_context.tenant_id

    plan: str = (body.get("plan") or "").strip().lower()
    interval: str = (body.get("interval") or "").strip().lower()
    success_url: str = body.get("success_url", "")
    cancel_url: str = body.get("cancel_url", "")
    customer_email: str | None = body.get("customer_email") or None

    if plan not in _VALID_PLANS:
        raise HTTPException(
            status_code=400,
            detail=f"plan must be one of {sorted(_VALID_PLANS)}.",
        )
    if interval not in _VALID_INTERVALS:
        raise HTTPException(
            status_code=400,
            detail=f"interval must be one of {sorted(_VALID_INTERVALS)}.",
        )
    if not success_url or not cancel_url:
        raise HTTPException(
            status_code=400, detail="success_url and cancel_url are required."
        )

    try:
        url = billing_svc.create_checkout_url(
            tenant_id=tenant_id,
            plan=plan,
            interval=interval,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=customer_email,
        )
    except ValueError as exc:
        # Unknown (plan, interval) combination — defensive; outer validation
        # should have caught this already, but raise a sane 400 just in case.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        _log.warning(
            "create_checkout_url failed for tenant=%s plan=%s interval=%s: %s",
            tenant_id,
            plan,
            interval,
            exc,
        )
        raise HTTPException(
            status_code=503, detail="Checkout session creation failed."
        ) from exc

    return {"checkout_url": url}


@router.get(
    "/portal",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_auth)],
)
def customer_portal(request: Request, return_url: str = "") -> Any:
    """Return a Stripe Customer Portal URL for the authenticated tenant."""
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required for billing operations",
        )

    billing_svc = getattr(request.app.state, "billing_service", None)
    if billing_svc is None:
        raise HTTPException(status_code=503, detail="Billing not configured.")

    tenant_id = auth_context.tenant_id

    if not return_url:
        return_url = str(request.base_url)
    else:
        parsed = urlparse(return_url)
        if parsed.scheme not in ("http", "https") or parsed.netloc not in _allowed_return_netlocs(request):
            raise HTTPException(status_code=400, detail="Invalid return_url.")

    try:
        url = billing_svc.create_portal_url(tenant_id, return_url)
    except RuntimeError as exc:
        _log.warning("create_portal_url failed for tenant=%s: %s", tenant_id, exc)
        raise HTTPException(status_code=400, detail="Customer portal session creation failed.") from exc

    return {"portal_url": url}


@router.patch(
    "/overage",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_auth)],
)
async def set_overage(request: Request) -> Any:
    """Enable or disable eval_runs overage and optionally set a budget cap.

    Expects JSON body: ``{"enabled": true, "budget_cap_cents": 5000}``
    (``budget_cap_cents`` is optional; null removes the cap).
    """
    import json

    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required for billing operations",
        )

    billing_svc = getattr(request.app.state, "billing_service", None)
    if billing_svc is None:
        raise HTTPException(status_code=503, detail="Billing not configured.")

    tenant_id = auth_context.tenant_id

    payload = await request.body()
    try:
        body = json.loads(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from exc

    enabled: bool = bool(body.get("enabled", False))
    budget_cap_cents: int | None = body.get("budget_cap_cents")

    try:
        billing_svc.set_overage(tenant_id, enabled, budget_cap_cents)
    except ValueError as exc:
        _log.warning("set_overage rejected for tenant=%s: %s", tenant_id, exc)
        raise HTTPException(status_code=400, detail="Invalid overage configuration.") from exc

    return {"overage_enabled": enabled, "budget_cap_cents": budget_cap_cents}

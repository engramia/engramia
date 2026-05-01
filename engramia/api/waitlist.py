# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Public waitlist endpoint for manual cloud onboarding (Variant A).

POST /v1/waitlist/request — anyone can submit; persisted to the
``waitlist_requests`` table; triggers an ack email to the requester and
a notification email to the admin (``support@engramia.dev``). Admin
processes via the ``engramia waitlist`` CLI on the prod VM.

Architecture: ``Ops/internal/cloud-onboarding-architecture.md`` (COMP-002).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator, model_validator

_log = logging.getLogger(__name__)

router = APIRouter(tags=["Waitlist"])

#: Where admin notifications are delivered. Override via env in non-default
#: deploys. Single value — dual-send was rejected per B5 decision.
_ADMIN_NOTIFY_TO_ENV = "ENGRAMIA_WAITLIST_ADMIN_EMAIL"
_ADMIN_NOTIFY_DEFAULT = "support@engramia.dev"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
#: ISO-3166-1 alpha-2 — exactly 2 uppercase letters. We don't validate
#: against the full registry; obvious typos are caught, exotic codes pass.
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")

PlanInterest = Literal["developer", "pro", "team", "business", "enterprise"]


class WaitlistRequestBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    name: str = Field(..., min_length=1, max_length=200)
    plan_interest: PlanInterest
    country: str = Field(..., min_length=2, max_length=2)
    use_case: str | None = Field(default=None, max_length=1000)
    company_name: str | None = Field(default=None, max_length=200)
    referral_source: str | None = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email format.")
        return v

    @field_validator("country")
    @classmethod
    def _validate_country(cls, v: str) -> str:
        v = v.strip().upper()
        if not _COUNTRY_RE.match(v):
            raise ValueError("country must be a 2-letter ISO-3166-1 alpha-2 code (e.g. CZ, DE, US).")
        return v

    @model_validator(mode="after")
    def _use_case_required_for_paid(self) -> WaitlistRequestBody:
        if self.plan_interest != "developer" and (not self.use_case or not self.use_case.strip()):
            raise ValueError("use_case is required when plan_interest is not 'developer'.")
        return self


class WaitlistRequestResponse(BaseModel):
    request_id: str
    status: Literal["pending"] = "pending"
    created_at: str
    next_step: str = "We'll email you within 2 business days."


def _require_engine(request: Request):
    """Same pattern as cloud_auth — pull engine from app.state."""
    engine = getattr(request.app.state, "auth_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Waitlist requires a database-backed deployment.",
        )
    return engine


@router.post(
    "/waitlist/request",
    response_model=WaitlistRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a cloud-access request",
    description=(
        "Public endpoint — anyone can submit. Persists the request to the "
        "waitlist queue and triggers ack + admin-notify emails. The admin "
        "manually approves or rejects via the engramia CLI. See ADR-001 in "
        "the architecture doc for the rationale."
    ),
)
def submit_waitlist_request(
    body: WaitlistRequestBody,
    request: Request,
) -> WaitlistRequestResponse:
    from sqlalchemy import text

    from engramia.email import EmailNotConfigured, send_email
    from engramia.email.templates import waitlist_ack_email, waitlist_admin_notify_email

    engine = _require_engine(request)

    with engine.begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO waitlist_requests "
                "(email, name, plan_interest, country, use_case, "
                " company_name, referral_source) "
                "VALUES (:email, :name, :plan, :country, :uc, :company, :ref) "
                "RETURNING id, created_at"
            ),
            {
                "email": body.email,
                "name": body.name,
                "plan": body.plan_interest,
                "country": body.country,
                "uc": body.use_case,
                "company": body.company_name,
                "ref": body.referral_source,
            },
        ).fetchone()

    if result is None:
        # Defensive — INSERT … RETURNING shouldn't return None on success.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist waitlist request.",
        )
    request_id = str(result[0])
    created_at = result[1].isoformat() if result[1] else ""

    _log.info(
        "waitlist_submitted request_id=%s plan_interest=%s country=%s",
        request_id,
        body.plan_interest,
        body.country,
    )

    # Send emails best-effort. DB row is the source of truth; if either email
    # fails we still return success — admin can re-send the ack later via the
    # CLI, and the row itself surfaces in `engramia waitlist list --pending`.
    admin_email = os.environ.get(_ADMIN_NOTIFY_TO_ENV, _ADMIN_NOTIFY_DEFAULT).strip()

    try:
        ack_subject, ack_text, ack_html = waitlist_ack_email(
            recipient_name=body.name,
            plan_interest=body.plan_interest,
        )
        send_email(to=body.email, subject=ack_subject, html=ack_html, text=ack_text)
    except EmailNotConfigured:
        _log.warning(
            "waitlist_ack_email_not_configured request_id=%s — SMTP not set",
            request_id,
        )
    except Exception as exc:
        _log.warning("waitlist_ack_email_failed request_id=%s: %s", request_id, exc)

    try:
        notify_subject, notify_text, notify_html = waitlist_admin_notify_email(
            request_id=request_id,
            requester_email=body.email,
            requester_name=body.name,
            plan_interest=body.plan_interest,
            country=body.country,
            use_case=body.use_case,
            company_name=body.company_name,
            referral_source=body.referral_source,
        )
        send_email(
            to=admin_email,
            subject=notify_subject,
            html=notify_html,
            text=notify_text,
        )
    except EmailNotConfigured:
        _log.warning(
            "waitlist_admin_notify_not_configured request_id=%s — SMTP not set",
            request_id,
        )
    except Exception as exc:
        _log.warning("waitlist_admin_notify_failed request_id=%s: %s", request_id, exc)

    return WaitlistRequestResponse(
        request_id=request_id,
        status="pending",
        created_at=created_at,
    )

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Billing limit enforcement — raises HTTP 429 when quotas are exceeded.

Replaces the inline ``_check_quota`` helper in routes.py for eval-run
enforcement. Pattern quota enforcement is also centralised here for a
single authoritative source of limit logic.
"""

import datetime
import logging

from fastapi import HTTPException, status

from engramia.billing.models import BillingSubscription, OverageSettings

_log = logging.getLogger(__name__)


class LimitEnforcer:
    """Checks usage counters against plan limits and raises HTTP 429 on breach.

    Args:
        meter: UsageMeter instance for reading current counts.
    """

    def __init__(self, meter) -> None:
        self._meter = meter

    # ------------------------------------------------------------------
    # Eval runs
    # ------------------------------------------------------------------

    def check_eval_runs(
        self,
        tenant_id: str,
        subscription: BillingSubscription,
        overage: OverageSettings | None,
    ) -> None:
        """Raise HTTP 429 if the tenant has exhausted their eval run quota.

        Checks the overage opt-in and budget cap before blocking.

        Args:
            tenant_id: Tenant to check.
            subscription: Current plan subscription for limit values.
            overage: Overage settings for eval_runs, or None.
        """
        _check_subscription_active(subscription)
        limit = subscription.eval_runs_limit
        if limit is None:
            return  # unlimited (enterprise)

        count = self._meter.get_count(tenant_id, "eval_runs")
        if count < limit:
            return  # within quota

        # Quota exhausted — check overage opt-in
        if overage is not None and overage.enabled:
            if overage.budget_cap_cents is not None:
                # Calculate current overage spend
                excess_units = max(0, count - limit) // overage.unit_size
                spend = excess_units * overage.price_per_unit_cents
                if spend < overage.budget_cap_cents:
                    return  # within budget cap — allow the request
                # Budget cap reached
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "overage_budget_cap_reached",
                        "message": "Monthly overage budget cap reached. Increase your cap or upgrade your plan.",
                        "current": count,
                        "limit": limit,
                    },
                )
            return  # overage enabled, no cap — allow

        # No overage — return reset date
        reset_date = _next_period_start()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "quota_exceeded",
                "metric": "eval_runs",
                "current": count,
                "limit": limit,
                "reset_date": reset_date,
                "message": f"Monthly eval run quota reached. Quota resets on {reset_date}.",
            },
        )

    # ------------------------------------------------------------------
    # Patterns (replaces legacy _check_quota in routes.py)
    # ------------------------------------------------------------------

    def check_patterns(
        self,
        current_count: int,
        subscription: BillingSubscription,
    ) -> None:
        """Raise HTTP 429 if the pattern count is at or above the plan limit.

        Args:
            current_count: Current number of stored patterns.
            subscription: Current plan subscription for limit values.
        """
        _check_subscription_active(subscription)
        limit = subscription.patterns_limit
        if limit is None:
            return  # unlimited
        if current_count >= limit:
            reset_date = _next_period_start()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "quota_exceeded",
                    "metric": "patterns",
                    "current": current_count,
                    "limit": limit,
                    "reset_date": reset_date,
                    "message": "Pattern quota reached. Delete old patterns or upgrade your plan.",
                },
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_GRACE_PERIOD_DAYS = 7
_REMINDER_THRESHOLD_DAYS = 5


def _check_subscription_active(subscription: BillingSubscription) -> None:
    """Raise HTTP 402 or 403 if the subscription is not in a usable state.

    past_due with grace period active  → allow (log warning when ≥ day 5)
    past_due after 7-day grace period  → HTTP 402 Payment Required
    canceled                           → HTTP 403 Forbidden
    """
    if subscription.status == "past_due":
        if subscription.past_due_since is not None:
            try:
                since = datetime.datetime.fromisoformat(subscription.past_due_since)
                if since.tzinfo is None:
                    since = since.replace(tzinfo=datetime.UTC)
                delta = datetime.datetime.now(datetime.UTC) - since
                if delta.days < _GRACE_PERIOD_DAYS:
                    days_remaining = _GRACE_PERIOD_DAYS - delta.days
                    if delta.days >= _REMINDER_THRESHOLD_DAYS:
                        # Structured event for day-5+ reminder — hook email here.
                        _log.warning(
                            "DUNNING_EVENT dunning_event=access_expiring_soon tenant=%s days_remaining=%d",
                            subscription.tenant_id,
                            days_remaining,
                            extra={
                                "dunning_event": "access_expiring_soon",
                                "tenant_id": subscription.tenant_id,
                                "days_remaining": days_remaining,
                            },
                        )
                    return  # within grace period — allow the request
            except (ValueError, TypeError):
                # Malformed timestamp: fall through to block access.
                _log.error(
                    "past_due_since parse error for tenant=%s value=%r",
                    subscription.tenant_id,
                    subscription.past_due_since,
                )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "payment_required",
                "message": "Your subscription payment is past due. Update your payment method to continue.",
            },
        )
    if subscription.status == "canceled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "subscription_canceled",
                "message": "Your subscription has been canceled. Subscribe again to continue using Engramia.",
            },
        )


def _next_period_start() -> str:
    """Return ISO-8601 date string for the first day of the next calendar month."""
    now = datetime.datetime.now(datetime.UTC)
    if now.month == 12:
        next_month = datetime.datetime(now.year + 1, 1, 1, tzinfo=datetime.UTC)
    else:
        next_month = datetime.datetime(now.year, now.month + 1, 1, tzinfo=datetime.UTC)
    return next_month.strftime("%Y-%m-%d")

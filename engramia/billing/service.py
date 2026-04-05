# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""BillingService — main facade for all billing operations.

Responsibilities:
- Subscription state (read from local DB, synced via Stripe webhooks)
- Usage metering (eval run counters via UsageMeter)
- Limit enforcement (via LimitEnforcer)
- Overage reporting (at invoice.created webhook)
- Stripe checkout / portal session creation
"""

import datetime
import logging

from sqlalchemy import text

from engramia.billing.enforcement import LimitEnforcer
from engramia.billing.metering import UsageMeter
from engramia.billing.models import (
    METRIC_EVAL_RUNS,
    OVERAGE_CONFIG,
    PLAN_LIMITS,
    BillingStatus,
    BillingSubscription,
    OverageSettings,
)
from engramia.billing.stripe_client import StripeClient

_log = logging.getLogger(__name__)


class BillingService:
    """Billing facade stored on ``app.state.billing_service``.

    All public methods are safe to call when ``engine`` is None — they
    return safe defaults or no-op (dev / JSON-storage mode).

    Args:
        engine: SQLAlchemy engine. None → no-op mode.
        stripe_client: Optional pre-configured StripeClient instance.
            Constructed from env vars when not provided.
    """

    def __init__(self, engine, stripe_client: StripeClient | None = None) -> None:
        self._engine = engine
        self._meter = UsageMeter(engine)
        self._enforcer = LimitEnforcer(self._meter)
        self._stripe = stripe_client or StripeClient()

    # ------------------------------------------------------------------
    # Enforcement (called from route handlers)
    # ------------------------------------------------------------------

    def check_eval_runs(self, tenant_id: str) -> None:
        """Raise HTTP 429 if the tenant's eval run quota is exhausted.

        No-op in dev / JSON-storage mode (no engine configured).
        """
        if self._engine is None:
            return
        sub = self.get_subscription(tenant_id)
        overage = self.get_overage_settings(tenant_id, METRIC_EVAL_RUNS)
        self._enforcer.check_eval_runs(tenant_id, sub, overage)

    def check_patterns(self, tenant_id: str, current_count: int) -> None:
        """Raise HTTP 429 if the tenant's pattern quota is exhausted.

        No-op in dev / JSON-storage mode.
        """
        if self._engine is None:
            return
        sub = self.get_subscription(tenant_id)
        self._enforcer.check_patterns(current_count, sub)

    # ------------------------------------------------------------------
    # Metering (called from route handlers after successful operations)
    # ------------------------------------------------------------------

    def increment_eval_runs(self, tenant_id: str) -> None:
        """Increment the current month's eval run counter for this tenant."""
        self._meter.increment(tenant_id, METRIC_EVAL_RUNS)

    # ------------------------------------------------------------------
    # Subscription state
    # ------------------------------------------------------------------

    def get_subscription(self, tenant_id: str) -> BillingSubscription:
        """Return the current subscription for a tenant.

        If no DB row exists (e.g. new tenant, or no engine), returns a
        default sandbox subscription without touching the DB.
        """
        if self._engine is None:
            return BillingSubscription.sandbox_default(tenant_id)
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT stripe_customer_id, stripe_subscription_id, plan_tier, "
                        "billing_interval, status, eval_runs_limit, patterns_limit, "
                        "projects_limit, current_period_end, past_due_since "
                        "FROM billing_subscriptions WHERE tenant_id = :tid"
                    ),
                    {"tid": tenant_id},
                ).fetchone()
        except Exception as exc:
            _log.warning("BillingService.get_subscription DB error for tenant=%s", tenant_id, exc_info=True)
            return BillingSubscription.sandbox_default(tenant_id)

        if row is None:
            return BillingSubscription.sandbox_default(tenant_id)
        return BillingSubscription(
            tenant_id=tenant_id,
            stripe_customer_id=row[0],
            stripe_subscription_id=row[1],
            plan_tier=row[2] or "sandbox",
            billing_interval=row[3] or "month",
            status=row[4] or "active",
            eval_runs_limit=row[5],
            patterns_limit=row[6],
            projects_limit=row[7],
            current_period_end=row[8],
            past_due_since=row[9],
        )

    def get_overage_settings(self, tenant_id: str, metric: str) -> OverageSettings | None:
        """Return overage opt-in settings for a tenant/metric, or None if not configured."""
        if self._engine is None:
            return None
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT enabled, price_per_unit_cents, unit_size, budget_cap_cents "
                        "FROM overage_settings WHERE tenant_id = :tid AND metric = :metric"
                    ),
                    {"tid": tenant_id, "metric": metric},
                ).fetchone()
        except Exception as exc:
            _log.warning("BillingService.get_overage_settings DB error", exc_info=True)
            return None
        if row is None:
            return None
        return OverageSettings(
            tenant_id=tenant_id,
            metric=metric,
            enabled=bool(row[0]),
            price_per_unit_cents=row[1],
            unit_size=row[2],
            budget_cap_cents=row[3],
        )

    # ------------------------------------------------------------------
    # Status (GET /v1/billing/status)
    # ------------------------------------------------------------------

    def get_status(self, tenant_id: str, current_pattern_count: int = 0) -> BillingStatus:
        """Return current usage + plan limits for the dashboard/API."""
        sub = self.get_subscription(tenant_id)
        overage = self.get_overage_settings(tenant_id, METRIC_EVAL_RUNS)
        eval_used = self._meter.get_count(tenant_id, METRIC_EVAL_RUNS)

        # Project count: number of projects for this tenant in the DB
        projects_used = self._count_projects(tenant_id)

        return BillingStatus(
            plan_tier=sub.plan_tier,
            status=sub.status,
            billing_interval=sub.billing_interval,
            eval_runs_used=eval_used,
            eval_runs_limit=sub.eval_runs_limit,
            patterns_used=current_pattern_count,
            patterns_limit=sub.patterns_limit,
            projects_used=projects_used,
            projects_limit=sub.projects_limit,
            period_end=sub.current_period_end,
            overage_enabled=overage.enabled if overage else False,
            overage_budget_cap_cents=overage.budget_cap_cents if overage else None,
        )

    # ------------------------------------------------------------------
    # Checkout / portal
    # ------------------------------------------------------------------

    def create_checkout_url(
        self,
        tenant_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        """Create a Stripe Checkout Session and return the URL.

        Raises ``RuntimeError`` if Stripe is not configured.
        """
        sub = self.get_subscription(tenant_id)
        return self._stripe.create_checkout_session(
            customer_id=sub.stripe_customer_id,
            price_id=price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"tenant_id": tenant_id},
        )

    def create_portal_url(self, tenant_id: str, return_url: str) -> str:
        """Create a Stripe Customer Portal session URL.

        Raises ``RuntimeError`` if Stripe is not configured or the tenant
        has no Stripe customer ID (has never subscribed).
        """
        sub = self.get_subscription(tenant_id)
        if not sub.stripe_customer_id:
            raise RuntimeError("Tenant has no Stripe customer — subscribe first.")
        return self._stripe.create_customer_portal_session(sub.stripe_customer_id, return_url)

    # ------------------------------------------------------------------
    # Tenant provisioning
    # ------------------------------------------------------------------

    def create_stripe_customer(self, tenant_id: str, email: str | None = None) -> str | None:
        """Create a Stripe Customer for a new tenant and persist the customer ID.

        Call this during tenant provisioning (bootstrap / signup) so the
        stripe_customer_id → tenant_id mapping is in the DB before the first
        Checkout session.  Without this, ``_upsert_subscription`` falls back to
        reading tenant_id from Checkout metadata, which fails if the subscription
        was created outside a Checkout flow.

        Returns the Stripe customer ID, or None when Stripe is not configured
        (STRIPE_SECRET_KEY not set / SDK not installed — dev/test mode).
        """
        try:
            customer_id = self._stripe.create_customer(tenant_id=tenant_id, email=email)
        except RuntimeError:
            _log.debug(
                "create_stripe_customer: Stripe not configured — skipping for tenant=%s",
                tenant_id,
            )
            return None
        if self._engine is None:
            return customer_id
        try:
            limits = PLAN_LIMITS["sandbox"]
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO billing_subscriptions "
                        "(id, tenant_id, stripe_customer_id, plan_tier, billing_interval, status, "
                        "eval_runs_limit, patterns_limit, projects_limit) "
                        "VALUES (gen_random_uuid()::text, :tid, :cid, 'sandbox', 'month', 'active', "
                        ":eval_lim, :pat_lim, :proj_lim) "
                        "ON CONFLICT (tenant_id) DO UPDATE SET stripe_customer_id = :cid"
                    ),
                    {
                        "tid": tenant_id,
                        "cid": customer_id,
                        "eval_lim": limits["eval_runs"],
                        "pat_lim": limits["patterns"],
                        "proj_lim": limits["projects"],
                    },
                )
        except Exception:
            _log.error(
                "create_stripe_customer: DB error persisting customer ID for tenant=%s",
                tenant_id,
                exc_info=True,
            )
        return customer_id

    # ------------------------------------------------------------------
    # Overage settings update (PATCH /v1/billing/overage)
    # ------------------------------------------------------------------

    def set_overage(
        self,
        tenant_id: str,
        enabled: bool,
        budget_cap_cents: int | None,
    ) -> None:
        """Enable/disable eval_runs overage and set budget cap.

        Upserts the overage_settings row for this tenant's eval_runs metric.
        Uses plan-default overage pricing.
        """
        if self._engine is None:
            return
        sub = self.get_subscription(tenant_id)
        tier_config = OVERAGE_CONFIG.get(sub.plan_tier, {}).get(METRIC_EVAL_RUNS)
        if tier_config is None:
            raise ValueError(f"Overage is not available for plan tier '{sub.plan_tier}'.")

        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO overage_settings "
                        "(id, tenant_id, metric, enabled, price_per_unit_cents, unit_size, budget_cap_cents) "
                        "VALUES (gen_random_uuid()::text, :tid, :metric, :enabled, :price, :unit, :cap) "
                        "ON CONFLICT (tenant_id, metric) "
                        "DO UPDATE SET enabled = :enabled, budget_cap_cents = :cap"
                    ),
                    {
                        "tid": tenant_id,
                        "metric": METRIC_EVAL_RUNS,
                        "enabled": enabled,
                        "price": tier_config["price_per_unit_cents"],
                        "unit": tier_config["unit_size"],
                        "cap": budget_cap_cents,
                    },
                )
        except Exception as exc:
            _log.error("BillingService.set_overage DB error for tenant=%s", tenant_id, exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Stripe webhook event dispatch
    # ------------------------------------------------------------------

    def handle_webhook_event(self, payload: bytes, sig_header: str) -> str:
        """Verify and process a Stripe webhook event.

        Returns the event type string on success.
        Raises ``ValueError`` on invalid signature.
        Skips duplicate events (Stripe delivers at-least-once).
        """
        event = self._stripe.construct_webhook_event(payload, sig_header)
        event_id: str = event["id"]
        event_type: str = event["type"]

        if self._is_event_processed(event_id):
            _log.info("stripe_webhook: duplicate event skipped event_id=%s type=%s", event_id, event_type)
            return event_type

        data = event["data"]["object"]

        if event_type in ("customer.subscription.created", "customer.subscription.updated"):
            self._upsert_subscription(data)
        elif event_type == "customer.subscription.deleted":
            self._downgrade_to_sandbox(data["customer"])
        elif event_type == "invoice.payment_failed":
            customer_id = data["customer"]
            self._set_status_by_customer(customer_id, "past_due")
            # Structured dunning event — hook an email provider here or call
            # from a daily job to send day-0 / day-5 notifications.
            attempt = data.get("attempt_count", 1)
            _log.warning(
                "DUNNING_EVENT dunning_event=payment_failed customer=%s attempt=%d "
                "grace_period_days=7 action=notify_customer_payment_failed",
                customer_id,
                attempt,
                extra={
                    "dunning_event": "payment_failed",
                    "customer_id": customer_id,
                    "attempt_count": attempt,
                    "grace_period_days": 7,
                },
            )
        elif event_type == "invoice.paid":
            self._set_status_by_customer(data["customer"], "active")
        elif event_type == "invoice.created":
            # Report overage before Stripe finalises the invoice
            customer_id = data.get("customer")
            if customer_id:
                self._report_overage_for_customer(customer_id)
        else:
            _log.debug("Unhandled Stripe event: %s", event_type)

        self._mark_event_processed(event_id, event_type)
        return event_type

    # ------------------------------------------------------------------
    # Internal webhook helpers
    # ------------------------------------------------------------------

    def _upsert_subscription(self, sub_data: dict) -> None:
        """Insert or update a billing_subscriptions row from Stripe subscription data."""
        if self._engine is None:
            return
        customer_id: str = sub_data["customer"]
        sub_id: str = sub_data["id"]
        status: str = sub_data["status"]
        interval: str = sub_data["items"]["data"][0]["plan"]["interval"]
        period_end: str = datetime.datetime.fromtimestamp(
            sub_data["current_period_end"], tz=datetime.UTC
        ).isoformat()

        # Resolve plan tier from Stripe metadata (set during checkout)
        plan_tier: str = sub_data.get("metadata", {}).get("plan_tier", "pro")
        limits = PLAN_LIMITS.get(plan_tier, PLAN_LIMITS["sandbox"])

        tenant_id = self._tenant_id_by_customer(customer_id)
        if not tenant_id:
            # Fallback: read tenant_id from subscription metadata written at
            # Checkout. Handles the first-ever subscribe when no
            # billing_subscriptions row exists yet (customer created by Stripe
            # on-the-fly, before create_stripe_customer() was called).
            tenant_id = sub_data.get("metadata", {}).get("tenant_id")
        if not tenant_id:
            _log.warning("_upsert_subscription: no tenant for customer=%s", customer_id)
            return

        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO billing_subscriptions "
                        "(id, tenant_id, stripe_customer_id, stripe_subscription_id, "
                        "plan_tier, billing_interval, status, "
                        "eval_runs_limit, patterns_limit, projects_limit, "
                        "current_period_end) "
                        "VALUES (gen_random_uuid()::text, :tid, :cid, :sid, "
                        ":tier, :interval, :status, "
                        ":eval_lim, :pat_lim, :proj_lim, :period_end) "
                        "ON CONFLICT (tenant_id) DO UPDATE SET "
                        "stripe_subscription_id = :sid, plan_tier = :tier, "
                        "billing_interval = :interval, status = :status, "
                        "eval_runs_limit = :eval_lim, patterns_limit = :pat_lim, "
                        "projects_limit = :proj_lim, current_period_end = :period_end, "
                        "updated_at = NOW()"
                    ),
                    {
                        "tid": tenant_id,
                        "cid": customer_id,
                        "sid": sub_id,
                        "tier": plan_tier,
                        "interval": interval,
                        "status": status,
                        "eval_lim": limits["eval_runs"],
                        "pat_lim": limits["patterns"],
                        "proj_lim": limits["projects"],
                        "period_end": period_end,
                    },
                )
        except Exception as exc:
            _log.error("_upsert_subscription DB error", exc_info=True)

    def _downgrade_to_sandbox(self, customer_id: str) -> None:
        """Downgrade a cancelled subscription to sandbox tier."""
        if self._engine is None:
            return
        limits = PLAN_LIMITS["sandbox"]
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE billing_subscriptions SET "
                        "plan_tier = 'sandbox', status = 'canceled', "
                        "eval_runs_limit = :eval_lim, patterns_limit = :pat_lim, "
                        "projects_limit = :proj_lim, updated_at = NOW() "
                        "WHERE stripe_customer_id = :cid"
                    ),
                    {
                        "cid": customer_id,
                        "eval_lim": limits["eval_runs"],
                        "pat_lim": limits["patterns"],
                        "proj_lim": limits["projects"],
                    },
                )
        except Exception as exc:
            _log.error("_downgrade_to_sandbox DB error", exc_info=True)

    def _set_status_by_customer(self, customer_id: str, status: str) -> None:
        if self._engine is None:
            return
        try:
            with self._engine.begin() as conn:
                if status == "past_due":
                    # Record the first payment failure timestamp.
                    # CASE preserves the existing timestamp on subsequent
                    # invoice.payment_failed events (Stripe Smart Retries) so
                    # the 7-day grace period clock does not reset on each retry.
                    now_iso = datetime.datetime.now(datetime.UTC).isoformat()
                    conn.execute(
                        text(
                            "UPDATE billing_subscriptions "
                            "SET status = :status, "
                            "past_due_since = CASE WHEN past_due_since IS NULL "
                            "                      THEN :now ELSE past_due_since END, "
                            "updated_at = NOW() "
                            "WHERE stripe_customer_id = :cid"
                        ),
                        {"cid": customer_id, "status": status, "now": now_iso},
                    )
                elif status == "active":
                    # Payment succeeded — clear the dunning clock.
                    conn.execute(
                        text(
                            "UPDATE billing_subscriptions "
                            "SET status = :status, past_due_since = NULL, updated_at = NOW() "
                            "WHERE stripe_customer_id = :cid"
                        ),
                        {"cid": customer_id, "status": status},
                    )
                else:
                    conn.execute(
                        text(
                            "UPDATE billing_subscriptions SET status = :status, updated_at = NOW() "
                            "WHERE stripe_customer_id = :cid"
                        ),
                        {"cid": customer_id, "status": status},
                    )
        except Exception as exc:
            _log.error("_set_status_by_customer DB error", exc_info=True)

    def _report_overage_for_customer(self, customer_id: str) -> None:
        """Create Stripe invoice items for any overage in the closing period."""
        if self._engine is None:
            return
        tenant_id = self._tenant_id_by_customer(customer_id)
        if not tenant_id:
            return
        sub = self.get_subscription(tenant_id)
        if sub.eval_runs_limit is None:
            return  # unlimited
        overage = self.get_overage_settings(tenant_id, METRIC_EVAL_RUNS)
        if overage is None or not overage.enabled:
            return

        excess = self._meter.get_overage_units(tenant_id, METRIC_EVAL_RUNS, sub.eval_runs_limit)
        if excess == 0:
            return

        units = excess // overage.unit_size
        if units == 0:
            return

        amount = units * overage.price_per_unit_cents
        if overage.budget_cap_cents is not None:
            amount = min(amount, overage.budget_cap_cents)

        description = (
            f"Engramia overage: {excess} eval runs "
            f"({units} × {overage.unit_size} run blocks)"
        )
        try:
            self._stripe.create_invoice_item(
                customer_id=customer_id,
                amount_cents=amount,
                description=description,
                subscription_id=sub.stripe_subscription_id,
            )
        except Exception as exc:
            _log.error("_report_overage_for_customer Stripe error", exc_info=True)

    def _tenant_id_by_customer(self, customer_id: str) -> str | None:
        """Look up tenant_id by Stripe customer ID."""
        if self._engine is None:
            return None
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT tenant_id FROM billing_subscriptions "
                        "WHERE stripe_customer_id = :cid"
                    ),
                    {"cid": customer_id},
                ).fetchone()
            return row[0] if row else None
        except Exception as exc:
            _log.warning("_tenant_id_by_customer DB error", exc_info=True)
            return None

    def _count_projects(self, tenant_id: str) -> int:
        """Count non-deleted projects for a tenant."""
        if self._engine is None:
            return 0
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM projects "
                        "WHERE tenant_id = :tid AND deleted_at IS NULL"
                    ),
                    {"tid": tenant_id},
                ).fetchone()
            return row[0] if row else 0
        except Exception as exc:
            _log.warning("_count_projects DB error for tenant=%s", tenant_id, exc_info=True)
            return 0

    # ------------------------------------------------------------------
    # Webhook idempotency
    # ------------------------------------------------------------------

    def _is_event_processed(self, stripe_event_id: str) -> bool:
        """Return True if this Stripe event ID was already processed."""
        if self._engine is None:
            return False
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT 1 FROM processed_webhook_events "
                        "WHERE stripe_event_id = :eid"
                    ),
                    {"eid": stripe_event_id},
                ).fetchone()
            return row is not None
        except Exception:
            # On DB error, allow processing to proceed (better to process twice
            # than to silently drop a billing event).
            _log.warning("_is_event_processed DB error for event_id=%s", stripe_event_id, exc_info=True)
            return False

    def _mark_event_processed(self, stripe_event_id: str, event_type: str) -> None:
        """Record a Stripe event ID as successfully processed."""
        if self._engine is None:
            return
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO processed_webhook_events "
                        "(stripe_event_id, event_type) "
                        "VALUES (:eid, :etype) "
                        "ON CONFLICT (stripe_event_id) DO NOTHING"
                    ),
                    {"eid": stripe_event_id, "etype": event_type},
                )
        except Exception:
            _log.warning("_mark_event_processed DB error for event_id=%s", stripe_event_id, exc_info=True)

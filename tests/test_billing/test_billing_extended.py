# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""P1 — T-04: Billing service extended tests.

Covers areas not reached by the existing test_service.py / test_enforcement.py /
test_webhooks_api_extended.py suite:

1. Webhook idempotency helpers
   - _is_event_processed(): no engine, row present, row absent, DB error.
   - _mark_event_processed(): no engine, successful write, DB error (no raise).
   - handle_webhook_event(): duplicate event is silently skipped (no side-effects).

2. _report_overage_for_customer() happy paths
   - Overage exists → stripe.create_invoice_item called with correct amount.
   - Budget cap applied → amount capped at budget_cap_cents.
   - Fractional unit (< unit_size) → zero units → Stripe NOT called.
   - Overage disabled → Stripe NOT called.
   - Overage settings absent (None) → Stripe NOT called.
   - Stripe API error is logged and swallowed (no raise).

3. UsageMeter.increment() DB success path (missing from test_webhooks_api_extended.py)
   - With engine, DB returns new count → increment() returns that count.
   - Explicit period (year/month) passed to SQL via get_count().
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import sqlalchemy.exc

from engramia.billing.models import (
    METRIC_EVAL_RUNS,
    BillingSubscription,
    OverageSettings,
)
from engramia.billing.metering import UsageMeter
from engramia.billing.service import BillingService

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers (mirror test_service.py for consistency)
# ---------------------------------------------------------------------------


def _engine_with_row(*rows):
    """Return a MagicMock engine whose fetchone() returns rows in sequence."""
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = lambda s: conn
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value.fetchone.side_effect = list(rows)
    return engine, conn


def _engine_begin():
    """Return a MagicMock engine where begin() context manager works."""
    engine = MagicMock()
    conn = MagicMock()
    engine.begin.return_value.__enter__ = lambda s: conn
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    return engine, conn


def _billing_service(engine=None, stripe_client=None) -> BillingService:
    stripe = stripe_client or MagicMock()
    return BillingService(engine=engine, stripe_client=stripe)


def _active_sub(
    tenant_id: str = "t1",
    customer_id: str = "cus_abc",
    sub_id: str = "sub_xyz",
    plan_tier: str = "pro",
    eval_runs_limit: int | None = 500,
) -> BillingSubscription:
    return BillingSubscription(
        tenant_id=tenant_id,
        stripe_customer_id=customer_id,
        stripe_subscription_id=sub_id,
        plan_tier=plan_tier,
        billing_interval="month",
        status="active",
        eval_runs_limit=eval_runs_limit,
        patterns_limit=50_000,
        projects_limit=3,
    )


def _overage_settings(
    enabled: bool = True,
    price_per_unit_cents: int = 500,
    unit_size: int = 500,
    budget_cap_cents: int | None = None,
) -> OverageSettings:
    return OverageSettings(
        tenant_id="t1",
        metric=METRIC_EVAL_RUNS,
        enabled=enabled,
        price_per_unit_cents=price_per_unit_cents,
        unit_size=unit_size,
        budget_cap_cents=budget_cap_cents,
    )


# ---------------------------------------------------------------------------
# T-04a: Webhook idempotency — _is_event_processed()
# ---------------------------------------------------------------------------


class TestIsEventProcessed:
    """_is_event_processed() checks the processed_webhook_events table."""

    def test_no_engine_returns_false(self):
        """No engine (dev mode) → always report unprocessed (allow processing)."""
        svc = _billing_service(engine=None)
        assert svc._is_event_processed("evt_001") is False

    def test_row_found_returns_true(self):
        """If the event ID is in the table, return True (skip reprocessing)."""
        engine, _ = _engine_with_row((1,))  # row exists
        svc = _billing_service(engine=engine)
        assert svc._is_event_processed("evt_dup") is True

    def test_no_row_returns_false(self):
        """If the event ID is absent, return False (allow processing)."""
        engine, _ = _engine_with_row(None)  # no row
        svc = _billing_service(engine=engine)
        assert svc._is_event_processed("evt_new") is False

    def test_db_error_returns_false_to_allow_processing(self):
        """On DB error, return False — better to process twice than drop a billing event."""
        engine = MagicMock()
        engine.connect.side_effect = sqlalchemy.exc.OperationalError("stmt", {}, Exception("DB unavailable"))
        svc = _billing_service(engine=engine)
        assert svc._is_event_processed("evt_err") is False

    def test_passes_event_id_to_query(self):
        """The event ID must be forwarded as a query parameter."""
        engine, conn = _engine_with_row(None)
        svc = _billing_service(engine=engine)
        svc._is_event_processed("evt_specific")
        params = conn.execute.call_args[0][1]
        assert params["eid"] == "evt_specific"


# ---------------------------------------------------------------------------
# T-04b: Webhook idempotency — _mark_event_processed()
# ---------------------------------------------------------------------------


class TestMarkEventProcessed:
    """_mark_event_processed() inserts a row so future calls can detect duplicates."""

    def test_no_engine_is_noop(self):
        svc = _billing_service(engine=None)
        svc._mark_event_processed("evt_001", "invoice.paid")  # must not raise

    def test_writes_event_id_and_type_to_db(self):
        engine, conn = _engine_begin()
        svc = _billing_service(engine=engine)
        svc._mark_event_processed("evt_abc", "customer.subscription.created")
        conn.execute.assert_called_once()
        params = conn.execute.call_args[0][1]
        assert params["eid"] == "evt_abc"
        assert params["etype"] == "customer.subscription.created"

    def test_db_error_does_not_raise(self):
        """A DB failure must be swallowed (logged), not propagated."""
        engine = MagicMock()
        engine.begin.side_effect = sqlalchemy.exc.OperationalError("stmt", {}, Exception("DB down"))
        svc = _billing_service(engine=engine)
        svc._mark_event_processed("evt_err", "invoice.paid")  # must not raise

    def test_sql_uses_on_conflict_do_nothing(self):
        """INSERT must use ON CONFLICT DO NOTHING to tolerate concurrent duplicate writes."""
        engine, conn = _engine_begin()
        svc = _billing_service(engine=engine)
        svc._mark_event_processed("evt_x", "some.event")
        sql = conn.execute.call_args[0][0].text
        assert "ON CONFLICT" in sql
        assert "DO NOTHING" in sql


# ---------------------------------------------------------------------------
# T-04c: Duplicate event detection in handle_webhook_event()
# ---------------------------------------------------------------------------


class TestHandleWebhookDuplication:
    """handle_webhook_event() skips side-effects for already-processed events."""

    def _make_svc_with_event(self, event_type: str, data: dict | None = None, event_id: str = "evt_dup_001"):
        stripe = MagicMock()
        event = {"id": event_id, "type": event_type, "data": {"object": data or {}}}
        stripe.construct_webhook_event.return_value = event
        svc = _billing_service(engine=MagicMock(), stripe_client=stripe)
        return svc

    def test_duplicate_event_returns_event_type_without_processing(self):
        """A duplicate event must be silently skipped — event_type still returned."""
        svc = self._make_svc_with_event("invoice.paid", {"customer": "cus_x"})
        with (
            patch.object(svc, "_is_event_processed", return_value=True),
            patch.object(svc, "_set_status_by_customer") as mock_status,
            patch.object(svc, "_mark_event_processed") as mock_mark,
        ):
            result = svc.handle_webhook_event(b"{}", "sig")

        assert result == "invoice.paid"
        mock_status.assert_not_called()  # No processing for duplicates
        mock_mark.assert_not_called()  # Idempotency record not re-written

    def test_fresh_event_processes_and_marks(self):
        """A new event (not yet processed) must be handled and then marked."""
        svc = self._make_svc_with_event("invoice.paid", {"customer": "cus_x"}, event_id="evt_fresh")
        with (
            patch.object(svc, "_is_event_processed", return_value=False),
            patch.object(svc, "_set_status_by_customer"),
            patch.object(svc, "_mark_event_processed") as mock_mark,
        ):
            svc.handle_webhook_event(b"{}", "sig")

        mock_mark.assert_called_once_with("evt_fresh", "invoice.paid")

    def test_duplicate_subscription_created_does_not_upsert(self):
        """A duplicate customer.subscription.created event must not call _upsert_subscription."""
        data = {
            "customer": "cus_x",
            "id": "sub_x",
            "status": "active",
            "items": {"data": [{"plan": {"interval": "month"}}]},
            "current_period_end": 1900000000,
            "metadata": {"plan_tier": "pro"},
        }
        svc = self._make_svc_with_event("customer.subscription.created", data)
        with (
            patch.object(svc, "_is_event_processed", return_value=True),
            patch.object(svc, "_upsert_subscription") as mock_upsert,
        ):
            svc.handle_webhook_event(b"{}", "sig")

        mock_upsert.assert_not_called()


# ---------------------------------------------------------------------------
# T-04d: _report_overage_for_customer() — happy paths and edge cases
# ---------------------------------------------------------------------------


_UNSET = object()  # sentinel — distinguishes "use default" from "explicitly None"


class TestReportOverageHappyPath:
    """Full path through _report_overage_for_customer() — Stripe invoice items."""

    def _svc_with_patches(
        self,
        tenant_id: str = "t1",
        sub: BillingSubscription | None = None,
        overage=_UNSET,
        excess_units: int = 1000,
        stripe: MagicMock | None = None,
    ):
        """Build a BillingService with engine + patched helpers.

        Pass ``overage=None`` to simulate "no overage settings" (tenant opted out).
        Omit ``overage`` to use the default enabled OverageSettings.
        """
        if stripe is None:
            stripe = MagicMock()
        svc = _billing_service(engine=MagicMock(), stripe_client=stripe)

        if sub is None:
            sub = _active_sub(eval_runs_limit=500)
        if overage is _UNSET:
            overage = _overage_settings()

        patches = [
            patch.object(svc, "_tenant_id_by_customer", return_value=tenant_id),
            patch.object(svc, "get_subscription", return_value=sub),
            patch.object(svc, "get_overage_settings", return_value=overage),
            patch.object(svc._meter, "get_overage_units", return_value=excess_units),
        ]
        return svc, stripe, patches

    def test_overage_calls_stripe_create_invoice_item(self):
        """1000 excess / 500 unit_size = 2 units → 2 * 500 = 1000 cents charged."""
        svc, stripe, patches = self._svc_with_patches(excess_units=1000)
        with patches[0], patches[1], patches[2], patches[3]:
            svc._report_overage_for_customer("cus_abc")

        stripe.create_invoice_item.assert_called_once()
        kwargs = stripe.create_invoice_item.call_args[1]
        assert kwargs["customer_id"] == "cus_abc"
        assert kwargs["amount_cents"] == 1000  # 2 units × $5

    def test_overage_passes_subscription_id_to_stripe(self):
        """stripe_subscription_id from the subscription must be forwarded."""
        svc, stripe, patches = self._svc_with_patches(excess_units=500)
        with patches[0], patches[1], patches[2], patches[3]:
            svc._report_overage_for_customer("cus_abc")

        kwargs = stripe.create_invoice_item.call_args[1]
        assert kwargs["subscription_id"] == "sub_xyz"

    def test_budget_cap_limits_charged_amount(self):
        """When budget_cap_cents < calculated overage, the cap is charged instead."""
        overage = _overage_settings(
            price_per_unit_cents=500,
            unit_size=500,
            budget_cap_cents=800,  # cap is 800, but 2 units = 1000 cents
        )
        svc, stripe, patches = self._svc_with_patches(overage=overage, excess_units=1000)
        with patches[0], patches[1], patches[2], patches[3]:
            svc._report_overage_for_customer("cus_abc")

        kwargs = stripe.create_invoice_item.call_args[1]
        assert kwargs["amount_cents"] == 800  # capped

    def test_fractional_unit_below_threshold_skips_stripe(self):
        """excess=499 with unit_size=500 → 0 complete units → Stripe NOT called."""
        svc, stripe, patches = self._svc_with_patches(excess_units=499)
        with patches[0], patches[1], patches[2], patches[3]:
            svc._report_overage_for_customer("cus_abc")

        stripe.create_invoice_item.assert_not_called()

    def test_zero_excess_skips_stripe(self):
        """No excess at all → Stripe NOT called."""
        svc, stripe, patches = self._svc_with_patches(excess_units=0)
        with patches[0], patches[1], patches[2], patches[3]:
            svc._report_overage_for_customer("cus_abc")

        stripe.create_invoice_item.assert_not_called()

    def test_overage_disabled_skips_stripe(self):
        """Overage opt-in is disabled → Stripe NOT called even if there is excess."""
        overage = _overage_settings(enabled=False)
        svc, stripe, patches = self._svc_with_patches(overage=overage, excess_units=1000)
        with patches[0], patches[1], patches[2], patches[3]:
            svc._report_overage_for_customer("cus_abc")

        stripe.create_invoice_item.assert_not_called()

    def test_no_overage_settings_skips_stripe(self):
        """None overage settings (tenant opted out) → Stripe NOT called."""
        svc, stripe, patches = self._svc_with_patches(overage=None, excess_units=1000)
        with patches[0], patches[1], patches[2], patches[3]:
            svc._report_overage_for_customer("cus_abc")

        stripe.create_invoice_item.assert_not_called()

    def test_unlimited_plan_skips_stripe(self):
        """eval_runs_limit=None (enterprise/unlimited) → Stripe NOT called."""
        sub = _active_sub(eval_runs_limit=None)
        svc, stripe, patches = self._svc_with_patches(sub=sub, excess_units=9999)
        with patches[0], patches[1], patches[2], patches[3]:
            svc._report_overage_for_customer("cus_abc")

        stripe.create_invoice_item.assert_not_called()

    def test_stripe_error_is_swallowed_not_raised(self):
        """An exception from stripe.create_invoice_item must be logged and swallowed."""
        svc, stripe, patches = self._svc_with_patches(excess_units=1000)
        stripe.create_invoice_item.side_effect = ConnectionError("Stripe 500")
        with patches[0], patches[1], patches[2], patches[3]:
            svc._report_overage_for_customer("cus_abc")  # must not raise

    def test_no_engine_returns_immediately(self):
        """When engine is None, _report_overage_for_customer is a no-op."""
        stripe = MagicMock()
        svc = _billing_service(engine=None, stripe_client=stripe)
        with patch.object(svc, "_tenant_id_by_customer") as mock_tenant:
            svc._report_overage_for_customer("cus_x")
        mock_tenant.assert_not_called()
        stripe.create_invoice_item.assert_not_called()

    def test_description_mentions_excess_and_units(self):
        """Invoice item description must reference the excess run count and unit blocks."""
        svc, stripe, patches = self._svc_with_patches(excess_units=1000)
        with patches[0], patches[1], patches[2], patches[3]:
            svc._report_overage_for_customer("cus_abc")

        kwargs = stripe.create_invoice_item.call_args[1]
        desc = kwargs["description"]
        assert "1000" in desc  # excess runs
        assert "2" in desc  # number of units (1000 // 500)


# ---------------------------------------------------------------------------
# T-04e: UsageMeter.increment() — DB success path
# ---------------------------------------------------------------------------


class TestUsageMeterIncrementDB:
    """UsageMeter.increment() DB path returns the new counter value from RETURNING."""

    def _meter_with_engine(self, returning_count: int):
        """Return a UsageMeter backed by a mock engine that returns returning_count."""
        engine = MagicMock()
        conn = MagicMock()
        engine.begin.return_value.__enter__ = lambda s: conn
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = (returning_count,)
        return UsageMeter(engine=engine), conn

    def test_increment_returns_new_count_from_db(self):
        """When DB returns (42,), increment() must return 42."""
        meter, _ = self._meter_with_engine(returning_count=42)
        result = meter.increment("tenant-1", "eval_runs")
        assert result == 42

    def test_increment_passes_tenant_and_metric_to_query(self):
        """tenant_id and metric must be forwarded as SQL parameters."""
        meter, conn = self._meter_with_engine(returning_count=1)
        meter.increment("my-tenant", "eval_runs")
        params = conn.execute.call_args[0][1]
        assert params["tid"] == "my-tenant"
        assert params["metric"] == "eval_runs"

    def test_increment_passes_current_year_month(self):
        """year and month are drawn from _current_period() and forwarded to SQL."""
        meter, conn = self._meter_with_engine(returning_count=5)
        year, month = UsageMeter._current_period()
        meter.increment("t1", "eval_runs")
        params = conn.execute.call_args[0][1]
        assert params["year"] == year
        assert params["month"] == month

    def test_increment_uses_upsert_returning(self):
        """SQL must use ON CONFLICT DO UPDATE … RETURNING count (atomic upsert)."""
        meter, conn = self._meter_with_engine(returning_count=3)
        meter.increment("t1", "eval_runs")
        sql = conn.execute.call_args[0][0].text
        assert "ON CONFLICT" in sql
        assert "RETURNING" in sql

    def test_increment_returns_one_when_fetchone_is_none(self):
        """If RETURNING returns no row (edge case), increment() falls back to 1."""
        engine = MagicMock()
        conn = MagicMock()
        engine.begin.return_value.__enter__ = lambda s: conn
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = None  # edge case
        meter = UsageMeter(engine=engine)
        result = meter.increment("t1", "eval_runs")
        assert result == 1

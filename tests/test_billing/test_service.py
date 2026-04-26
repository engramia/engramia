# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Unit tests for BillingService (engramia/billing/service.py).

All DB interactions are mocked via a MagicMock engine. Stripe calls are
mocked via a MagicMock StripeClient. No real DB or network is needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy.exc

from engramia.billing.models import (
    METRIC_EVAL_RUNS,
    BillingStatus,
    BillingSubscription,
    OverageSettings,
)
from engramia.billing.service import BillingService

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
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


def _sub_row(
    tenant_id="t1",
    customer_id="cus_abc",
    sub_id="sub_xyz",
    plan_tier="pro",
    interval="month",
    status="active",
    eval_runs_limit=3000,
    patterns_limit=50000,
    projects_limit=3,
    period_end="2026-05-01",
    past_due_since=None,
    cancel_at_period_end=False,
):
    """Return a tuple matching the SELECT column order in get_subscription()."""
    return (
        customer_id,
        sub_id,
        plan_tier,
        interval,
        status,
        eval_runs_limit,
        patterns_limit,
        projects_limit,
        period_end,
        past_due_since,
        cancel_at_period_end,
    )


def _overage_row(enabled=True, price=1, unit=100, cap=10000):
    return (enabled, price, unit, cap)


def _billing_service(engine=None, stripe_client=None) -> BillingService:
    stripe = stripe_client or MagicMock()
    return BillingService(engine=engine, stripe_client=stripe)


# ---------------------------------------------------------------------------
# get_subscription()
# ---------------------------------------------------------------------------


class TestGetSubscription:
    def test_no_engine_returns_sandbox_default(self):
        svc = _billing_service(engine=None)
        sub = svc.get_subscription("t1")
        assert sub.plan_tier == "sandbox"
        assert sub.tenant_id == "t1"

    def test_db_row_found_returns_subscription(self):
        engine, _ = _engine_with_row(_sub_row())
        svc = _billing_service(engine=engine)
        sub = svc.get_subscription("t1")
        assert sub.plan_tier == "pro"
        assert sub.stripe_customer_id == "cus_abc"
        assert sub.eval_runs_limit == 3000

    def test_db_row_missing_returns_sandbox(self):
        engine, _ = _engine_with_row(None)
        svc = _billing_service(engine=engine)
        sub = svc.get_subscription("t1")
        assert sub.plan_tier == "sandbox"

    def test_db_error_returns_sandbox_default(self):
        engine = MagicMock()
        engine.connect.side_effect = sqlalchemy.exc.OperationalError("stmt", {}, Exception("DB down"))
        svc = _billing_service(engine=engine)
        sub = svc.get_subscription("t1")
        assert sub.plan_tier == "sandbox"

    def test_tenant_id_passed_to_query(self):
        engine, conn = _engine_with_row(None)
        svc = _billing_service(engine=engine)
        svc.get_subscription("my-tenant")
        args = conn.execute.call_args[0][1]
        assert args["tid"] == "my-tenant"


# ---------------------------------------------------------------------------
# get_overage_settings()
# ---------------------------------------------------------------------------


class TestGetOverageSettings:
    def test_no_engine_returns_none(self):
        svc = _billing_service(engine=None)
        result = svc.get_overage_settings("t1", METRIC_EVAL_RUNS)
        assert result is None

    def test_row_found_returns_overage_settings(self):
        engine, _ = _engine_with_row(_overage_row())
        svc = _billing_service(engine=engine)
        result = svc.get_overage_settings("t1", METRIC_EVAL_RUNS)
        assert isinstance(result, OverageSettings)
        assert result.enabled is True
        assert result.budget_cap_cents == 10000

    def test_row_missing_returns_none(self):
        engine, _ = _engine_with_row(None)
        svc = _billing_service(engine=engine)
        result = svc.get_overage_settings("t1", METRIC_EVAL_RUNS)
        assert result is None

    def test_db_error_returns_none(self):
        engine = MagicMock()
        engine.connect.side_effect = sqlalchemy.exc.OperationalError("stmt", {}, Exception("DB down"))
        svc = _billing_service(engine=engine)
        result = svc.get_overage_settings("t1", METRIC_EVAL_RUNS)
        assert result is None


# ---------------------------------------------------------------------------
# get_status()
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_no_engine_returns_sandbox_status(self):
        svc = _billing_service(engine=None)
        status = svc.get_status("t1", current_pattern_count=5)
        assert status.plan_tier == "sandbox"
        assert status.patterns_used == 5

    def test_with_engine_aggregates_meter_and_subscription(self):
        engine = MagicMock()
        # get_subscription
        conn_r = MagicMock()
        engine.connect.return_value.__enter__ = lambda s: conn_r
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        conn_r.execute.return_value.fetchone.side_effect = [
            _sub_row(eval_runs_limit=3000),  # get_subscription
            None,  # get_overage_settings
            (42,),  # meter.get_count
            (2,),  # _count_projects
        ]
        svc = _billing_service(engine=engine)
        status = svc.get_status("t1", current_pattern_count=100)
        assert status.plan_tier == "pro"
        assert status.patterns_used == 100
        assert isinstance(status, BillingStatus)


# ---------------------------------------------------------------------------
# check_eval_runs() / check_patterns()
# ---------------------------------------------------------------------------


class TestEnforcement:
    def test_check_eval_runs_no_engine_is_noop(self):
        svc = _billing_service(engine=None)
        svc.check_eval_runs("t1")  # must not raise

    def test_check_patterns_no_engine_is_noop(self):
        svc = _billing_service(engine=None)
        svc.check_patterns("t1", 9999)  # must not raise

    def test_check_eval_runs_calls_enforcer(self):
        svc = _billing_service(engine=None)
        with (
            patch.object(svc._enforcer, "check_eval_runs") as mock_check,
            patch.object(svc, "get_subscription", return_value=BillingSubscription.sandbox_default("t1")),
            patch.object(svc, "get_overage_settings", return_value=None),
        ):
            svc._engine = MagicMock()  # trick: make engine truthy
            svc.check_eval_runs("t1")
        mock_check.assert_called_once()


# ---------------------------------------------------------------------------
# increment_eval_runs()
# ---------------------------------------------------------------------------


class TestMetering:
    def test_increment_eval_runs_delegates_to_meter(self):
        svc = _billing_service(engine=None)
        with patch.object(svc._meter, "increment") as mock_inc:
            svc.increment_eval_runs("t1")
        mock_inc.assert_called_once_with("t1", METRIC_EVAL_RUNS)


# ---------------------------------------------------------------------------
# create_checkout_url() / create_portal_url()
# ---------------------------------------------------------------------------


class TestStripeUrls:
    def test_create_checkout_delegates_to_stripe(self):
        stripe = MagicMock()
        stripe.create_checkout_session.return_value = "https://checkout.stripe.com/pay/cs_test"
        svc = _billing_service(engine=None, stripe_client=stripe)
        url = svc.create_checkout_url("t1", "price_pro", "https://ok", "https://cancel")
        assert url == "https://checkout.stripe.com/pay/cs_test"
        stripe.create_checkout_session.assert_called_once()

    def test_create_portal_no_customer_raises(self):
        svc = _billing_service(engine=None)
        # sandbox_default has no stripe_customer_id
        with pytest.raises(RuntimeError, match="no Stripe customer"):
            svc.create_portal_url("t1", "https://return")

    def test_create_portal_delegates_to_stripe_when_customer_exists(self):
        stripe = MagicMock()
        stripe.create_customer_portal_session.return_value = "https://billing.stripe.com/session/xyz"
        engine, _ = _engine_with_row(_sub_row(customer_id="cus_123"))
        svc = _billing_service(engine=engine, stripe_client=stripe)
        url = svc.create_portal_url("t1", "https://return")
        assert url == "https://billing.stripe.com/session/xyz"


# ---------------------------------------------------------------------------
# set_overage()
# ---------------------------------------------------------------------------


class TestSetOverage:
    def test_no_engine_is_noop(self):
        svc = _billing_service(engine=None)
        svc.set_overage("t1", enabled=True, budget_cap_cents=None)  # must not raise

    def test_sandbox_plan_raises_value_error(self):
        engine, _ = _engine_with_row(None)  # None row → sandbox plan
        svc = _billing_service(engine=engine)
        with pytest.raises(ValueError, match="not available for plan tier"):
            svc.set_overage("t1", enabled=True, budget_cap_cents=None)

    def test_pro_plan_upserts_row(self):
        engine, _conn_r = _engine_with_row(_sub_row(plan_tier="pro"))
        _engine_w, _conn_w = _engine_begin()

        call_count = [0]

        def _connect_side_effect():
            ctx = MagicMock()
            row = _sub_row(plan_tier="pro") if call_count[0] == 0 else None
            call_count[0] += 1
            conn_local = MagicMock()
            conn_local.execute.return_value.fetchone.return_value = row
            ctx.__enter__ = lambda s: conn_local
            ctx.__exit__ = MagicMock(return_value=False)
            return ctx

        engine.connect.side_effect = _connect_side_effect

        svc = _billing_service(engine=engine, stripe_client=MagicMock())
        # Use pro plan — patch get_subscription to avoid repeated DB mock complexity
        with patch.object(svc, "get_subscription") as mock_sub:
            mock_sub.return_value = BillingSubscription(
                tenant_id="t1",
                stripe_customer_id="cus_x",
                stripe_subscription_id="sub_x",
                plan_tier="pro",
                billing_interval="month",
                status="active",
                eval_runs_limit=3000,
                patterns_limit=50000,
                projects_limit=3,
                current_period_end=None,
            )
            svc.set_overage("t1", enabled=True, budget_cap_cents=5000)
        # Verify that begin() was called (DB write happened)
        engine.begin.assert_called()


# ---------------------------------------------------------------------------
# handle_webhook_event()
# ---------------------------------------------------------------------------


class TestHandleWebhookEvent:
    def _make_svc(self, event_type, data=None, event_id="evt_test_001"):
        stripe = MagicMock()
        event = {"id": event_id, "type": event_type, "data": {"object": data or {}}}
        stripe.construct_webhook_event.return_value = event
        svc = _billing_service(engine=None, stripe_client=stripe)
        return svc, stripe

    def test_returns_event_type(self):
        svc, _ = self._make_svc("invoice.paid", {"customer": "cus_x"})
        with patch.object(svc, "_set_status_by_customer"):
            result = svc.handle_webhook_event(b"{}", "sig")
        assert result == "invoice.paid"

    def test_subscription_created_calls_upsert(self):
        data = {
            "customer": "cus_x",
            "id": "sub_x",
            "status": "active",
            "items": {"data": [{"plan": {"interval": "month"}}]},
            "current_period_end": 1900000000,
            "metadata": {"plan_tier": "pro"},
        }
        svc, _ = self._make_svc("customer.subscription.created", data)
        with patch.object(svc, "_upsert_subscription") as mock_upsert:
            svc.handle_webhook_event(b"{}", "sig")
        mock_upsert.assert_called_once_with(data)

    def test_subscription_updated_calls_upsert(self):
        data = {
            "customer": "cus_x",
            "id": "sub_x",
            "status": "active",
            "items": {"data": [{"plan": {"interval": "month"}}]},
            "current_period_end": 1900000000,
            "metadata": {},
        }
        svc, _ = self._make_svc("customer.subscription.updated", data)
        with patch.object(svc, "_upsert_subscription") as mock_upsert:
            svc.handle_webhook_event(b"{}", "sig")
        mock_upsert.assert_called_once()

    def test_subscription_deleted_calls_downgrade(self):
        svc, _ = self._make_svc("customer.subscription.deleted", {"customer": "cus_x"})
        with patch.object(svc, "_downgrade_to_sandbox") as mock_down:
            svc.handle_webhook_event(b"{}", "sig")
        mock_down.assert_called_once_with("cus_x")

    def test_invoice_payment_failed_sets_past_due(self):
        svc, _ = self._make_svc("invoice.payment_failed", {"customer": "cus_x"})
        with patch.object(svc, "_set_status_by_customer") as mock_status:
            svc.handle_webhook_event(b"{}", "sig")
        mock_status.assert_called_once_with("cus_x", "past_due")

    def test_invoice_paid_sets_active(self):
        svc, _ = self._make_svc("invoice.paid", {"customer": "cus_x"})
        with patch.object(svc, "_set_status_by_customer") as mock_status:
            svc.handle_webhook_event(b"{}", "sig")
        mock_status.assert_called_once_with("cus_x", "active")

    def test_invoice_created_reports_overage(self):
        svc, _ = self._make_svc("invoice.created", {"customer": "cus_x"})
        with patch.object(svc, "_report_overage_for_customer") as mock_overage:
            svc.handle_webhook_event(b"{}", "sig")
        mock_overage.assert_called_once_with("cus_x")

    def test_unknown_event_type_returns_event_type(self):
        svc, _ = self._make_svc("some.unknown.event", {})
        result = svc.handle_webhook_event(b"{}", "sig")
        assert result == "some.unknown.event"

    def test_invalid_signature_propagates_value_error(self):
        stripe = MagicMock()
        stripe.construct_webhook_event.side_effect = ValueError("Bad sig")
        svc = _billing_service(engine=None, stripe_client=stripe)
        with pytest.raises(ValueError):
            svc.handle_webhook_event(b"{}", "badsig")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestInternalHelpers:
    def test_upsert_subscription_no_engine_returns(self):
        svc = _billing_service(engine=None)
        svc._upsert_subscription({"customer": "cus_x"})  # must not raise

    def test_downgrade_no_engine_returns(self):
        svc = _billing_service(engine=None)
        svc._downgrade_to_sandbox("cus_x")  # must not raise

    def test_set_status_by_customer_no_engine_returns(self):
        svc = _billing_service(engine=None)
        svc._set_status_by_customer("cus_x", "active")  # must not raise

    def test_tenant_id_by_customer_no_engine_returns_none(self):
        svc = _billing_service(engine=None)
        assert svc._tenant_id_by_customer("cus_x") is None

    def test_count_projects_no_engine_returns_zero(self):
        svc = _billing_service(engine=None)
        assert svc._count_projects("t1") == 0

    def test_tenant_id_by_customer_found(self):
        engine, _conn = _engine_with_row(("my-tenant",))
        svc = _billing_service(engine=engine)
        result = svc._tenant_id_by_customer("cus_abc")
        assert result == "my-tenant"

    def test_tenant_id_by_customer_not_found(self):
        engine, _ = _engine_with_row(None)
        svc = _billing_service(engine=engine)
        result = svc._tenant_id_by_customer("unknown")
        assert result is None

    def test_count_projects_returns_count(self):
        engine, _ = _engine_with_row((7,))
        svc = _billing_service(engine=engine)
        assert svc._count_projects("t1") == 7

    def test_count_projects_db_error_returns_zero(self):
        engine = MagicMock()
        engine.connect.side_effect = sqlalchemy.exc.OperationalError("stmt", {}, Exception("DB down"))
        svc = _billing_service(engine=engine)
        assert svc._count_projects("t1") == 0

    def test_report_overage_no_tenant_found_skips(self):
        svc = _billing_service(engine=None)
        with patch.object(svc, "_tenant_id_by_customer", return_value=None):
            svc._report_overage_for_customer("cus_x")  # must not raise

    def test_report_overage_unlimited_plan_skips(self):
        svc = _billing_service(engine=None)
        sub = BillingSubscription(
            tenant_id="t1",
            stripe_customer_id="cus_x",
            stripe_subscription_id=None,
            plan_tier="enterprise",
            billing_interval="year",
            status="active",
            eval_runs_limit=None,
            patterns_limit=None,
            projects_limit=None,
            current_period_end=None,
        )
        with (
            patch.object(svc, "_tenant_id_by_customer", return_value="t1"),
            patch.object(svc, "get_subscription", return_value=sub),
        ):
            svc._report_overage_for_customer("cus_x")  # must not raise (unlimited → skip)

    def test_downgrade_to_sandbox_updates_db(self):
        engine, conn = _engine_begin()
        svc = _billing_service(engine=engine)
        svc._downgrade_to_sandbox("cus_x")
        conn.execute.assert_called_once()
        sql = conn.execute.call_args[0][0].text
        assert "UPDATE billing_subscriptions" in sql

    def test_set_status_by_customer_updates_db(self):
        engine, conn = _engine_begin()
        svc = _billing_service(engine=engine)
        svc._set_status_by_customer("cus_x", "past_due")
        conn.execute.assert_called_once()
        args = conn.execute.call_args[0][1]
        assert args["status"] == "past_due"
        assert args["cid"] == "cus_x"

    def test_upsert_subscription_falls_back_to_metadata_tenant_id(self):
        """When customer lookup returns None, tenant_id is read from sub metadata."""
        engine, conn = _engine_begin()
        svc = _billing_service(engine=engine)
        sub_data = {
            "customer": "cus_new",
            "id": "sub_new",
            "status": "active",
            "items": {"data": [{"plan": {"interval": "month"}}]},
            "current_period_end": 1900000000,
            "metadata": {"plan_tier": "pro", "tenant_id": "tenant-from-metadata"},
        }
        with patch.object(svc, "_tenant_id_by_customer", return_value=None):
            svc._upsert_subscription(sub_data)
        # DB write must have been attempted with the metadata tenant_id
        conn.execute.assert_called_once()
        params = conn.execute.call_args[0][1]
        assert params["tid"] == "tenant-from-metadata"

    def test_upsert_subscription_logs_warning_when_no_tenant_anywhere(self):
        """When both customer lookup and metadata return nothing, event is skipped."""
        svc = _billing_service(engine=None)
        sub_data = {
            "customer": "cus_orphan",
            "id": "sub_orphan",
            "status": "active",
            "items": {"data": [{"plan": {"interval": "month"}}]},
            "current_period_end": 1900000000,
            "metadata": {},  # no tenant_id in metadata
        }
        with patch.object(svc, "_tenant_id_by_customer", return_value=None):
            svc._upsert_subscription(sub_data)  # must not raise


# ---------------------------------------------------------------------------
# create_stripe_customer()
# ---------------------------------------------------------------------------


class TestCreateStripeCustomer:
    def test_no_stripe_configured_returns_none(self):
        stripe = MagicMock()
        stripe.create_customer.side_effect = RuntimeError("Stripe not configured")
        svc = _billing_service(engine=None, stripe_client=stripe)
        result = svc.create_stripe_customer("t1")
        assert result is None

    def test_no_engine_returns_customer_id_without_db_write(self):
        stripe = MagicMock()
        stripe.create_customer.return_value = "cus_new_123"
        svc = _billing_service(engine=None, stripe_client=stripe)
        result = svc.create_stripe_customer("t1", email="owner@example.com")
        assert result == "cus_new_123"
        stripe.create_customer.assert_called_once_with(tenant_id="t1", email="owner@example.com")

    def test_with_engine_persists_customer_id(self):
        stripe = MagicMock()
        stripe.create_customer.return_value = "cus_persisted"
        engine, conn = _engine_begin()
        svc = _billing_service(engine=engine, stripe_client=stripe)
        result = svc.create_stripe_customer("tenant-abc")
        assert result == "cus_persisted"
        conn.execute.assert_called_once()
        params = conn.execute.call_args[0][1]
        assert params["tid"] == "tenant-abc"
        assert params["cid"] == "cus_persisted"

    def test_db_error_does_not_propagate(self):
        stripe = MagicMock()
        stripe.create_customer.return_value = "cus_ok"
        engine = MagicMock()
        engine.begin.side_effect = sqlalchemy.exc.OperationalError("stmt", {}, Exception("DB down"))
        svc = _billing_service(engine=engine, stripe_client=stripe)
        result = svc.create_stripe_customer("t1")
        # Should still return the customer ID even if DB write failed
        assert result == "cus_ok"


# ---------------------------------------------------------------------------
# Dunning: _set_status_by_customer grace-period tracking
# ---------------------------------------------------------------------------


class TestDunningStatusTracking:
    def test_past_due_sets_past_due_since_when_null(self):
        engine, conn = _engine_begin()
        svc = _billing_service(engine=engine)
        svc._set_status_by_customer("cus_x", "past_due")
        conn.execute.assert_called_once()
        sql = conn.execute.call_args[0][0].text
        # past_due_since must only be set if it is currently NULL
        assert "past_due_since" in sql
        assert "CASE WHEN past_due_since IS NULL" in sql
        params = conn.execute.call_args[0][1]
        assert params["status"] == "past_due"
        assert "now" in params  # timestamp was passed

    def test_active_clears_past_due_since(self):
        engine, conn = _engine_begin()
        svc = _billing_service(engine=engine)
        svc._set_status_by_customer("cus_x", "active")
        conn.execute.assert_called_once()
        sql = conn.execute.call_args[0][0].text
        assert "past_due_since = NULL" in sql
        params = conn.execute.call_args[0][1]
        assert params["status"] == "active"

    def test_other_status_does_not_touch_past_due_since(self):
        engine, conn = _engine_begin()
        svc = _billing_service(engine=engine)
        svc._set_status_by_customer("cus_x", "trialing")
        sql = conn.execute.call_args[0][0].text
        assert "past_due_since" not in sql

    def test_get_subscription_reads_past_due_since(self):
        past_due_ts = "2026-03-29T00:00:00+00:00"
        engine, _ = _engine_with_row(_sub_row(status="past_due", past_due_since=past_due_ts))
        svc = _billing_service(engine=engine)
        sub = svc.get_subscription("t1")
        assert sub.status == "past_due"
        assert sub.past_due_since == past_due_ts


# ---------------------------------------------------------------------------
# Subscription lifecycle edge cases
# ---------------------------------------------------------------------------


class TestSubscriptionLifecycleEdgeCases:
    """Edge cases for subscription lifecycle and dunning state machine."""

    def _sub_data(self, status="active", plan_tier="pro"):
        return {
            "customer": "cus_lifecycle",
            "id": "sub_lifecycle",
            "status": status,
            "items": {"data": [{"plan": {"interval": "month"}}]},
            "current_period_end": 1900000000,
            "metadata": {"plan_tier": plan_tier},
        }

    def test_upgrade_while_in_dunning_calls_upsert(self):
        """subscription.updated must upsert even when current status is past_due."""
        stripe = MagicMock()
        event = {
            "id": "evt_upgrade_dunning",
            "type": "customer.subscription.updated",
            "data": {"object": self._sub_data(status="active", plan_tier="team")},
        }
        stripe.construct_webhook_event.return_value = event
        svc = _billing_service(engine=None, stripe_client=stripe)

        with patch.object(svc, "_upsert_subscription") as mock_upsert:
            result = svc.handle_webhook_event(b"{}", "sig")

        mock_upsert.assert_called_once()
        assert result == "customer.subscription.updated"

    def test_double_cancel_second_downgrade_still_executes(self):
        """subscription.deleted is idempotent — calling _downgrade_to_sandbox twice is safe."""
        engine, conn = _engine_begin()
        svc = _billing_service(engine=engine)
        svc._downgrade_to_sandbox("cus_x")
        svc._downgrade_to_sandbox("cus_x")
        # Both calls must have issued DB updates
        assert conn.execute.call_count == 2

    def test_reactivate_after_past_due_clears_dunning_clock(self):
        """invoice.paid after past_due must call _set_status_by_customer with 'active',
        which clears past_due_since in the DB."""
        stripe = MagicMock()
        event = {
            "id": "evt_reactivate",
            "type": "invoice.paid",
            "data": {"object": {"customer": "cus_dunning"}},
        }
        stripe.construct_webhook_event.return_value = event
        svc = _billing_service(engine=None, stripe_client=stripe)

        with patch.object(svc, "_set_status_by_customer") as mock_status:
            svc.handle_webhook_event(b"{}", "sig")

        mock_status.assert_called_once_with("cus_dunning", "active")

    def test_cancel_then_reactivate_via_new_subscription(self):
        """After cancel (subscription.deleted), a new subscription.created re-upserts."""
        stripe = MagicMock()
        cancel_event = {
            "id": "evt_cancel",
            "type": "customer.subscription.deleted",
            "data": {"object": {"customer": "cus_x"}},
        }
        create_event = {
            "id": "evt_create_new",
            "type": "customer.subscription.created",
            "data": {"object": self._sub_data(status="active", plan_tier="pro")},
        }
        stripe.construct_webhook_event.side_effect = [cancel_event, create_event]
        svc = _billing_service(engine=None, stripe_client=stripe)

        with (
            patch.object(svc, "_downgrade_to_sandbox") as mock_down,
            patch.object(svc, "_upsert_subscription") as mock_upsert,
        ):
            svc.handle_webhook_event(b"{}", "sig_cancel")
            svc.handle_webhook_event(b"{}", "sig_create")

        mock_down.assert_called_once_with("cus_x")
        mock_upsert.assert_called_once()

    def test_invoice_payment_failed_logs_attempt_count(self):
        """invoice.payment_failed must set past_due status regardless of attempt_count."""
        stripe = MagicMock()
        event = {
            "id": "evt_fail_attempt2",
            "type": "invoice.payment_failed",
            "data": {"object": {"customer": "cus_retry", "attempt_count": 3}},
        }
        stripe.construct_webhook_event.return_value = event
        svc = _billing_service(engine=None, stripe_client=stripe)

        with patch.object(svc, "_set_status_by_customer") as mock_status:
            result = svc.handle_webhook_event(b"{}", "sig")

        mock_status.assert_called_once_with("cus_retry", "past_due")
        assert result == "invoice.payment_failed"

    def test_invoice_created_without_customer_id_skips_overage(self):
        """invoice.created with no customer field must not call _report_overage_for_customer."""
        stripe = MagicMock()
        event = {
            "id": "evt_invoice_no_cust",
            "type": "invoice.created",
            "data": {"object": {}},  # no "customer" key
        }
        stripe.construct_webhook_event.return_value = event
        svc = _billing_service(engine=None, stripe_client=stripe)

        with patch.object(svc, "_report_overage_for_customer") as mock_overage:
            svc.handle_webhook_event(b"{}", "sig")

        mock_overage.assert_not_called()

    def test_upsert_subscription_db_error_does_not_propagate(self):
        """DB error in _upsert_subscription must be swallowed (logged, not raised)."""
        engine = MagicMock()
        engine.connect.return_value.__enter__ = lambda s: MagicMock(execute=MagicMock(return_value=MagicMock(fetchone=MagicMock(return_value=("t1",)))))
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        engine.begin.side_effect = sqlalchemy.exc.OperationalError("stmt", {}, Exception("DB down"))
        svc = _billing_service(engine=engine)
        sub_data = {
            "customer": "cus_x",
            "id": "sub_x",
            "status": "active",
            "items": {"data": [{"plan": {"interval": "month"}}]},
            "current_period_end": 1900000000,
            "metadata": {"plan_tier": "pro"},
        }
        # Must not raise even when DB fails
        svc._upsert_subscription(sub_data)

    def test_downgrade_to_sandbox_db_error_does_not_propagate(self):
        """DB error in _downgrade_to_sandbox must be swallowed (logged, not raised)."""
        engine = MagicMock()
        engine.begin.side_effect = sqlalchemy.exc.OperationalError("stmt", {}, Exception("DB down"))
        svc = _billing_service(engine=engine)
        svc._downgrade_to_sandbox("cus_x")  # must not raise

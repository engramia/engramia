# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""P0-1: Unit tests for billing.enforcement.LimitEnforcer.

Covers:
- check_eval_runs(): within quota, at limit, over limit, unlimited,
  overage enabled/disabled, budget cap logic
- check_patterns(): within/at/over quota, unlimited
- _next_period_start(): format and semantics
"""

import datetime
import re
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import datetime

from engramia.billing.enforcement import LimitEnforcer, _next_period_start
from engramia.billing.models import BillingSubscription, OverageSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sub(eval_runs_limit, patterns_limit=5_000, status="active", past_due_since=None):
    return BillingSubscription(
        tenant_id="t1",
        eval_runs_limit=eval_runs_limit,
        patterns_limit=patterns_limit,
        status=status,
        past_due_since=past_due_since,
    )


def _overage(
    enabled=True,
    budget_cap_cents=None,
    price_per_unit_cents=500,
    unit_size=500,
):
    return OverageSettings(
        tenant_id="t1",
        metric="eval_runs",
        enabled=enabled,
        price_per_unit_cents=price_per_unit_cents,
        unit_size=unit_size,
        budget_cap_cents=budget_cap_cents,
    )


def _enforcer(count: int) -> LimitEnforcer:
    meter = MagicMock()
    meter.get_count.return_value = count
    return LimitEnforcer(meter)


# ---------------------------------------------------------------------------
# LimitEnforcer.check_eval_runs
# ---------------------------------------------------------------------------


class TestCheckEvalRuns:
    def test_within_quota_no_raise(self):
        _enforcer(100).check_eval_runs("t1", _sub(eval_runs_limit=500), None)

    def test_at_limit_raises_429(self):
        with pytest.raises(HTTPException) as exc_info:
            _enforcer(500).check_eval_runs("t1", _sub(eval_runs_limit=500), None)
        assert exc_info.value.status_code == 429
        assert exc_info.value.detail["error"] == "quota_exceeded"
        assert exc_info.value.detail["metric"] == "eval_runs"

    def test_over_limit_raises_429_with_correct_counts(self):
        with pytest.raises(HTTPException) as exc_info:
            _enforcer(600).check_eval_runs("t1", _sub(eval_runs_limit=500), None)
        detail = exc_info.value.detail
        assert exc_info.value.status_code == 429
        assert detail["current"] == 600
        assert detail["limit"] == 500

    def test_unlimited_plan_never_raises(self):
        # Enterprise: eval_runs_limit=None means unlimited
        _enforcer(9_999_999).check_eval_runs("t1", _sub(eval_runs_limit=None), None)

    def test_overage_disabled_at_limit_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            _enforcer(500).check_eval_runs(
                "t1", _sub(eval_runs_limit=500), _overage(enabled=False)
            )
        assert exc_info.value.status_code == 429

    def test_overage_enabled_no_cap_allows_over_limit(self):
        # Overage enabled, no budget cap → always allow
        _enforcer(600).check_eval_runs(
            "t1", _sub(eval_runs_limit=500), _overage(enabled=True, budget_cap_cents=None)
        )

    def test_overage_within_budget_cap_allows(self):
        # count=550, limit=500 → excess=50 → excess_units = 50//500 = 0
        # spend = 0 * 500 = 0 < cap (10_000) → allow
        _enforcer(550).check_eval_runs(
            "t1",
            _sub(eval_runs_limit=500),
            _overage(enabled=True, budget_cap_cents=10_000, price_per_unit_cents=500, unit_size=500),
        )

    def test_overage_budget_cap_reached_raises(self):
        # count=1500, limit=500 → excess=1000
        # excess_units = 1000 // 500 = 2
        # spend = 2 * 500 = 1000 cents
        # cap = 500 cents → 1000 >= 500 → raise
        with pytest.raises(HTTPException) as exc_info:
            _enforcer(1500).check_eval_runs(
                "t1",
                _sub(eval_runs_limit=500),
                _overage(
                    enabled=True,
                    budget_cap_cents=500,
                    price_per_unit_cents=500,
                    unit_size=500,
                ),
            )
        assert exc_info.value.status_code == 429
        assert exc_info.value.detail["error"] == "overage_budget_cap_reached"

    def test_error_detail_contains_reset_date(self):
        with pytest.raises(HTTPException) as exc_info:
            _enforcer(999).check_eval_runs("t1", _sub(eval_runs_limit=500), None)
        detail = exc_info.value.detail
        assert "reset_date" in detail
        assert re.match(r"\d{4}-\d{2}-\d{2}", detail["reset_date"])

    def test_error_detail_contains_message(self):
        with pytest.raises(HTTPException) as exc_info:
            _enforcer(999).check_eval_runs("t1", _sub(eval_runs_limit=500), None)
        assert "message" in exc_info.value.detail

    def test_meter_queried_with_tenant_and_metric(self):
        meter = MagicMock()
        meter.get_count.return_value = 0
        enf = LimitEnforcer(meter)
        enf.check_eval_runs("tenant-xyz", _sub(eval_runs_limit=500), None)
        meter.get_count.assert_called_once_with("tenant-xyz", "eval_runs")

    def test_meter_not_queried_for_unlimited_plan(self):
        meter = MagicMock()
        enf = LimitEnforcer(meter)
        enf.check_eval_runs("t1", _sub(eval_runs_limit=None), None)
        meter.get_count.assert_not_called()


# ---------------------------------------------------------------------------
# LimitEnforcer.check_patterns
# ---------------------------------------------------------------------------


class TestCheckPatterns:
    # Patterns check does not use the meter — pass a dummy
    _enf = LimitEnforcer(MagicMock())

    def test_within_quota_no_raise(self):
        self._enf.check_patterns(100, _sub(eval_runs_limit=None, patterns_limit=5_000))

    def test_zero_patterns_no_raise(self):
        self._enf.check_patterns(0, _sub(eval_runs_limit=None, patterns_limit=5_000))

    def test_at_limit_raises_429(self):
        with pytest.raises(HTTPException) as exc_info:
            self._enf.check_patterns(
                5_000, _sub(eval_runs_limit=None, patterns_limit=5_000)
            )
        assert exc_info.value.status_code == 429
        detail = exc_info.value.detail
        assert detail["error"] == "quota_exceeded"
        assert detail["metric"] == "patterns"
        assert detail["current"] == 5_000
        assert detail["limit"] == 5_000

    def test_over_limit_raises_429(self):
        with pytest.raises(HTTPException) as exc_info:
            self._enf.check_patterns(
                6_000, _sub(eval_runs_limit=None, patterns_limit=5_000)
            )
        assert exc_info.value.status_code == 429

    def test_unlimited_no_raise(self):
        self._enf.check_patterns(
            9_999_999, _sub(eval_runs_limit=None, patterns_limit=None)
        )

    def test_error_detail_contains_reset_date(self):
        with pytest.raises(HTTPException) as exc_info:
            self._enf.check_patterns(
                5_001, _sub(eval_runs_limit=None, patterns_limit=5_000)
            )
        assert "reset_date" in exc_info.value.detail


# ---------------------------------------------------------------------------
# _next_period_start helper
# ---------------------------------------------------------------------------


class TestNextPeriodStart:
    def test_returns_iso_date_string(self):
        result = _next_period_start()
        assert re.match(r"\d{4}-\d{2}-01$", result), f"Expected YYYY-MM-01, got: {result}"

    def test_is_first_of_month(self):
        result = _next_period_start()
        dt = datetime.datetime.strptime(result, "%Y-%m-%d")
        assert dt.day == 1

    def test_is_in_the_future(self):
        result = _next_period_start()
        dt = datetime.datetime.strptime(result, "%Y-%m-%d")
        now = datetime.datetime.now(datetime.UTC)
        # Next period must be strictly after the current month start
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        assert dt > current_month_start

    def test_december_wraps_to_january(self):
        # Simulate a December date — year must increment
        with pytest.MonkeyPatch().context() as mp:
            fixed_dec = datetime.datetime(2026, 12, 15, tzinfo=datetime.UTC)

            class _FakeDatetime(datetime.datetime):
                @classmethod
                def now(cls, tz=None):
                    return fixed_dec

            mp.setattr(datetime, "datetime", _FakeDatetime)
            result = _next_period_start()
        assert result == "2027-01-01"


# ---------------------------------------------------------------------------
# Subscription status guard (_check_subscription_active)
# ---------------------------------------------------------------------------


class TestSubscriptionStatusGuard:
    """Tests for P0-2 status check and P1 7-day grace period."""

    _enf = LimitEnforcer(MagicMock())

    # -- past_due without grace period (no past_due_since) --

    def test_past_due_no_timestamp_raises_402(self):
        sub = _sub(eval_runs_limit=500, status="past_due", past_due_since=None)
        with pytest.raises(HTTPException) as exc_info:
            self._enf.check_eval_runs("t1", sub, None)
        assert exc_info.value.status_code == 402
        assert exc_info.value.detail["error"] == "payment_required"

    # -- canceled --

    def test_canceled_raises_403(self):
        sub = _sub(eval_runs_limit=500, status="canceled")
        with pytest.raises(HTTPException) as exc_info:
            self._enf.check_eval_runs("t1", sub, None)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["error"] == "subscription_canceled"

    def test_canceled_also_blocks_pattern_check(self):
        sub = _sub(eval_runs_limit=None, patterns_limit=5_000, status="canceled")
        with pytest.raises(HTTPException) as exc_info:
            self._enf.check_patterns(100, sub)
        assert exc_info.value.status_code == 403

    # -- grace period active (within 7 days) --

    def test_past_due_within_grace_period_allows_access(self):
        # past_due_since = 3 days ago → within 7-day window
        since = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=3)).isoformat()
        sub = _sub(eval_runs_limit=500, status="past_due", past_due_since=since)
        meter = MagicMock()
        meter.get_count.return_value = 100  # within quota
        LimitEnforcer(meter).check_eval_runs("t1", sub, None)  # must not raise

    def test_past_due_within_grace_period_still_enforces_quota(self):
        # Even within grace period, quota limits still apply
        since = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=3)).isoformat()
        sub = _sub(eval_runs_limit=500, status="past_due", past_due_since=since)
        with pytest.raises(HTTPException) as exc_info:
            _enforcer(600).check_eval_runs("t1", sub, None)
        # Quota error (429), not payment error (402)
        assert exc_info.value.status_code == 429

    def test_past_due_day_zero_allows_access(self):
        since = datetime.datetime.now(datetime.UTC).isoformat()
        sub = _sub(eval_runs_limit=None, status="past_due", past_due_since=since)
        LimitEnforcer(MagicMock()).check_eval_runs("t1", sub, None)  # must not raise

    def test_past_due_day_6_allows_access(self):
        since = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=6)).isoformat()
        sub = _sub(eval_runs_limit=None, status="past_due", past_due_since=since)
        LimitEnforcer(MagicMock()).check_eval_runs("t1", sub, None)  # must not raise

    # -- grace period expired (7+ days) --

    def test_past_due_after_7_days_raises_402(self):
        since = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=7)).isoformat()
        sub = _sub(eval_runs_limit=None, status="past_due", past_due_since=since)
        with pytest.raises(HTTPException) as exc_info:
            LimitEnforcer(MagicMock()).check_eval_runs("t1", sub, None)
        assert exc_info.value.status_code == 402

    def test_past_due_after_30_days_raises_402(self):
        since = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=30)).isoformat()
        sub = _sub(eval_runs_limit=None, status="past_due", past_due_since=since)
        with pytest.raises(HTTPException) as exc_info:
            LimitEnforcer(MagicMock()).check_eval_runs("t1", sub, None)
        assert exc_info.value.status_code == 402

    # -- malformed timestamp fallback --

    def test_past_due_malformed_timestamp_raises_402(self):
        # If timestamp is corrupted, block access (safe default)
        sub = _sub(eval_runs_limit=None, status="past_due", past_due_since="not-a-date")
        with pytest.raises(HTTPException) as exc_info:
            LimitEnforcer(MagicMock()).check_eval_runs("t1", sub, None)
        assert exc_info.value.status_code == 402

    # -- active subscription is unaffected --

    def test_active_subscription_passes_status_check(self):
        sub = _sub(eval_runs_limit=None, status="active")
        LimitEnforcer(MagicMock()).check_eval_runs("t1", sub, None)  # must not raise

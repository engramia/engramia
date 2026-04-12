# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Unit tests for UsageMeter (engramia/billing/metering.py).

All DB interactions are mocked via MagicMock engines. No real DB needed.
"""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pytest

from engramia.billing.metering import UsageMeter

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine_begin(fetchone_return=None):
    """Return a MagicMock engine where begin() works (for writes / increment)."""
    engine = MagicMock()
    conn = MagicMock()
    engine.begin.return_value.__enter__ = lambda s: conn
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value.fetchone.return_value = fetchone_return
    return engine, conn


def _engine_connect(fetchone_return=None):
    """Return a MagicMock engine where connect() works (for reads / get_count)."""
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = lambda s: conn
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value.fetchone.return_value = fetchone_return
    return engine, conn


def _meter(engine) -> UsageMeter:
    return UsageMeter(engine=engine)


# ---------------------------------------------------------------------------
# increment()
# ---------------------------------------------------------------------------


class TestIncrement:
    def test_no_engine_returns_zero(self):
        result = _meter(None).increment("t1", "eval_runs")
        assert result == 0

    def test_db_returns_new_count(self):
        engine, _ = _engine_begin(fetchone_return=(42,))
        result = _meter(engine).increment("t1", "eval_runs")
        assert result == 42

    def test_db_returns_none_row_falls_back_to_one(self):
        # First insert with no conflict: RETURNING may yield nothing on some paths.
        engine, _ = _engine_begin(fetchone_return=None)
        result = _meter(engine).increment("t1", "eval_runs")
        assert result == 1

    def test_db_error_returns_zero_and_does_not_raise(self):
        engine = MagicMock()
        engine.begin.side_effect = RuntimeError("DB unavailable")
        result = _meter(engine).increment("t1", "eval_runs")
        assert result == 0

    def test_sql_params_contain_tenant_and_metric(self):
        engine, conn = _engine_begin(fetchone_return=(1,))
        _meter(engine).increment("tenant-abc", "patterns")
        params = conn.execute.call_args[0][1]
        assert params["tid"] == "tenant-abc"
        assert params["metric"] == "patterns"

    def test_sql_params_contain_current_year_and_month(self):
        engine, conn = _engine_begin(fetchone_return=(1,))
        _meter(engine).increment("t1", "eval_runs")
        params = conn.execute.call_args[0][1]
        now = datetime.datetime.now(datetime.UTC)
        assert params["year"] == now.year
        assert params["month"] == now.month

    def test_uses_begin_transaction_not_connect(self):
        # increment must be atomic — it should use begin() not connect()
        engine, _ = _engine_begin(fetchone_return=(5,))
        _meter(engine).increment("t1", "eval_runs")
        engine.begin.assert_called_once()
        engine.connect.assert_not_called()

    def test_consecutive_calls_each_hit_db(self):
        engine = MagicMock()
        conn = MagicMock()
        engine.begin.return_value.__enter__ = lambda s: conn
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.side_effect = [(1,), (2,), (3,)]
        meter = _meter(engine)
        assert meter.increment("t1", "eval_runs") == 1
        assert meter.increment("t1", "eval_runs") == 2
        assert meter.increment("t1", "eval_runs") == 3
        assert engine.begin.call_count == 3


# ---------------------------------------------------------------------------
# get_count()
# ---------------------------------------------------------------------------


class TestGetCount:
    def test_no_engine_returns_zero(self):
        result = _meter(None).get_count("t1", "eval_runs")
        assert result == 0

    def test_row_found_returns_count(self):
        engine, _ = _engine_connect(fetchone_return=(99,))
        result = _meter(engine).get_count("t1", "eval_runs")
        assert result == 99

    def test_no_row_returns_zero(self):
        engine, _ = _engine_connect(fetchone_return=None)
        result = _meter(engine).get_count("t1", "eval_runs")
        assert result == 0

    def test_db_error_returns_zero_and_does_not_raise(self):
        engine = MagicMock()
        engine.connect.side_effect = RuntimeError("connection refused")
        result = _meter(engine).get_count("t1", "eval_runs")
        assert result == 0

    def test_sql_params_contain_tenant_and_metric(self):
        engine, conn = _engine_connect(fetchone_return=(5,))
        _meter(engine).get_count("my-tenant", "patterns")
        params = conn.execute.call_args[0][1]
        assert params["tid"] == "my-tenant"
        assert params["metric"] == "patterns"

    def test_explicit_year_month_passed_to_query(self):
        engine, conn = _engine_connect(fetchone_return=(10,))
        _meter(engine).get_count("t1", "eval_runs", year=2025, month=3)
        params = conn.execute.call_args[0][1]
        assert params["year"] == 2025
        assert params["month"] == 3

    def test_default_year_month_is_current_period(self):
        engine, conn = _engine_connect(fetchone_return=(0,))
        now = datetime.datetime.now(datetime.UTC)
        _meter(engine).get_count("t1", "eval_runs")
        params = conn.execute.call_args[0][1]
        assert params["year"] == now.year
        assert params["month"] == now.month

    def test_partial_explicit_period_uses_current_when_both_not_given(self):
        # year given but month=None → both default to current period
        engine, conn = _engine_connect(fetchone_return=(7,))
        now = datetime.datetime.now(datetime.UTC)
        _meter(engine).get_count("t1", "eval_runs", year=2099, month=None)
        params = conn.execute.call_args[0][1]
        # When only year OR month is None, the method falls back to current period for both
        assert params["year"] == now.year
        assert params["month"] == now.month

    def test_uses_connect_not_begin(self):
        # get_count is read-only; should not open a write transaction
        engine, _ = _engine_connect(fetchone_return=(3,))
        _meter(engine).get_count("t1", "eval_runs")
        engine.connect.assert_called_once()
        engine.begin.assert_not_called()

    def test_zero_count_row_returns_zero_not_none(self):
        engine, _ = _engine_connect(fetchone_return=(0,))
        result = _meter(engine).get_count("t1", "eval_runs")
        assert result == 0


# ---------------------------------------------------------------------------
# get_overage_units()
# ---------------------------------------------------------------------------


class TestGetOverageUnits:
    def test_no_engine_returns_zero(self):
        # get_count returns 0 with no engine, so overage is 0
        result = _meter(None).get_overage_units("t1", "eval_runs", limit=1000)
        assert result == 0

    def test_within_limit_returns_zero(self):
        engine, _ = _engine_connect(fetchone_return=(400,))
        result = _meter(engine).get_overage_units("t1", "eval_runs", limit=1000)
        assert result == 0

    def test_at_limit_exactly_returns_zero(self):
        engine, _ = _engine_connect(fetchone_return=(1000,))
        result = _meter(engine).get_overage_units("t1", "eval_runs", limit=1000)
        assert result == 0

    def test_one_over_limit_returns_one(self):
        engine, _ = _engine_connect(fetchone_return=(1001,))
        result = _meter(engine).get_overage_units("t1", "eval_runs", limit=1000)
        assert result == 1

    def test_over_limit_returns_correct_excess(self):
        engine, _ = _engine_connect(fetchone_return=(1500,))
        result = _meter(engine).get_overage_units("t1", "eval_runs", limit=1000)
        assert result == 500

    def test_zero_limit_all_usage_is_overage(self):
        engine, _ = _engine_connect(fetchone_return=(50,))
        result = _meter(engine).get_overage_units("t1", "eval_runs", limit=0)
        assert result == 50

    def test_zero_usage_zero_limit_returns_zero(self):
        engine, _ = _engine_connect(fetchone_return=(0,))
        result = _meter(engine).get_overage_units("t1", "eval_runs", limit=0)
        assert result == 0

    def test_db_unavailable_returns_zero(self):
        engine = MagicMock()
        engine.connect.side_effect = RuntimeError("DB down")
        result = _meter(engine).get_overage_units("t1", "eval_runs", limit=100)
        assert result == 0

    def test_delegates_to_get_count_for_current_period(self):
        meter = UsageMeter(engine=None)
        with patch.object(meter, "get_count", return_value=750) as mock_gc:
            result = meter.get_overage_units("tenant-x", "eval_runs", limit=500)
        mock_gc.assert_called_once_with("tenant-x", "eval_runs")
        assert result == 250

    def test_large_overage_not_capped(self):
        # get_overage_units has no internal cap — that's the enforcer's job
        engine, _ = _engine_connect(fetchone_return=(100_000,))
        result = _meter(engine).get_overage_units("t1", "eval_runs", limit=1000)
        assert result == 99_000


# ---------------------------------------------------------------------------
# _current_period() — static helper
# ---------------------------------------------------------------------------


class TestCurrentPeriod:
    def test_returns_two_tuple(self):
        result = UsageMeter._current_period()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_current_year_and_month(self):
        year, month = UsageMeter._current_period()
        now = datetime.datetime.now(datetime.UTC)
        assert year == now.year
        assert month == now.month

    def test_year_is_int(self):
        year, month = UsageMeter._current_period()
        assert isinstance(year, int)
        assert isinstance(month, int)

    def test_month_equals_current_month(self):
        fixed = datetime.datetime(2026, 4, 12, tzinfo=datetime.UTC)
        with patch("engramia.billing.metering.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = fixed
            mock_dt.UTC = datetime.UTC
            _, month = UsageMeter._current_period()
        assert month == 4  # April 2026

    def test_december_monkeypatch(self):
        fixed = datetime.datetime(2026, 12, 20, tzinfo=datetime.UTC)
        with patch("engramia.billing.metering.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = fixed
            mock_dt.UTC = datetime.UTC
            year, month = UsageMeter._current_period()
        assert year == 2026
        assert month == 12


# ---------------------------------------------------------------------------
# Additional coverage — new-tenant, atomic SQL, high-count scenarios
# ---------------------------------------------------------------------------


class TestIncrementAdditional:
    def test_increment_returns_large_count(self):
        """Increment must return whatever the DB RETURNING clause gives — no cap."""
        engine, _ = _engine_begin(fetchone_return=(999_999,))
        result = _meter(engine).increment("t1", "eval_runs")
        assert result == 999_999

    def test_upsert_sql_contains_on_conflict(self):
        """Atomic UPSERT requires ON CONFLICT DO UPDATE in the SQL."""
        engine, conn = _engine_begin(fetchone_return=(1,))
        _meter(engine).increment("t1", "eval_runs")
        sql = conn.execute.call_args[0][0].text
        assert "ON CONFLICT" in sql.upper()

    def test_increment_sql_uses_returning(self):
        """Increment must use RETURNING to get the new value atomically."""
        engine, conn = _engine_begin(fetchone_return=(5,))
        _meter(engine).increment("t1", "eval_runs")
        sql = conn.execute.call_args[0][0].text
        assert "RETURNING" in sql.upper()

    def test_increment_first_call_returns_one(self):
        """First increment for a tenant (no prior row) must return 1."""
        engine, _ = _engine_begin(fetchone_return=(1,))
        result = _meter(engine).increment("brand-new-tenant", "eval_runs")
        assert result == 1


class TestGetCountAdditional:
    def test_new_tenant_no_row_returns_zero(self):
        """get_count for a tenant with no usage row must return 0, not raise."""
        engine, _ = _engine_connect(fetchone_return=None)
        result = _meter(engine).get_count("brand-new-tenant", "eval_runs")
        assert result == 0

    def test_get_count_uses_connect_not_begin(self):
        """get_count is read-only and must use connect(), not begin()."""
        engine, _ = _engine_connect(fetchone_return=(10,))
        _meter(engine).get_count("t1", "eval_runs")
        engine.connect.assert_called_once()
        engine.begin.assert_not_called()

    def test_get_count_passes_tenant_and_metric_params(self):
        """SQL params must include tid and metric for correct row selection."""
        engine, conn = _engine_connect(fetchone_return=(7,))
        _meter(engine).get_count("acme-corp", "eval_runs")
        params = conn.execute.call_args[0][1]
        assert params["tid"] == "acme-corp"
        assert params["metric"] == "eval_runs"

    def test_get_count_for_explicit_past_period(self):
        """Explicit year/month params are forwarded to the query."""
        engine, conn = _engine_connect(fetchone_return=(42,))
        result = _meter(engine).get_count("t1", "eval_runs", year=2025, month=11)
        assert result == 42
        params = conn.execute.call_args[0][1]
        assert params["year"] == 2025
        assert params["month"] == 11

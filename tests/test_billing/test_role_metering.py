# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Behavioral tests for ``engramia.billing.role_metering.RoleMeter``.

The full atomic-UPSERT path requires a live PostgreSQL container and is
covered by the postgres-marked integration suite. These unit tests pin the
contract that does not need a real DB:

- ``engine=None`` is a no-op (dev / JSON-storage mode).
- Non-positive ``cost_cents`` short-circuits without touching the engine.
- The increment path emits the right composite key bind parameters and
  the SQL contains the atomicity-critical ``ON CONFLICT ... DO UPDATE``
  clause (the contract that makes concurrent calls safe).
- All three methods fail-open on engine errors — the LLM call path that
  triggered metering must not be invalidated by a metering failure.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from engramia.billing.role_metering import RoleMeter, current_month


# ---------------------------------------------------------------------------
# No-op mode
# ---------------------------------------------------------------------------


class TestNoEngineNoOp:
    def test_increment_returns_zero_when_engine_none(self):
        meter = RoleMeter(engine=None)
        assert (
            meter.increment_spend(
                tenant_id="t1", credential_id="c1", role="coder", cost_cents=42
            )
            == 0
        )

    def test_get_spend_returns_zero_when_engine_none(self):
        meter = RoleMeter(engine=None)
        assert meter.get_spend(tenant_id="t1", credential_id="c1", role="coder") == 0

    def test_list_for_credential_returns_empty_when_engine_none(self):
        meter = RoleMeter(engine=None)
        assert meter.list_for_credential(tenant_id="t1", credential_id="c1") == {}


# ---------------------------------------------------------------------------
# Increment short-circuits + SQL contract
# ---------------------------------------------------------------------------


class TestIncrementSpend:
    def _make_engine(self, returning: int | None = 100):
        """Return a MagicMock engine whose .begin() yields a conn whose
        .execute() returns a row with ``returning`` as the first column."""
        engine = MagicMock()
        conn = engine.begin.return_value.__enter__.return_value
        row = MagicMock()
        row.__getitem__.side_effect = lambda i: returning if i == 0 else None
        if returning is None:
            conn.execute.return_value.fetchone.return_value = None
        else:
            conn.execute.return_value.fetchone.return_value = row
        return engine, conn

    def test_zero_cost_short_circuits_without_db(self):
        engine, conn = self._make_engine()
        meter = RoleMeter(engine=engine)
        result = meter.increment_spend(
            tenant_id="t1", credential_id="c1", role="coder", cost_cents=0
        )
        assert result == 0
        assert conn.execute.called is False, (
            "cost_cents=0 must not touch the database — the gate's hot path "
            "calls increment_spend on every provider response and a no-op write "
            "would otherwise dominate DB load."
        )

    def test_negative_cost_short_circuits_without_db(self):
        engine, conn = self._make_engine()
        meter = RoleMeter(engine=engine)
        meter.increment_spend(
            tenant_id="t1", credential_id="c1", role="coder", cost_cents=-5
        )
        assert conn.execute.called is False

    def test_increment_emits_atomic_upsert_with_composite_key(self):
        engine, conn = self._make_engine(returning=420)
        meter = RoleMeter(engine=engine)
        result = meter.increment_spend(
            tenant_id="tenant-A",
            credential_id="cred-B",
            role="coder",
            cost_cents=42,
            tokens_in=100,
            tokens_out=200,
        )

        assert result == 420
        assert conn.execute.call_count == 1

        # Pin the SQL contract: the composite-key UPSERT keywords must be
        # present. Without ON CONFLICT DO UPDATE the contract degrades from
        # atomic-increment to "race-prone read-modify-write" — the bug
        # this counter was specifically designed to avoid.
        sql_arg = conn.execute.call_args[0][0]
        sql_text = str(sql_arg).upper()
        assert "INSERT INTO ROLE_SPEND_COUNTERS" in sql_text
        assert "ON CONFLICT" in sql_text
        assert "DO UPDATE" in sql_text
        assert "RETURNING SPEND_CENTS" in sql_text

        # Pin the composite primary key — every component must be bound.
        params = conn.execute.call_args[0][1]
        assert params["tid"] == "tenant-A"
        assert params["cid"] == "cred-B"
        assert params["role"] == "coder"
        assert params["month"] == current_month()
        assert params["cost"] == 42
        assert params["tin"] == 100
        assert params["tout"] == 200

    def test_increment_fails_open_on_db_error(self):
        engine = MagicMock()
        engine.begin.side_effect = RuntimeError("DB unavailable")
        meter = RoleMeter(engine=engine)
        # Must NOT raise — fail-open per module docstring.
        result = meter.increment_spend(
            tenant_id="t1", credential_id="c1", role="coder", cost_cents=42
        )
        assert result == 0


# ---------------------------------------------------------------------------
# Read paths fail-open
# ---------------------------------------------------------------------------


class TestReadFailOpen:
    def test_get_spend_returns_zero_on_db_error(self):
        engine = MagicMock()
        engine.connect.side_effect = RuntimeError("DB blip")
        meter = RoleMeter(engine=engine)
        assert meter.get_spend(tenant_id="t1", credential_id="c1", role="coder") == 0

    def test_list_for_credential_returns_empty_on_db_error(self):
        engine = MagicMock()
        engine.connect.side_effect = RuntimeError("DB blip")
        meter = RoleMeter(engine=engine)
        assert meter.list_for_credential(tenant_id="t1", credential_id="c1") == {}

    def test_get_spend_returns_zero_when_row_missing(self):
        engine = MagicMock()
        conn = engine.connect.return_value.__enter__.return_value
        conn.execute.return_value.fetchone.return_value = None
        meter = RoleMeter(engine=engine)
        assert meter.get_spend(tenant_id="t1", credential_id="c1", role="coder") == 0


# ---------------------------------------------------------------------------
# current_month()
# ---------------------------------------------------------------------------


class TestCurrentMonth:
    def test_format_yyyy_mm(self):
        m = current_month()
        assert len(m) == 7
        assert m[4] == "-"
        year, month = m.split("-")
        assert 2025 <= int(year) <= 2100
        assert 1 <= int(month) <= 12

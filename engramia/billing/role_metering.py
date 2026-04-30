# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Per-(tenant, credential, role, month) LLM cost accumulator (#2b).

Companion to :mod:`engramia.billing.metering`. The eval_runs counter is
a fair-use rate cap shared by the whole tenant; this counter is the
absolute monthly $ spend per role override, used to enforce the
:pep:`role_cost_limits` ceiling defined per credential.

Same atomic UPSERT pattern as ``UsageMeter`` — INSERT ... ON CONFLICT DO
UPDATE on the composite PK so concurrent provider calls don't race the
counter. ``role`` and ``month`` are part of the PK; the table grows by
one row per (tenant, credential, role, month) combination — capped by
the tenant's role cardinality (≤ 16 per credential per the validator).

All methods are safe to call with ``engine=None`` (dev / JSON-storage
mode = no-op). Errors are logged at WARNING and swallowed: a metering
failure must never break the LLM call path that triggered it. The cost
ceiling gate degrades gracefully — if the spend read fails, we let the
call through (fail-open), accepting that a transient DB blip might let
one over-budget call slip rather than blocking traffic.
"""

from __future__ import annotations

import datetime
import logging

from sqlalchemy import text

_log = logging.getLogger(__name__)


def current_month() -> str:
    """Return the current UTC month as ``YYYY-MM``.

    Same shape ``billing.metering`` uses so dashboards can join the two
    counters on the same calendar grouping.
    """
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m")


class RoleMeter:
    """Atomic per-role spend counter backed by ``role_spend_counters``.

    Args:
        engine: SQLAlchemy engine. ``None`` enables no-op mode.
    """

    def __init__(self, engine) -> None:
        self._engine = engine

    def increment_spend(
        self,
        *,
        tenant_id: str,
        credential_id: str,
        role: str,
        cost_cents: int,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> int:
        """UPSERT the (tenant, credential, role, current month) row.

        Returns the new ``spend_cents`` value, or 0 in no-op mode. Never
        raises — errors are logged. The caller (provider after-call hook)
        already has the response in hand; failing the metering write
        must not invalidate the response.

        Args:
            tenant_id: Active tenant from the scope contextvar.
            credential_id: Which credential billed this call.
            role: Logical role hint that drove the model selection.
            cost_cents: Result of ``rate_cards.cost_for(...)`` for the
                completed call. Caller computes — the meter does not
                touch the rate card to keep the metering layer testable
                without a card lookup.
            tokens_in / tokens_out: Optional usage breakdown for
                analytics; included in the row but not used by the gate.
        """
        if self._engine is None or cost_cents <= 0:
            return 0
        month = current_month()
        try:
            with self._engine.begin() as conn:
                row = conn.execute(
                    text(
                        """
                        INSERT INTO role_spend_counters
                            (tenant_id, credential_id, role, month,
                             spend_cents, tokens_in, tokens_out, updated_at)
                        VALUES
                            (:tid, :cid, :role, :month, :cost, :tin, :tout, now())
                        ON CONFLICT (tenant_id, credential_id, role, month)
                        DO UPDATE SET
                            spend_cents = role_spend_counters.spend_cents + EXCLUDED.spend_cents,
                            tokens_in   = role_spend_counters.tokens_in   + EXCLUDED.tokens_in,
                            tokens_out  = role_spend_counters.tokens_out  + EXCLUDED.tokens_out,
                            updated_at  = now()
                        RETURNING spend_cents
                        """
                    ),
                    {
                        "tid": tenant_id,
                        "cid": credential_id,
                        "role": role,
                        "month": month,
                        "cost": cost_cents,
                        "tin": tokens_in,
                        "tout": tokens_out,
                    },
                ).fetchone()
            return row[0] if row else cost_cents
        except Exception:
            _log.warning(
                "RoleMeter.increment_spend failed tenant=%s cred=%s role=%s",
                tenant_id,
                credential_id,
                role,
                exc_info=True,
            )
            return 0

    def get_spend(
        self,
        *,
        tenant_id: str,
        credential_id: str,
        role: str,
        month: str | None = None,
    ) -> int:
        """Return cumulative cents for the given (cred, role, month).

        Defaults to current UTC month. Returns 0 when no row exists,
        when the engine is unset, or when the read fails (fail-open —
        see module docstring).
        """
        if self._engine is None:
            return 0
        m = month or current_month()
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT spend_cents FROM role_spend_counters "
                        "WHERE tenant_id = :tid AND credential_id = :cid "
                        "AND role = :role AND month = :month"
                    ),
                    {"tid": tenant_id, "cid": credential_id, "role": role, "month": m},
                ).fetchone()
            return row[0] if row else 0
        except Exception:
            _log.warning(
                "RoleMeter.get_spend failed tenant=%s cred=%s role=%s",
                tenant_id,
                credential_id,
                role,
                exc_info=True,
            )
            return 0

    def list_for_credential(
        self,
        *,
        tenant_id: str,
        credential_id: str,
        month: str | None = None,
    ) -> dict[str, int]:
        """Return ``{role: spend_cents}`` for one credential in one month.

        Used by the dashboard's per-credential budget bar. Empty dict
        when nothing accumulated this month. Errors fail-open (empty).
        """
        if self._engine is None:
            return {}
        m = month or current_month()
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT role, spend_cents FROM role_spend_counters "
                        "WHERE tenant_id = :tid AND credential_id = :cid AND month = :month"
                    ),
                    {"tid": tenant_id, "cid": credential_id, "month": m},
                ).fetchall()
            return {r[0]: r[1] for r in rows}
        except Exception:
            _log.warning(
                "RoleMeter.list_for_credential failed tenant=%s cred=%s",
                tenant_id,
                credential_id,
                exc_info=True,
            )
            return {}

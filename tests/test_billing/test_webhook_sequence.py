# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""End-to-end Stripe webhook sequence test against a real Postgres + migrations.

The existing test_billing/test_webhooks_*.py files cover each handler in
isolation against a `MagicMock` engine. That catches per-handler regressions
but misses bugs that only surface across the **ordered sequence** of events
Stripe delivers when a customer subscribes:

    checkout.session.completed
        → customer.subscription.created
        → invoice.paid
        → invoice.payment_failed     (later month)
        → invoice.paid               (recovery)
        → customer.subscription.deleted

This test drives the actual ``BillingService`` through that sequence against
a throwaway pgvector container with the full alembic head applied, and
inspects the ``billing_subscriptions`` row at each step.

Also covered:

  - Out-of-order delivery: ``subscription.created`` before
    ``checkout.session.completed`` (Stripe does not guarantee ordering).
  - Idempotent replay: re-delivering any event must be a no-op once the
    ``stripe_event_id`` has been recorded.

Run:
    pytest -m postgres tests/test_billing/test_webhook_sequence.py
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.postgres


_MIGRATIONS_DIR = str(
    Path(__file__).parent.parent.parent / "engramia" / "db" / "migrations"
)


# ---------------------------------------------------------------------------
# Fake StripeClient — decodes the JSON payload back into an event dict so
# tests can drive deterministic event sequences without signature crypto.
# ---------------------------------------------------------------------------


class _FakeStripeClient:
    """Stand-in for engramia.billing.stripe_client.StripeClient.

    Only ``construct_webhook_event`` is exercised by the sequence test —
    the other methods are not called from the webhook code path.
    Returns the event dict directly from the payload (pre-encoded JSON).
    """

    def construct_webhook_event(self, payload: bytes, sig_header: str) -> dict:
        return json.loads(payload)

    # `_link_checkout_session` may try to fetch a Subscription via
    # `self._stripe._sdk.Subscription.retrieve(subscription_id)` in the
    # webhook handler when a `subscription` field is on the checkout
    # session. For the sequence test we omit that field so the back-fetch
    # branch is not entered; if a future test exercises it, expand here.


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_url():
    try:
        from alembic import command
        from alembic.config import Config
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers / alembic not installed")

    try:
        with PostgresContainer("pgvector/pgvector:0.7.4-pg16") as pg:
            url = pg.get_connection_url()
            cfg = Config()
            cfg.set_main_option("script_location", _MIGRATIONS_DIR)
            cfg.set_main_option("sqlalchemy.url", url)
            command.upgrade(cfg, "head")
            yield url
    except Exception as exc:
        pytest.skip(f"Postgres container failed: {exc}")


@pytest.fixture
def engine(pg_url):
    """Engine with billing-related tables wiped between tests.

    Each DELETE runs in its own transaction so a missing optional table
    (e.g. one that lives behind a feature flag) doesn't poison the
    surrounding txn with InFailedSqlTransaction for every statement
    that follows.
    """
    from sqlalchemy import create_engine, text

    eng = create_engine(pg_url, pool_pre_ping=True)

    for tbl in (
        "processed_webhook_events",
        "billing_subscriptions",
        "tenant_eval_runs",
        "tenants",
    ):
        try:
            with eng.begin() as conn:
                conn.execute(text(f"DELETE FROM {tbl}"))
        except Exception:
            pass  # Table may not exist in this branch / migration head.

    # tenants.name is NOT NULL in the real schema (migration 003).
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenants (id, name) VALUES (:tid, :name) "
                "ON CONFLICT DO NOTHING"
            ),
            {"tid": "tenant-1", "name": "tenant-1"},
        )
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def svc(engine):
    from engramia.billing.service import BillingService

    return BillingService(engine=engine, stripe_client=_FakeStripeClient())


# ---------------------------------------------------------------------------
# Event factories
# ---------------------------------------------------------------------------


def _ev(event_type: str, obj: dict, *, event_id: str | None = None) -> bytes:
    """Encode a Stripe-shaped event for the fake stripe client to decode."""
    return json.dumps(
        {
            "id": event_id or f"evt_{uuid.uuid4().hex}",
            "type": event_type,
            "data": {"object": obj},
        }
    ).encode()


def _checkout_completed(tenant_id: str, customer_id: str, *, mode: str = "subscription") -> bytes:
    return _ev(
        "checkout.session.completed",
        {
            "id": f"cs_{uuid.uuid4().hex}",
            "mode": mode,
            "client_reference_id": tenant_id,
            "customer": customer_id,
            # subscription field omitted so _link_checkout_session does NOT
            # back-fetch via the SDK (would need _stripe._sdk.Subscription).
        },
    )


def _subscription_event(
    event_type: str,
    *,
    sub_id: str,
    customer_id: str,
    status: str = "active",
    plan_tier: str = "pro",
    interval: str = "monthly",
    cancel_at_period_end: bool = False,
    period_end_offset_days: int = 30,
    tenant_id: str | None = None,
) -> bytes:
    period_end = int(time.time()) + period_end_offset_days * 86400
    metadata: dict = {"plan_tier": plan_tier}
    if tenant_id:
        metadata["tenant_id"] = tenant_id
    return _ev(
        event_type,
        {
            "id": sub_id,
            "customer": customer_id,
            "status": status,
            "cancel_at_period_end": cancel_at_period_end,
            "metadata": metadata,
            "items": {
                "data": [
                    {
                        "plan": {"interval": interval},
                        "current_period_end": period_end,
                        "price": {"id": "price_test_pro_monthly"},
                    }
                ]
            },
        },
    )


def _invoice_event(event_type: str, customer_id: str, attempt: int = 1) -> bytes:
    return _ev(
        event_type,
        {
            "id": f"in_{uuid.uuid4().hex}",
            "customer": customer_id,
            "attempt_count": attempt,
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(engine, tenant_id: str = "tenant-1") -> dict | None:
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT tenant_id, stripe_customer_id, stripe_subscription_id, "
                "plan_tier, billing_interval, status, cancel_at_period_end "
                "FROM billing_subscriptions WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        ).fetchone()
    if row is None:
        return None
    return {
        "tenant_id": row[0],
        "customer_id": row[1],
        "sub_id": row[2],
        "plan_tier": row[3],
        "interval": row[4],
        "status": row[5],
        "cancel_at_period_end": row[6],
    }


def _processed_count(engine) -> int:
    from sqlalchemy import text

    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM processed_webhook_events")).scalar()
    return int(n)


# ---------------------------------------------------------------------------
# The sequence test
# ---------------------------------------------------------------------------


class TestSubscribeFlow:
    def test_full_subscribe_to_cancel_sequence(self, engine, svc):
        cust = "cus_test_1"
        tenant = "tenant-1"
        sub_id = "sub_test_1"

        # 1. Checkout completed — stub row appears with status='incomplete'.
        svc.handle_webhook_event(_checkout_completed(tenant, cust), sig_header="x")
        row = _row(engine, tenant)
        assert row is not None
        assert row["customer_id"] == cust
        assert row["status"] == "incomplete"
        # subscription_id not yet set.
        assert row["sub_id"] in (None, "", )

        # 2. subscription.created — fills in plan, status='active', period_end.
        svc.handle_webhook_event(
            _subscription_event(
                "customer.subscription.created",
                sub_id=sub_id,
                customer_id=cust,
                status="active",
                plan_tier="pro",
                interval="monthly",
            ),
            sig_header="x",
        )
        row = _row(engine, tenant)
        assert row["sub_id"] == sub_id
        assert row["plan_tier"] == "pro"
        assert row["interval"] == "monthly"
        assert row["status"] == "active"
        assert row["cancel_at_period_end"] is False

        # 3. invoice.paid — status confirmed active.
        svc.handle_webhook_event(_invoice_event("invoice.paid", cust), sig_header="x")
        row = _row(engine, tenant)
        assert row["status"] == "active"

        # 4. invoice.payment_failed — status flips to past_due.
        svc.handle_webhook_event(
            _invoice_event("invoice.payment_failed", cust, attempt=1),
            sig_header="x",
        )
        row = _row(engine, tenant)
        assert row["status"] == "past_due"

        # 5. Recovery: invoice.paid lifts status back to active.
        svc.handle_webhook_event(_invoice_event("invoice.paid", cust), sig_header="x")
        row = _row(engine, tenant)
        assert row["status"] == "active"

        # 6. subscription.deleted — downgrade to sandbox + status canceled.
        svc.handle_webhook_event(
            _subscription_event(
                "customer.subscription.deleted",
                sub_id=sub_id,
                customer_id=cust,
                status="canceled",
                plan_tier="pro",
            ),
            sig_header="x",
        )
        row = _row(engine, tenant)
        assert row["status"] == "canceled"
        assert row["plan_tier"] == "sandbox"
        assert row["cancel_at_period_end"] is False


class TestOutOfOrder:
    def test_subscription_created_before_checkout_session_uses_metadata(
        self, engine, svc
    ):
        """Stripe does NOT guarantee event order. When subscription.created
        arrives first, BillingService falls back to subscription.metadata.tenant_id.
        """
        cust = "cus_ooo_1"
        tenant = "tenant-1"
        sub_id = "sub_ooo_1"

        # subscription.created arrives BEFORE checkout.session.completed.
        # Without _link_checkout_session having run, _tenant_id_by_customer
        # returns nothing — handler falls back to metadata.tenant_id.
        svc.handle_webhook_event(
            _subscription_event(
                "customer.subscription.created",
                sub_id=sub_id,
                customer_id=cust,
                tenant_id=tenant,  # fallback path
                plan_tier="pro",
            ),
            sig_header="x",
        )
        row = _row(engine, tenant)
        assert row is not None
        assert row["sub_id"] == sub_id
        assert row["plan_tier"] == "pro"
        assert row["status"] == "active"
        assert row["customer_id"] == cust

        # checkout.session.completed now arrives — the ON CONFLICT path keeps
        # plan_tier="pro" (richer) but writes the tenant→customer link.
        svc.handle_webhook_event(_checkout_completed(tenant, cust), sig_header="x")
        row = _row(engine, tenant)
        assert row["customer_id"] == cust
        # plan_tier from subscription.created should NOT be overwritten by
        # the checkout stub's 'incomplete' insert (ON CONFLICT only updates
        # stripe_customer_id + updated_at — see _link_checkout_session SQL).
        assert row["plan_tier"] == "pro"
        assert row["status"] == "active"


class TestIdempotency:
    def test_same_event_id_replayed_is_a_noop(self, engine, svc):
        """Stripe delivers at-least-once. A replayed event must not double-write."""
        cust = "cus_idem"
        tenant = "tenant-1"
        sub_id = "sub_idem"
        event_id = "evt_replay_me"

        sub_payload = _subscription_event(
            "customer.subscription.created",
            sub_id=sub_id,
            customer_id=cust,
            tenant_id=tenant,
            plan_tier="pro",
        )
        # Re-pack with a stable event_id.
        sub_obj = json.loads(sub_payload)
        sub_obj["id"] = event_id
        sub_payload = json.dumps(sub_obj).encode()

        svc.handle_webhook_event(sub_payload, sig_header="x")
        first_processed = _processed_count(engine)
        first_row = _row(engine, tenant)

        # Replay.
        svc.handle_webhook_event(sub_payload, sig_header="x")
        second_processed = _processed_count(engine)
        second_row = _row(engine, tenant)

        # The dedupe table count is unchanged (ON CONFLICT DO NOTHING) and
        # the subscription row is unchanged (the handler short-circuited).
        assert first_processed == second_processed == 1
        assert first_row == second_row

    def test_distinct_event_ids_processed_independently(self, engine, svc):
        """Two checkout completions for the same tenant produce idempotent rows."""
        cust = "cus_distinct"
        tenant = "tenant-1"

        svc.handle_webhook_event(
            _checkout_completed(tenant, cust, mode="subscription"),
            sig_header="x",
        )
        svc.handle_webhook_event(
            _checkout_completed(tenant, cust, mode="subscription"),
            sig_header="x",
        )

        # Two distinct events recorded.
        assert _processed_count(engine) == 2
        # But the billing row UNIQUE on tenant_id is one row.
        from sqlalchemy import text

        with engine.connect() as conn:
            n = conn.execute(
                text("SELECT COUNT(*) FROM billing_subscriptions WHERE tenant_id = :tid"),
                {"tid": tenant},
            ).scalar()
        assert n == 1


class TestSkippedEvents:
    def test_non_subscription_checkout_session_skipped(self, engine, svc):
        """One-off payment / setup mode checkout sessions don't link a tenant."""
        svc.handle_webhook_event(
            _checkout_completed("tenant-1", "cus_oneoff", mode="payment"),
            sig_header="x",
        )
        # No row written — _link_checkout_session early-returned on mode != subscription.
        assert _row(engine, "tenant-1") is None

    def test_unknown_event_type_marked_processed_but_no_state_change(self, engine, svc):
        """An event type the handler does not know about is recorded for
        idempotency but produces no DB writes elsewhere."""
        svc.handle_webhook_event(
            _ev("customer.discount.created", {"id": "di_x", "customer": "cus_x"}),
            sig_header="x",
        )
        assert _processed_count(engine) == 1
        assert _row(engine, "tenant-1") is None

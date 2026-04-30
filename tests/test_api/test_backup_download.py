# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Phase 6.6 #5 — GET /v1/governance/backup/download tests.

Three gates:
  1. RBAC — owner-only (governance:backup_download via _OWNER_PERMS wildcard).
  2. Tier — Team / Business / Enterprise allowed; Developer / Pro / sandbox 402.
  3. Rate limit — 1 successful download / 24 h / tenant; subsequent 429.

Plus the streaming envelope (header / row / footer) + audit log entry +
tenant-scope isolation.

The endpoint requires a SQLAlchemy engine on app.state.auth_engine. Tests
fake it with a MagicMock that records SQL calls so we can assert the
right rows are inserted into ``backup_download_log`` without a real
PostgreSQL container.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engramia import Memory
from engramia.api.auth import require_auth
from engramia.api.governance import router as gov_router
from engramia.billing.models import BillingSubscription
from engramia.providers.json_storage import JSONStorage
from tests.conftest import FakeEmbeddings
from tests.factories import make_auth_dep

pytestmark = pytest.mark.security


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_engine_for_backup(
    *,
    last_success_at: datetime | None = None,
    rows_per_table: int = 0,
):
    """Build a MagicMock engine that satisfies the backup endpoint's SQL.

    The endpoint does three things via the engine:

    1. SELECT requested_at FROM backup_download_log ... LIMIT 1
       — rate-limit lookup. Returns ``last_success_at`` (or None).
    2. SELECT ... FROM <each table> WHERE tenant_id = :tid
       — the streaming export. We return ``rows_per_table`` synthetic rows
       per table so the footer arrives with realistic counts.
    3. INSERT INTO backup_download_log ...
       — final outcome row. Captured for assertions.
    """
    engine = MagicMock()
    insert_calls: list[dict] = []

    def _connect():
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)

        def _execute(stmt, params=None):
            sql = str(stmt)
            result = MagicMock()
            if "SELECT requested_at" in sql:
                if last_success_at is not None:
                    result.fetchone = MagicMock(return_value=(last_success_at,))
                else:
                    result.fetchone = MagicMock(return_value=None)
                return result
            if "INSERT INTO backup_download_log" in sql:
                insert_calls.append(dict(params or {}))
                return result
            # Treat all other SELECTs as the export path. Each returns
            # ``rows_per_table`` row mocks. Iteration over MagicMock returns
            # rows directly.
            rows = []
            for i in range(rows_per_table):
                row = MagicMock()
                row._mapping = {"col": f"v{i}", "tenant_id": params.get("tid")}
                rows.append(row)
            result.__iter__ = lambda self: iter(rows)
            return result

        conn.execute = MagicMock(side_effect=_execute)
        # execution_options returns the same conn for chaining
        conn.execution_options = MagicMock(return_value=conn)
        return conn

    engine.connect = MagicMock(side_effect=_connect)
    engine.begin = MagicMock(side_effect=_connect)
    engine.insert_calls = insert_calls  # exposed for asserts
    return engine


def _fake_billing_service(plan_tier: str):
    """BillingService stub returning a subscription with the given plan_tier."""
    svc = MagicMock()
    svc.get_subscription = MagicMock(
        return_value=BillingSubscription(
            tenant_id="tenant-a",
            plan_tier=plan_tier,
            billing_interval="month",
            status="active",
        )
    )
    return svc


def _make_app(
    *,
    role: str = "owner",
    tenant_id: str = "tenant-a",
    plan_tier: str = "team",
    last_success_at: datetime | None = None,
    rows_per_table: int = 0,
    no_engine: bool = False,
):
    app = FastAPI()
    mem = Memory(embeddings=FakeEmbeddings(), storage=JSONStorage(path="/tmp/engramia-test"))
    app.state.memory = mem
    app.state.auth_engine = (
        None
        if no_engine
        else _fake_engine_for_backup(
            last_success_at=last_success_at, rows_per_table=rows_per_table
        )
    )
    app.state.billing_service = _fake_billing_service(plan_tier)
    app.dependency_overrides[require_auth] = make_auth_dep(
        role=role, tenant_id=tenant_id, project_id="proj-a"
    )
    app.include_router(gov_router, prefix="/v1")
    return app


def _client(**kwargs) -> TestClient:
    return TestClient(_make_app(**kwargs))


# ---------------------------------------------------------------------------
# RBAC gate — owner only
# ---------------------------------------------------------------------------


class TestRBAC:
    def test_reader_forbidden(self):
        resp = _client(role="reader").get("/v1/governance/backup/download")
        assert resp.status_code == 403
        assert "governance:backup_download" in resp.json()["detail"]

    def test_editor_forbidden(self):
        resp = _client(role="editor").get("/v1/governance/backup/download")
        assert resp.status_code == 403

    def test_admin_forbidden(self):
        """Admin can manage credentials but cannot pull a full tenant dump.
        Backup is the most sensitive read; only owner has it."""
        resp = _client(role="admin").get("/v1/governance/backup/download")
        assert resp.status_code == 403

    def test_owner_allowed(self):
        resp = _client(role="owner").get("/v1/governance/backup/download")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tier gate — Team+ only
# ---------------------------------------------------------------------------


class TestTierGate:
    @pytest.mark.parametrize("plan", ["developer", "sandbox", "pro"])
    def test_lower_tiers_get_402(self, plan):
        resp = _client(role="owner", plan_tier=plan).get("/v1/governance/backup/download")
        assert resp.status_code == 402
        body = resp.json()
        assert body["detail"]["error_code"] == "TIER_UPGRADE_REQUIRED"
        assert body["detail"]["current_tier"] == plan
        assert body["detail"]["min_tier"] == "team"

    @pytest.mark.parametrize("plan", ["team", "business", "enterprise"])
    def test_team_and_above_allowed(self, plan):
        resp = _client(role="owner", plan_tier=plan).get("/v1/governance/backup/download")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Rate limit — 1 / 24 h / tenant
# ---------------------------------------------------------------------------


class TestRateLimit:
    def test_recent_success_blocks_with_429(self):
        recent = datetime.now(UTC) - timedelta(hours=2)
        resp = _client(role="owner", last_success_at=recent).get(
            "/v1/governance/backup/download"
        )
        assert resp.status_code == 429
        body = resp.json()
        assert body["detail"]["error_code"] == "BACKUP_RATE_LIMITED"
        assert body["detail"]["retry_after"] > 0
        # Retry-After header reflects the same value
        assert int(resp.headers["Retry-After"]) > 0

    def test_old_success_allows_new_download(self):
        old = datetime.now(UTC) - timedelta(hours=25)
        resp = _client(role="owner", last_success_at=old).get(
            "/v1/governance/backup/download"
        )
        assert resp.status_code == 200

    def test_first_download_allowed_with_no_history(self):
        resp = _client(role="owner", last_success_at=None).get(
            "/v1/governance/backup/download"
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Streaming envelope shape — header / row / footer
# ---------------------------------------------------------------------------


class TestStreamingEnvelope:
    def test_response_is_ndjson_with_header_and_footer(self):
        import json

        resp = _client(role="owner", rows_per_table=2).get("/v1/governance/backup/download")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/x-ndjson")
        assert "attachment" in resp.headers["content-disposition"]

        lines = [line for line in resp.text.split("\n") if line]
        # Each line is valid JSON
        envelopes = [json.loads(line) for line in lines]
        # First envelope is the header, last is the footer.
        assert envelopes[0]["kind"] == "header"
        assert envelopes[0]["tenant_id"] == "tenant-a"
        assert envelopes[-1]["kind"] == "footer"
        # Row envelopes between
        row_envelopes = [e for e in envelopes if e["kind"] == "row"]
        assert len(row_envelopes) > 0
        for row in row_envelopes:
            assert "table" in row
            assert "data" in row

    def test_filename_includes_tenant_prefix(self):
        resp = _client(role="owner", tenant_id="tenant-abcdefgh").get(
            "/v1/governance/backup/download"
        )
        # Filename must include the tenant prefix (first 8 chars) for ops triage
        cd = resp.headers["content-disposition"]
        assert "tenant-a" in cd  # first 8 of tenant-abcdefgh

    def test_no_caching_headers(self):
        """Backup is sensitive — must never be cached by intermediaries."""
        resp = _client(role="owner").get("/v1/governance/backup/download")
        assert resp.headers.get("cache-control") == "no-store"


# ---------------------------------------------------------------------------
# Audit + accounting — INSERT INTO backup_download_log
# ---------------------------------------------------------------------------


class TestAuditTrail:
    def test_successful_download_logs_success_row(self):
        app = _make_app(role="owner", rows_per_table=1)
        client = TestClient(app)
        resp = client.get("/v1/governance/backup/download")
        # Force the response stream to drain so the finally block runs.
        _ = resp.text
        engine = app.state.auth_engine
        success_inserts = [
            call for call in engine.insert_calls if call.get("st") == "success"
        ]
        assert len(success_inserts) == 1
        ins = success_inserts[0]
        assert ins["tid"] == "tenant-a"
        assert ins["bs"] > 0  # bytes_streamed > 0
        assert ins["tc"] >= 0  # tables_exported


# ---------------------------------------------------------------------------
# 503 when no DB engine (JSON storage mode)
# ---------------------------------------------------------------------------


class TestNoEngine:
    def test_503_when_no_db_engine(self):
        resp = _client(role="owner", no_engine=True).get("/v1/governance/backup/download")
        assert resp.status_code == 503
        assert "DB-backed storage" in resp.json()["detail"]

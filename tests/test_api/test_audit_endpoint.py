# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for GET /v1/audit (Phase 6.0 — audit log viewer).

Covers:
- RBAC: reader / editor get 403 (audit:read is admin+)
- 503 when no DB engine is configured (JSON storage deployments)
- Scope isolation: tenant A's rows are invisible to tenant B
- Filtering: action, actor, since, until
- Pagination: cursor semantics (until) + total count reflects filters
- Response shape: resource_type + resource_id, structured detail dict

DB is emulated with a temporary SQLite engine + minimal audit_log table —
same schema shape Alembic produces on Postgres, but with SQLite types so
the suite runs without Docker.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from engramia import Memory
from engramia.api.auth import require_auth
from engramia.api.routes import router as core_router
from engramia.providers.json_storage import JSONStorage
from tests.conftest import FakeEmbeddings
from tests.factories import make_auth_dep

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def audit_engine():
    """In-memory SQLite with a schema compatible with the /audit query.

    Only the columns the endpoint reads are modelled. JSON columns are TEXT
    because SQLite doesn't have native JSONB — the endpoint reads `detail`
    as a string on SQLite, which we parse manually in the fixture seed.
    """
    # StaticPool + shared cache so every checkout returns the SAME connection
    # — required because SQLite :memory: is per-connection by default.
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    key_id TEXT,
                    action TEXT NOT NULL,
                    resource_type TEXT,
                    resource_id TEXT,
                    ip_address TEXT,
                    created_at TEXT NOT NULL,
                    detail TEXT
                )
                """
            )
        )
    return engine


def _seed(engine, rows: list[dict]) -> None:
    with engine.begin() as conn:
        for r in rows:
            conn.execute(
                text(
                    "INSERT INTO audit_log "
                    "(tenant_id, project_id, key_id, action, resource_type, resource_id, "
                    " ip_address, created_at, detail) "
                    "VALUES (:tenant_id, :project_id, :key_id, :action, :resource_type, "
                    " :resource_id, :ip_address, :created_at, :detail)"
                ),
                {
                    "tenant_id": r.get("tenant_id", "tenant-a"),
                    "project_id": r.get("project_id", "proj-a"),
                    "key_id": r.get("key_id"),
                    "action": r["action"],
                    "resource_type": r.get("resource_type"),
                    "resource_id": r.get("resource_id"),
                    "ip_address": r.get("ip"),
                    "created_at": r["created_at"],
                    "detail": json.dumps(r["detail"]) if r.get("detail") else None,
                },
            )


def _make_app(
    engine,
    *,
    role: str = "admin",
    tenant_id: str = "tenant-a",
    project_id: str = "proj-a",
    tmp_path=None,
) -> FastAPI:
    """Core-router app with an SQLite audit engine and a real AuthContext."""
    app = FastAPI()
    mem = Memory(embeddings=FakeEmbeddings(), storage=JSONStorage(path=tmp_path))
    app.state.memory = mem
    app.state.auth_engine = engine

    app.dependency_overrides[require_auth] = make_auth_dep(
        role=role,
        tenant_id=tenant_id,
        project_id=project_id,
        key_id="key-admin-1",
    )
    app.include_router(core_router, prefix="/v1")
    return app


def _client(engine, role="admin", **kwargs) -> TestClient:
    return TestClient(_make_app(engine, role=role, **kwargs))


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


class TestAuditRBAC:
    def test_reader_cannot_read_audit(self, audit_engine, tmp_path):
        resp = _client(audit_engine, role="reader", tmp_path=tmp_path).get("/v1/audit")
        assert resp.status_code == 403
        assert "audit:read" in resp.json()["detail"]

    def test_editor_cannot_read_audit(self, audit_engine, tmp_path):
        resp = _client(audit_engine, role="editor", tmp_path=tmp_path).get("/v1/audit")
        assert resp.status_code == 403

    def test_admin_can_read_audit(self, audit_engine, tmp_path):
        resp = _client(audit_engine, role="admin", tmp_path=tmp_path).get("/v1/audit")
        assert resp.status_code == 200

    def test_owner_can_read_audit(self, audit_engine, tmp_path):
        resp = _client(audit_engine, role="owner", tmp_path=tmp_path).get("/v1/audit")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Degradation: 503 without DB
# ---------------------------------------------------------------------------


class TestAuditNoDB:
    def test_503_when_no_auth_engine(self, tmp_path):
        app = FastAPI()
        mem = Memory(embeddings=FakeEmbeddings(), storage=JSONStorage(path=tmp_path))
        app.state.memory = mem
        app.state.auth_engine = None  # JSON-storage deployment

        app.dependency_overrides[require_auth] = make_auth_dep(role="admin")
        app.include_router(core_router, prefix="/v1")

        resp = TestClient(app).get("/v1/audit")
        assert resp.status_code == 503
        assert resp.json()["detail"]["error_code"] == "SERVICE_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Scope isolation
# ---------------------------------------------------------------------------


class TestAuditScopeIsolation:
    def test_only_own_tenant_rows_returned(self, audit_engine, tmp_path):
        _seed(
            audit_engine,
            [
                {"tenant_id": "tenant-a", "project_id": "proj-a", "action": "learn", "created_at": "2026-04-11T10:00:00Z"},
                {"tenant_id": "tenant-b", "project_id": "proj-b", "action": "learn", "created_at": "2026-04-11T10:01:00Z"},
                {"tenant_id": "tenant-a", "project_id": "proj-a", "action": "pattern_deleted", "created_at": "2026-04-11T10:02:00Z"},
            ],
        )

        resp = _client(audit_engine, tenant_id="tenant-a", project_id="proj-a", tmp_path=tmp_path).get("/v1/audit")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        actions = {e["action"] for e in body["events"]}
        assert actions == {"learn", "pattern_deleted"}

    def test_cross_project_not_returned(self, audit_engine, tmp_path):
        _seed(
            audit_engine,
            [
                {"tenant_id": "tenant-a", "project_id": "proj-a", "action": "learn", "created_at": "2026-04-11T10:00:00Z"},
                {"tenant_id": "tenant-a", "project_id": "proj-other", "action": "learn", "created_at": "2026-04-11T10:01:00Z"},
            ],
        )
        resp = _client(audit_engine, tenant_id="tenant-a", project_id="proj-a", tmp_path=tmp_path).get("/v1/audit")
        body = resp.json()
        assert body["total"] == 1


# ---------------------------------------------------------------------------
# Filters + ordering + pagination
# ---------------------------------------------------------------------------


class TestAuditFilters:
    @pytest.fixture
    def seeded_engine(self, audit_engine):
        _seed(
            audit_engine,
            [
                {"action": "learn", "key_id": "key-1", "created_at": "2026-04-11T10:00:00Z"},
                {"action": "pattern_deleted", "key_id": "key-1", "created_at": "2026-04-11T11:00:00Z",
                 "resource_type": "pattern", "resource_id": "patterns/abc"},
                {"action": "key_created", "key_id": "key-admin", "created_at": "2026-04-11T12:00:00Z"},
                {"action": "learn", "key_id": "key-2", "created_at": "2026-04-11T13:00:00Z",
                 "detail": {"eval_score": 8.5}},
                {"action": "key_revoked", "key_id": "key-admin", "created_at": "2026-04-11T14:00:00Z"},
            ],
        )
        return audit_engine

    def test_default_order_is_newest_first(self, seeded_engine, tmp_path):
        resp = _client(seeded_engine, tmp_path=tmp_path).get("/v1/audit")
        events = resp.json()["events"]
        timestamps = [e["timestamp"] for e in events]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_action_filter(self, seeded_engine, tmp_path):
        resp = _client(seeded_engine, tmp_path=tmp_path).get("/v1/audit?action=learn")
        body = resp.json()
        assert body["total"] == 2
        assert all(e["action"] == "learn" for e in body["events"])

    def test_actor_filter(self, seeded_engine, tmp_path):
        resp = _client(seeded_engine, tmp_path=tmp_path).get("/v1/audit?actor=key-admin")
        body = resp.json()
        assert body["total"] == 2
        assert all(e["actor"] == "key-admin" for e in body["events"])

    def test_since_filter(self, seeded_engine, tmp_path):
        resp = _client(seeded_engine, tmp_path=tmp_path).get("/v1/audit?since=2026-04-11T12:00:00Z")
        body = resp.json()
        # Events at 12:00, 13:00, 14:00 match (>=).
        assert body["total"] == 3

    def test_until_filter_for_cursor_pagination(self, seeded_engine, tmp_path):
        resp = _client(seeded_engine, tmp_path=tmp_path).get("/v1/audit?until=2026-04-11T12:00:00Z")
        body = resp.json()
        # Events at 10:00 and 11:00 match (<).
        assert body["total"] == 2

    def test_limit_does_not_affect_total(self, seeded_engine, tmp_path):
        resp = _client(seeded_engine, tmp_path=tmp_path).get("/v1/audit?limit=1")
        body = resp.json()
        assert len(body["events"]) == 1
        assert body["total"] == 5  # full count regardless of limit slice

    def test_limit_out_of_range_rejected(self, seeded_engine, tmp_path):
        resp = _client(seeded_engine, tmp_path=tmp_path).get("/v1/audit?limit=0")
        assert resp.status_code == 422
        resp = _client(seeded_engine, tmp_path=tmp_path).get("/v1/audit?limit=1001")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


class TestAuditResponseShape:
    def test_resource_type_and_id_are_separate_fields(self, audit_engine, tmp_path):
        _seed(
            audit_engine,
            [
                {
                    "action": "pattern_deleted",
                    "key_id": "key-1",
                    "resource_type": "pattern",
                    "resource_id": "patterns/abc123",
                    "ip": "10.0.0.1",
                    "created_at": "2026-04-11T10:00:00Z",
                },
            ],
        )
        resp = _client(audit_engine, tmp_path=tmp_path).get("/v1/audit")
        ev = resp.json()["events"][0]
        assert ev["resource_type"] == "pattern"
        assert ev["resource_id"] == "patterns/abc123"
        assert ev["ip"] == "10.0.0.1"
        assert ev["actor"] == "key-1"

    def test_detail_is_dict_or_none(self, audit_engine, tmp_path):
        _seed(
            audit_engine,
            [
                {"action": "learn", "detail": {"pattern_key": "patterns/xyz", "score": 8.5},
                 "created_at": "2026-04-11T10:00:00Z"},
                {"action": "health_check", "created_at": "2026-04-11T11:00:00Z"},
            ],
        )
        resp = _client(audit_engine, tmp_path=tmp_path).get("/v1/audit")
        events = resp.json()["events"]
        by_action = {e["action"]: e for e in events}
        assert by_action["learn"]["detail"] == {"pattern_key": "patterns/xyz", "score": 8.5}
        assert by_action["health_check"]["detail"] is None


# ---------------------------------------------------------------------------
# End-to-end: empty result
# ---------------------------------------------------------------------------


def test_empty_audit_log_returns_empty_events(audit_engine, tmp_path):
    resp = _client(audit_engine, tmp_path=tmp_path).get("/v1/audit")
    assert resp.status_code == 200
    assert resp.json() == {"events": [], "total": 0}


# Silence unused-import warning on ``time`` if Python's linter gets picky —
# kept for potential future sleep-based tests.
_ = time

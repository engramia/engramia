# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Regression tests for the Admin Dashboard audit viewer.

Specifically guards the ``audit_log.created_at`` parsing path: the column is
``TEXT`` populated via PostgreSQL's ``now()::text`` (see
``engramia/api/audit.py``), which renders ``YYYY-MM-DD HH:MM:SS.ffffff+TT`` —
a two-digit offset without colon. Pydantic v2's strict RFC 3339 datetime
parser rejects that shape, so the endpoint pre-parses via
``_parse_audit_timestamp`` before constructing the response model. Without
that pre-parse, every ``GET /v1/admin/audit`` against real PostgreSQL data
returns 422 "Invalid request parameters." — the defect this file pins.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from engramia.admin_auth.service import AdminAuthService
from engramia.api.admin.audit_viewer import router as audit_router
from engramia.api.admin.deps import (
    AdminContext,
    get_admin_auth_service,
    require_super_admin,
)


@pytest.fixture
def audit_engine():
    """SQLite engine with the audit_log columns the viewer reads.

    Mirrors the migration-031 schema shape — the columns matter, not their
    Postgres-specific types.
    """
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
                    project_id TEXT,
                    key_id TEXT,
                    actor_user_id TEXT,
                    action TEXT NOT NULL,
                    resource_type TEXT,
                    resource_id TEXT,
                    ip_address TEXT,
                    detail TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
    return engine


def _seed(engine, *, created_at: str, action: str = "auth.login") -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_log "
                "(tenant_id, project_id, action, created_at) "
                "VALUES ('tenant-a', 'proj-a', :action, :created_at)"
            ),
            {"action": action, "created_at": created_at},
        )


def _client(engine) -> TestClient:
    app = FastAPI()
    app.state.auth_engine = engine
    app.include_router(audit_router, prefix="/v1")

    fake_ctx = AdminContext(
        admin_user_id=1,
        session_id="session-1",
        totp_issued_at=0,
        request_ip="127.0.0.1",
    )
    app.dependency_overrides[require_super_admin] = lambda: fake_ctx
    app.dependency_overrides[get_admin_auth_service] = lambda: AdminAuthService(engine)
    return TestClient(app)


class TestTenantAuditTimestampParsing:
    """Regression for the 422 "Invalid request parameters." on staging."""

    def test_pg_now_text_offset_without_colon_is_accepted(self, audit_engine):
        # The exact shape PostgreSQL's ``now()::text`` produces.
        _seed(audit_engine, created_at="2026-05-11 22:16:25.123456+00")

        resp = _client(audit_engine).get("/v1/admin/audit")

        assert resp.status_code == 200, resp.json()
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["action"] == "auth.login"
        # Normalised to RFC 3339 with extended offset in the JSON response.
        assert body["items"][0]["created_at"].startswith("2026-05-11T22:16:25")

    def test_iso_t_separator_still_works(self, audit_engine):
        # Test seed format used elsewhere — must remain accepted.
        _seed(audit_engine, created_at="2026-05-11T22:16:25Z")

        resp = _client(audit_engine).get("/v1/admin/audit")

        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_empty_audit_log_returns_zero_total(self, audit_engine):
        resp = _client(audit_engine).get("/v1/admin/audit")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}

    def test_single_row_detail_endpoint_also_parses(self, audit_engine):
        _seed(audit_engine, created_at="2026-05-11 22:16:25.123456+00")
        resp = _client(audit_engine).get("/v1/admin/audit/1")
        assert resp.status_code == 200
        assert resp.json()["created_at"].startswith("2026-05-11T22:16:25")

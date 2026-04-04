# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for api/analytics.py — ROI Analytics endpoints (Phase 5.7).

Uses in-memory JSONStorage + FakeEmbeddings; no external services required.

Auth is injected via ``app.dependency_overrides[require_auth]`` — the same
pattern used by the real dependency (sets request.state.auth_context), which
guarantees scope contextvar propagation without relying on BaseHTTPMiddleware.
"""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engramia import Memory
from engramia.api.analytics import router as analytics_router
from engramia.api.auth import require_auth
from engramia.providers.json_storage import JSONStorage
from tests.conftest import FakeEmbeddings
from tests.factories import make_auth_dep

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mem(tmp_path):
    return Memory(embeddings=FakeEmbeddings(), storage=JSONStorage(path=tmp_path))


def _make_app(mem: Memory, role: str = "editor") -> FastAPI:
    """Build a test app with analytics router.

    Auth is provided via dependency_overrides so that:
    - require_auth is fully bypassed (no env-var or DB lookup)
    - request.state.auth_context is set with the requested role
    - scope contextvar is propagated correctly (same path as production auth)

    Default scope matches env-var auth mode (tenant_id='default', project_id='default').
    """
    app = FastAPI()
    app.include_router(analytics_router, prefix="/v1")
    app.state.memory = mem

    app.dependency_overrides[require_auth] = make_auth_dep(role=role)
    return app


# ---------------------------------------------------------------------------
# GET /v1/analytics/events
# ---------------------------------------------------------------------------


class TestGetEvents:
    def test_returns_empty_list_when_no_events(self, mem):
        app = _make_app(mem)
        client = TestClient(app)
        resp = client.get("/v1/analytics/events")
        assert resp.status_code == 200
        body = resp.json()
        assert body["events"] == []
        assert body["total"] == 0

    def test_returns_events_after_learn(self, mem):
        mem.learn(task="sort a list", code="sorted(lst)", eval_score=8.0)
        app = _make_app(mem)
        client = TestClient(app)
        resp = client.get("/v1/analytics/events")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1

    def test_limit_param_respected(self, mem):
        for i in range(5):
            mem.learn(task=f"task {i}", code=f"code_{i}()", eval_score=7.0)
        app = _make_app(mem)
        client = TestClient(app)
        resp = client.get("/v1/analytics/events?limit=2")
        assert resp.status_code == 200
        assert len(resp.json()["events"]) <= 2

    def test_since_param_filters_old_events(self, mem):
        mem.learn(task="old task", code="old()", eval_score=6.0)
        future_ts = time.time() + 3600
        app = _make_app(mem)
        client = TestClient(app)
        resp = client.get(f"/v1/analytics/events?since={future_ts}")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_reader_role_allowed(self, mem):
        app = _make_app(mem, role="reader")
        client = TestClient(app)
        resp = client.get("/v1/analytics/events")
        assert resp.status_code == 200

    def test_invalid_limit_returns_422(self, mem):
        app = _make_app(mem)
        client = TestClient(app)
        resp = client.get("/v1/analytics/events?limit=0")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /v1/analytics/rollup
# ---------------------------------------------------------------------------


class TestTriggerRollup:
    def test_rollup_hourly_returns_200(self, mem):
        mem.learn(task="compute sum", code="sum(lst)", eval_score=9.0)
        app = _make_app(mem, role="editor")
        client = TestClient(app)
        resp = client.post("/v1/analytics/rollup", json={"window": "hourly"})
        assert resp.status_code == 200
        body = resp.json()
        assert "window" in body
        assert body["window"] == "hourly"

    def test_rollup_daily_returns_200(self, mem):
        app = _make_app(mem, role="editor")
        client = TestClient(app)
        resp = client.post("/v1/analytics/rollup", json={"window": "daily"})
        assert resp.status_code == 200

    def test_rollup_invalid_window_returns_422(self, mem):
        app = _make_app(mem, role="editor")
        client = TestClient(app)
        resp = client.post("/v1/analytics/rollup", json={"window": "decadely"})
        assert resp.status_code == 422

    def test_reader_cannot_trigger_rollup(self, mem):
        app = _make_app(mem, role="reader")
        client = TestClient(app)
        resp = client.post("/v1/analytics/rollup", json={"window": "hourly"})
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /v1/analytics/rollup/{window}
# ---------------------------------------------------------------------------


class TestGetRollup:
    def test_returns_404_when_no_rollup_computed(self, mem):
        app = _make_app(mem)
        client = TestClient(app)
        resp = client.get("/v1/analytics/rollup/daily")
        assert resp.status_code == 404

    def test_returns_200_with_body_after_trigger(self, mem):
        """Trigger computes a rollup; GET must return 200 and a valid body.

        Both learn() and the API requests share default scope (env-var auth
        mode), so the rollup is visible to the same scope that GET uses.
        """
        mem.learn(task="filter items", code="[x for x in lst if x]", eval_score=8.5)
        app = _make_app(mem, role="editor")
        client = TestClient(app)

        trigger = client.post("/v1/analytics/rollup", json={"window": "hourly"})
        assert trigger.status_code == 200

        resp = client.get("/v1/analytics/rollup/hourly")
        assert resp.status_code == 200
        body = resp.json()
        assert body["window"] == "hourly"
        assert body["learn"]["total"] == 1
        assert 0.0 <= body["roi_score"] <= 10.0

    def test_invalid_window_returns_422(self, mem):
        app = _make_app(mem)
        client = TestClient(app)
        resp = client.get("/v1/analytics/rollup/quarterly")
        assert resp.status_code == 422

    def test_reader_can_read_rollup(self, mem):
        """Reader role must be able to read rollups (no 403/401/500).

        404 is expected when no rollup has been computed yet — that is a
        data-existence issue, not a permissions issue.
        """
        mem.learn(task="reader test task", code="x()", eval_score=7.0)
        editor_app = _make_app(mem, role="editor")
        editor_client = TestClient(editor_app)
        trigger = editor_client.post("/v1/analytics/rollup", json={"window": "daily"})
        assert trigger.status_code == 200

        reader_app = _make_app(mem, role="reader")
        reader_client = TestClient(reader_app)
        resp = reader_client.get("/v1/analytics/rollup/daily")
        assert resp.status_code == 200
        assert resp.json()["window"] == "daily"

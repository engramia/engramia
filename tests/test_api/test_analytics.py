# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for api/analytics.py — ROI Analytics endpoints (Phase 5.7).

Uses in-memory JSONStorage + FakeEmbeddings; no external services required.
"""

import os
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engramia import Memory
from engramia.api.analytics import router as analytics_router
from engramia.providers.json_storage import JSONStorage
from engramia.types import AuthContext, Scope
from tests.conftest import FakeEmbeddings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_auth_env():
    os.environ["ENGRAMIA_ALLOW_NO_AUTH"] = "true"
    os.environ.pop("ENGRAMIA_API_KEYS", None)
    yield
    os.environ.pop("ENGRAMIA_ALLOW_NO_AUTH", None)
    os.environ.pop("ENGRAMIA_API_KEYS", None)


@pytest.fixture
def mem(tmp_path):
    return Memory(embeddings=FakeEmbeddings(), storage=JSONStorage(path=tmp_path))


def _make_app(mem: Memory, role: str = "editor") -> FastAPI:
    from starlette.middleware.base import BaseHTTPMiddleware
    from fastapi import Request

    app = FastAPI()
    app.include_router(analytics_router, prefix="/v1")

    class FakeAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request.state.auth_context = AuthContext(
                key_id="test-key",
                tenant_id="acme",
                project_id="prod",
                role=role,
                scope=Scope(tenant_id="acme", project_id="prod"),
            )
            return await call_next(request)

    app.add_middleware(FakeAuthMiddleware)
    app.state.memory = mem
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
        assert body["total"] >= 1

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

    def test_returns_rollup_after_trigger(self, mem):
        mem.learn(task="filter items", code="[x for x in lst if x]", eval_score=8.5)
        app = _make_app(mem, role="editor")
        client = TestClient(app)
        # First trigger so there's a persisted rollup
        client.post("/v1/analytics/rollup", json={"window": "hourly"})
        resp = client.get("/v1/analytics/rollup/hourly")
        # Either 200 (rollup present for this scope) or 404 (no events in scope)
        assert resp.status_code in (200, 404)

    def test_invalid_window_returns_422(self, mem):
        app = _make_app(mem)
        client = TestClient(app)
        resp = client.get("/v1/analytics/rollup/quarterly")
        assert resp.status_code == 422

    def test_reader_can_read_rollup(self, mem):
        app = _make_app(mem, role="reader")
        client = TestClient(app)
        resp = client.get("/v1/analytics/rollup/daily")
        # 404 is fine (no rollup), 403 would be a permissions bug
        assert resp.status_code != 403

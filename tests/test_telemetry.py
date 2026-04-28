# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for engramia/telemetry — Phase 5.5."""

import uuid

import pytest
from starlette.testclient import TestClient

from engramia.telemetry.context import get_request_id, reset_request_id, set_request_id

# ---------------------------------------------------------------------------
# telemetry/context
# ---------------------------------------------------------------------------


class TestRequestIDContext:
    def test_default_is_empty(self):
        assert get_request_id() == ""

    def test_set_and_get(self):
        token = set_request_id("abc-123")
        try:
            assert get_request_id() == "abc-123"
        finally:
            reset_request_id(token)

    def test_reset_restores_previous(self):
        token1 = set_request_id("first")
        token2 = set_request_id("second")
        assert get_request_id() == "second"
        reset_request_id(token2)
        assert get_request_id() == "first"
        reset_request_id(token1)
        assert get_request_id() == ""


# ---------------------------------------------------------------------------
# telemetry/metrics
# ---------------------------------------------------------------------------


class TestMetricsInit:
    def test_disabled_by_default(self):
        from engramia.telemetry import metrics as m

        # metrics are not enabled unless init_metrics() is called
        # safe no-ops should not raise
        m.observe_request("GET", "/v1/health", 200, 0.01)
        m.observe_llm("openai", "gpt-4.1", 0.5)
        m.observe_embedding("openai", 0.1)
        m.observe_storage("json", "load", 0.001)
        m.set_pattern_count(42)
        m.inc_recall_hit()
        m.inc_recall_miss()
        m.inc_job_submitted("evaluate")
        m.inc_job_completed("evaluate", "completed")


# ---------------------------------------------------------------------------
# telemetry/tracing
# ---------------------------------------------------------------------------


class TestTracingDecorator:
    def test_traced_passthrough_when_disabled(self):
        from engramia.telemetry.tracing import traced

        @traced("test.span")
        def add(a, b):
            return a + b

        assert add(2, 3) == 5

    def test_traced_propagates_exception(self):
        from engramia.telemetry.tracing import traced

        @traced("test.span")
        def boom():
            raise ValueError("intentional")

        with pytest.raises(ValueError, match="intentional"):
            boom()

    def test_noop_tracer(self):
        from engramia.telemetry.tracing import _NoOpTracer

        tracer = _NoOpTracer()
        with tracer.start_as_current_span("foo") as span:
            span.set_attribute("k", "v")
            span.record_exception(ValueError("x"))
            span.set_status(None)


# ---------------------------------------------------------------------------
# telemetry/middleware (via ASGI TestClient)
# ---------------------------------------------------------------------------


@pytest.fixture()
def mini_app():
    """Minimal FastAPI app with RequestIDMiddleware and TimingMiddleware."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    from engramia.telemetry.middleware import RequestIDMiddleware, TimingMiddleware

    app = FastAPI()
    app.add_middleware(TimingMiddleware)
    app.add_middleware(RequestIDMiddleware)

    @app.get("/ping")
    def ping():
        return JSONResponse({"pong": True})

    return app


class TestRequestIDMiddleware:
    def test_generates_request_id(self, mini_app):
        client = TestClient(mini_app)
        resp = client.get("/ping")
        assert resp.status_code == 200
        assert "x-request-id" in resp.headers
        rid = resp.headers["x-request-id"]
        # Should be a valid UUID4
        uuid.UUID(rid, version=4)

    def test_echoes_caller_supplied_request_id(self, mini_app):
        client = TestClient(mini_app)
        my_id = "my-custom-id-123"
        resp = client.get("/ping", headers={"X-Request-ID": my_id})
        assert resp.headers["x-request-id"] == my_id

    def test_timing_middleware_does_not_crash(self, mini_app):
        client = TestClient(mini_app)
        resp = client.get("/ping")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# telemetry/health probes
# ---------------------------------------------------------------------------


class TestHealthProbes:
    def test_check_storage_json(self, tmp_path):
        from engramia.providers.json_storage import JSONStorage
        from engramia.telemetry.health import check_storage

        storage = JSONStorage(path=str(tmp_path))
        result = check_storage(storage)
        assert result["status"] == "ok"
        assert result["latency_ms"] >= 0

    def test_check_llm_none(self):
        from engramia.telemetry.health import check_llm

        result = check_llm(None)
        assert result["status"] == "not_configured"

    def test_check_embedding_none(self):
        from engramia.telemetry.health import check_embedding

        result = check_embedding(None)
        assert result["status"] == "not_configured"

    def test_check_llm_error(self):
        from unittest.mock import MagicMock

        from engramia.telemetry.health import check_llm

        bad_llm = MagicMock()
        bad_llm.call.side_effect = RuntimeError("no key")
        result = check_llm(bad_llm)
        assert result["status"] == "error"
        assert "no key" in result["error"]

    def test_check_embedding_error(self):
        from unittest.mock import MagicMock

        from engramia.telemetry.health import check_embedding

        bad_embed = MagicMock()
        bad_embed.embed.side_effect = RuntimeError("unreachable")
        result = check_embedding(bad_embed)
        assert result["status"] == "error"

    def test_aggregate_status_all_ok(self):
        from engramia.telemetry.health import aggregate_status

        checks = {
            "storage": {"status": "ok"},
            "llm": {"status": "ok"},
        }
        assert aggregate_status(checks) == "ok"

    def test_aggregate_status_one_error(self):
        from engramia.telemetry.health import aggregate_status

        checks = {
            "storage": {"status": "ok"},
            "llm": {"status": "error"},
        }
        assert aggregate_status(checks) == "degraded"

    def test_aggregate_status_all_error(self):
        from engramia.telemetry.health import aggregate_status

        checks = {
            "storage": {"status": "error"},
            "llm": {"status": "error"},
        }
        assert aggregate_status(checks) == "error"

    def test_aggregate_status_skips_not_configured(self):
        from engramia.telemetry.health import aggregate_status

        checks = {
            "storage": {"status": "ok"},
            "llm": {"status": "not_configured"},
        }
        assert aggregate_status(checks) == "ok"


# ---------------------------------------------------------------------------
# telemetry/setup (init functions are safe when deps missing)
# ---------------------------------------------------------------------------


class TestSetupTelemetry:
    def test_setup_does_not_raise(self, monkeypatch):
        """setup_telemetry() should never raise even with env flags set."""
        monkeypatch.setenv("ENGRAMIA_JSON_LOGS", "false")
        monkeypatch.setenv("ENGRAMIA_TELEMETRY", "false")
        monkeypatch.setenv("ENGRAMIA_METRICS", "false")

        from engramia.telemetry import setup_telemetry

        setup_telemetry()  # no exception


# ---------------------------------------------------------------------------
# Deep health endpoint via API
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAMIA_SKIP_AUTO_APP", "1")
    monkeypatch.setenv("ENGRAMIA_AUTH_MODE", "dev")
    monkeypatch.setenv("ENGRAMIA_ALLOW_NO_AUTH", "true")
    monkeypatch.setenv("ENGRAMIA_STORAGE", "json")
    monkeypatch.setenv("ENGRAMIA_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("ENGRAMIA_LLM_PROVIDER", "none")

    # Patch make_embeddings and make_llm to avoid needing real API keys
    from unittest.mock import MagicMock

    import engramia._factory as factory

    mock_embeddings = MagicMock()
    mock_embeddings.embed.return_value = [0.1] * 1536
    mock_llm = MagicMock()
    mock_llm.call.return_value = "ok"

    monkeypatch.setattr(factory, "make_embeddings", lambda resolver=None: mock_embeddings)
    monkeypatch.setattr(factory, "make_llm", lambda resolver=None: mock_llm)

    from engramia.api.app import create_app

    app = create_app()
    return TestClient(app)


class TestDeepHealthEndpoint:
    def test_health_deep_returns_200(self, api_client):
        resp = api_client.get("/v1/health/deep")
        assert resp.status_code in (200, 503)
        body = resp.json()
        assert "status" in body
        assert "checks" in body
        assert "storage" in body["checks"]

    def test_health_deep_has_uptime(self, api_client):
        resp = api_client.get("/v1/health/deep")
        body = resp.json()
        assert body["uptime_seconds"] >= 0

    def test_health_deep_has_version(self, api_client):
        resp = api_client.get("/v1/health/deep")
        body = resp.json()
        assert "version" in body

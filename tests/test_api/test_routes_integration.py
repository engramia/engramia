# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Integration tests for the full FastAPI app created via create_app().

These tests exercise the COMPLETE middleware stack that production traffic
goes through — the layer that unit tests in test_routes.py deliberately skip:

  CORS → MaintenanceModeMiddleware → SecurityHeadersMiddleware
  → TimingMiddleware → RequestIDMiddleware
  → BodySizeLimitMiddleware → RateLimitMiddleware → routes

Covers (P1-3, P2-4, P2-5, P2-6 from the audit):
- Security headers are present on every response
- BodySizeLimitMiddleware rejects oversized payloads (413)
- MaintenanceModeMiddleware returns 503 on non-health endpoints
- ValidationError responses are sanitized ("Validation error in request."),
  not raw str(exc) — production behaviour differs from unit test fixture

Fixture pattern copied from test_telemetry.py which is the only other file
that correctly uses create_app().
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import engramia._factory as factory

pytestmark = pytest.mark.integration

# app_client fixture is inherited from tests/conftest.py (create_app based)


# ---------------------------------------------------------------------------
# P2-6 — Error message sanitization
# ---------------------------------------------------------------------------


class TestErrorSanitization:
    def test_empty_task_returns_sanitized_422(self, app_client):
        """Production ValidationError handler returns a generic message.

        Unit tests in test_routes.py install a custom handler that returns
        str(exc) — a security risk. This test verifies that create_app()'s
        handler is sanitized.
        """
        resp = app_client.post(
            "/v1/learn",
            json={"task": "", "code": "import csv", "eval_score": 7.0},
        )
        assert resp.status_code == 422
        data = resp.json()
        # Production error format uses error_code / detail keys
        assert "error_code" in data
        assert data["error_code"] == "VALIDATION_ERROR"
        assert "detail" in data
        # Production returns a generic string, not the raw exception message
        assert data["detail"] in (
            "Validation error in request.",
            "Invalid request parameters.",
        )
        # Must NOT leak internal exception details
        assert "non-empty" not in data["detail"]
        assert "task" not in data["detail"]

    def test_invalid_eval_score_returns_422(self, app_client):
        """Pydantic validation (ge=0, le=10) must produce a 422."""
        resp = app_client.post(
            "/v1/learn",
            json={"task": "Parse CSV", "code": "import csv", "eval_score": 11.0},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# P2-4 — MaintenanceModeMiddleware
# ---------------------------------------------------------------------------


class TestMaintenanceMode:
    def test_maintenance_blocks_learn(self, app_client, monkeypatch):
        monkeypatch.setenv("ENGRAMIA_MAINTENANCE", "true")
        resp = app_client.post(
            "/v1/learn",
            json={"task": "Parse CSV", "code": "import csv", "eval_score": 7.0},
        )
        assert resp.status_code == 503
        data = resp.json()
        # Production error format uses error_code / detail keys
        assert "error_code" in data
        assert data["error_code"] == "SERVICE_UNAVAILABLE"
        assert "detail" in data
        assert "maintenance" in data["detail"].lower()
        assert "Retry-After" in resp.headers

    def test_maintenance_allows_health(self, app_client, monkeypatch):
        monkeypatch.setenv("ENGRAMIA_MAINTENANCE", "true")
        resp = app_client.get("/v1/health")
        assert resp.status_code == 200

    def test_maintenance_allows_health_deep(self, app_client, monkeypatch):
        monkeypatch.setenv("ENGRAMIA_MAINTENANCE", "true")
        resp = app_client.get("/v1/health/deep")
        # deep health is allowed through maintenance mode
        assert resp.status_code in (200, 503)
        # 503 here means storage is unhealthy — NOT maintenance rejection
        body = resp.json()
        if resp.status_code == 503:
            assert "maintenance" not in body.get("detail", "").lower()

    def test_no_maintenance_env_passes_normally(self, app_client, monkeypatch):
        monkeypatch.delenv("ENGRAMIA_MAINTENANCE", raising=False)
        resp = app_client.get("/v1/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# P2-5 — BodySizeLimitMiddleware
# ---------------------------------------------------------------------------


class TestBodySizeLimit:
    def test_oversized_body_returns_413(self, tmp_path, monkeypatch):
        """BodySizeLimitMiddleware must reject bodies larger than the configured max."""
        monkeypatch.setenv("ENGRAMIA_ALLOW_NO_AUTH", "true")
        monkeypatch.setenv("ENGRAMIA_AUTH_MODE", "dev")
        monkeypatch.setenv("ENGRAMIA_STORAGE", "json")
        monkeypatch.setenv("ENGRAMIA_DATA_PATH", str(tmp_path))
        monkeypatch.setenv("ENGRAMIA_LLM_PROVIDER", "none")
        monkeypatch.setenv("ENGRAMIA_SKIP_AUTO_APP", "1")
        monkeypatch.setenv("ENGRAMIA_MAX_BODY_SIZE", "50")  # 50 bytes — tiny

        mock_embeddings = MagicMock()
        mock_embeddings.embed.return_value = [0.1] * 1536
        monkeypatch.setattr(factory, "make_embeddings", lambda: mock_embeddings)
        monkeypatch.setattr(factory, "make_llm", lambda: MagicMock())

        from engramia.api.app import create_app

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        payload = {"task": "Parse CSV file", "code": "import csv", "eval_score": 7.0}
        import json

        body = json.dumps(payload).encode()
        assert len(body) > 50, "payload must exceed the tiny limit for this test to be meaningful"

        resp = client.post(
            "/v1/learn",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 413

    def test_normal_body_passes(self, app_client):
        """A standard request must not be rejected by the body size limit."""
        resp = app_client.post(
            "/v1/learn",
            json={"task": "Parse CSV file", "code": "import csv", "eval_score": 7.0},
        )
        # 200 or 503 (no embedding provider configured in some envs) — NOT 413
        assert resp.status_code != 413


# ---------------------------------------------------------------------------
# Security headers (P audit — untested middleware)
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    def test_x_content_type_options(self, app_client):
        resp = app_client.get("/v1/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, app_client):
        resp = app_client.get("/v1/health")
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_referrer_policy(self, app_client):
        resp = app_client.get("/v1/health")
        assert resp.headers.get("Referrer-Policy") == "no-referrer"

    def test_x_permitted_cross_domain_policies(self, app_client):
        resp = app_client.get("/v1/health")
        assert resp.headers.get("X-Permitted-Cross-Domain-Policies") == "none"

    def test_headers_present_on_post(self, app_client):
        """Security headers must be set on POST responses too, not just GET."""
        resp = app_client.post(
            "/v1/learn",
            json={"task": "Task", "code": "x = 1", "eval_score": 7.0},
        )
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

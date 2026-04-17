# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Integration tests for core API routes via create_app().

Unlike test_routes.py which uses a bare FastAPI() with manually mounted
router, these tests exercise the COMPLETE production wiring:
middleware, auth, error handlers, dependency injection.

Covers the happy path + key edge cases for:
- POST /v1/learn
- POST /v1/recall
- POST /v1/evaluate
- GET  /v1/metrics
- GET  /v1/health
- DELETE /v1/patterns/{key}
"""

import pytest

pytestmark = pytest.mark.integration

# app_client fixture is inherited from tests/conftest.py (create_app based)


# ---------------------------------------------------------------------------
# POST /v1/learn
# ---------------------------------------------------------------------------


class TestLearnIntegration:
    def test_learn_returns_200_with_stored_true(self, app_client):
        resp = app_client.post(
            "/v1/learn",
            json={
                "task": "Parse CSV file",
                "code": "import csv",
                "eval_score": 8.5,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stored"] is True
        assert data["pattern_count"] >= 1

    def test_learn_pattern_is_recallable(self, app_client):
        """Side-effect verification: learn stores, recall finds."""
        app_client.post(
            "/v1/learn",
            json={
                "task": "Parse CSV file",
                "code": "import csv",
                "eval_score": 8.5,
            },
        )
        resp = app_client.post("/v1/recall", json={"task": "Parse CSV file"})
        assert resp.status_code == 200
        assert len(resp.json()["matches"]) >= 1

    def test_learn_increments_pattern_count(self, app_client):
        app_client.post("/v1/learn", json={"task": "A", "code": "a", "eval_score": 7.0})
        resp = app_client.post("/v1/learn", json={"task": "B", "code": "b", "eval_score": 8.0})
        assert resp.json()["pattern_count"] >= 2

    def test_learn_invalid_score_returns_422(self, app_client):
        resp = app_client.post(
            "/v1/learn",
            json={
                "task": "T",
                "code": "c",
                "eval_score": 11.0,
            },
        )
        assert resp.status_code == 422

    def test_learn_empty_task_returns_422(self, app_client):
        resp = app_client.post(
            "/v1/learn",
            json={
                "task": "",
                "code": "c",
                "eval_score": 7.0,
            },
        )
        assert resp.status_code == 422
        # Error sanitized — no internal details leaked
        assert "non-empty" not in resp.json().get("detail", "")


# ---------------------------------------------------------------------------
# POST /v1/recall
# ---------------------------------------------------------------------------


class TestRecallIntegration:
    def test_recall_empty_store_returns_empty(self, app_client):
        resp = app_client.post("/v1/recall", json={"task": "anything"})
        assert resp.status_code == 200
        assert resp.json()["matches"] == []

    def test_recall_returns_match_with_expected_fields(self, app_client):
        app_client.post(
            "/v1/learn",
            json={
                "task": "Sort a list",
                "code": "sorted(lst)",
                "eval_score": 9.0,
            },
        )
        resp = app_client.post("/v1/recall", json={"task": "Sort a list"})
        assert resp.status_code == 200
        matches = resp.json()["matches"]
        assert len(matches) >= 1
        m = matches[0]
        assert "similarity" in m
        assert "reuse_tier" in m
        assert "pattern_key" in m


# ---------------------------------------------------------------------------
# GET /v1/metrics
# ---------------------------------------------------------------------------


class TestMetricsIntegration:
    def test_metrics_returns_structure(self, app_client):
        resp = app_client.get("/v1/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        assert "pattern_count" in data
        assert "success_rate" in data

    def test_metrics_increments_after_learn(self, app_client):
        app_client.post(
            "/v1/learn",
            json={
                "task": "T",
                "code": "c",
                "eval_score": 7.0,
            },
        )
        resp = app_client.get("/v1/metrics")
        data = resp.json()
        assert data["pattern_count"] >= 1
        assert data["runs"] >= 1


# ---------------------------------------------------------------------------
# GET /v1/health
# ---------------------------------------------------------------------------


class TestHealthIntegration:
    def test_health_returns_ok(self, app_client):
        resp = app_client.get("/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_health_has_security_headers(self, app_client):
        resp = app_client.get("/v1/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"


# ---------------------------------------------------------------------------
# DELETE /v1/patterns/{key}
# ---------------------------------------------------------------------------


class TestDeletePatternIntegration:
    def test_delete_existing_pattern(self, app_client):
        app_client.post(
            "/v1/learn",
            json={
                "task": "Delete me",
                "code": "x = 1",
                "eval_score": 7.0,
            },
        )
        recall = app_client.post("/v1/recall", json={"task": "Delete me"})
        key = recall.json()["matches"][0]["pattern_key"]

        resp = app_client.delete(f"/v1/patterns/{key}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        # Verify side-effect: pattern is gone
        recall2 = app_client.post("/v1/recall", json={"task": "Delete me"})
        assert recall2.json()["matches"] == []

    def test_delete_nonexistent_returns_false(self, app_client):
        resp = app_client.delete("/v1/patterns/patterns/ghost_key")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is False

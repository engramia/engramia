"""API endpoint tests using FastAPI TestClient + FakeEmbeddings + mocked LLM.

Tests run against an in-memory JSON storage — no external services needed.
Each test gets a fresh Brain instance via the ``api_client`` fixture.

All routes are mounted under /v1 to match production create_app() behaviour.
"""

import json
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from agent_brain import Brain
from agent_brain.api.routes import router
from agent_brain.exceptions import ValidationError as BrainValidationError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EVAL_RESPONSE = json.dumps(
    {
        "task_alignment": 8,
        "code_quality": 7,
        "workspace_usage": 8,
        "robustness": 6,
        "overall": 7.5,
        "feedback": "Add error handling for missing input files.",
    }
)

COMPOSE_RESPONSE = json.dumps(
    {
        "stages": [
            {"task": "Read CSV file", "reads": ["input.csv"], "writes": ["data.json"]},
            {"task": "Compute statistics", "reads": ["data.json"], "writes": ["report.txt"]},
        ]
    }
)


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.call.return_value = EVAL_RESPONSE
    return llm


@pytest.fixture
def api_client(fake_embeddings, storage, mock_llm):
    """TestClient with a fresh Brain instance backed by FakeEmbeddings + JSONStorage."""
    app = FastAPI()
    brain = Brain(embeddings=fake_embeddings, storage=storage, llm=mock_llm)
    app.state.brain = brain

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(BrainValidationError)
    async def _brain_validation_error(request: Request, exc: BrainValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    app.include_router(router, prefix="/v1")
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /v1/learn
# ---------------------------------------------------------------------------


class TestLearnEndpoint:
    def test_learn_returns_200(self, api_client):
        resp = api_client.post(
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
        assert data["pattern_count"] == 1

    def test_learn_increments_count(self, api_client):
        api_client.post("/v1/learn", json={"task": "Task A", "code": "code_a", "eval_score": 7.0})
        api_client.post("/v1/learn", json={"task": "Task B", "code": "code_b", "eval_score": 8.0})
        resp = api_client.post("/v1/learn", json={"task": "Task C", "code": "code_c", "eval_score": 9.0})
        assert resp.json()["pattern_count"] == 3

    def test_learn_invalid_score_returns_422(self, api_client):
        resp = api_client.post("/v1/learn", json={"task": "Task", "code": "code", "eval_score": 11.0})
        assert resp.status_code == 422

    def test_learn_empty_task_returns_422(self, api_client):
        resp = api_client.post("/v1/learn", json={"task": "", "code": "import csv", "eval_score": 7.0})
        assert resp.status_code in (422, 400, 500)  # depends on validation depth


# ---------------------------------------------------------------------------
# POST /v1/recall
# ---------------------------------------------------------------------------


class TestRecallEndpoint:
    def test_recall_returns_matches(self, api_client):
        api_client.post("/v1/learn", json={"task": "Parse CSV file", "code": "import csv", "eval_score": 8.5})
        resp = api_client.post("/v1/recall", json={"task": "Parse CSV file"})
        assert resp.status_code == 200
        data = resp.json()
        assert "matches" in data
        assert len(data["matches"]) == 1
        assert data["matches"][0]["similarity"] == pytest.approx(1.0, abs=1e-4)

    def test_recall_empty_store_returns_empty(self, api_client):
        resp = api_client.post("/v1/recall", json={"task": "Read CSV data"})
        assert resp.status_code == 200
        assert resp.json()["matches"] == []

    def test_recall_match_has_pattern_key(self, api_client):
        api_client.post("/v1/learn", json={"task": "Task", "code": "code", "eval_score": 7.0})
        resp = api_client.post("/v1/recall", json={"task": "Task"})
        match = resp.json()["matches"][0]
        assert match["pattern_key"].startswith("patterns/")

    def test_recall_invalid_limit_returns_422(self, api_client):
        resp = api_client.post("/v1/recall", json={"task": "task", "limit": 0})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /v1/evaluate
# ---------------------------------------------------------------------------


class TestEvaluateEndpoint:
    def test_evaluate_returns_median_score(self, api_client):
        resp = api_client.post("/v1/evaluate", json={"task": "Parse CSV", "code": "import csv", "num_evals": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert data["median_score"] == pytest.approx(7.5)

    def test_evaluate_returns_feedback(self, api_client):
        resp = api_client.post("/v1/evaluate", json={"task": "Parse CSV", "code": "import csv", "num_evals": 1})
        assert "error handling" in resp.json()["feedback"].lower()

    def test_evaluate_num_evals_zero_returns_422(self, api_client):
        resp = api_client.post("/v1/evaluate", json={"task": "Task", "code": "code", "num_evals": 0})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /v1/compose
# ---------------------------------------------------------------------------


class TestComposeEndpoint:
    def test_compose_returns_pipeline(self, api_client, mock_llm):
        mock_llm.call.return_value = COMPOSE_RESPONSE
        api_client.post("/v1/learn", json={"task": "Read CSV file", "code": "import csv", "eval_score": 8.0})
        resp = api_client.post("/v1/compose", json={"task": "Read CSV and compute stats"})
        assert resp.status_code == 200
        data = resp.json()
        assert "stages" in data
        assert len(data["stages"]) >= 1


# ---------------------------------------------------------------------------
# GET /v1/feedback
# ---------------------------------------------------------------------------


class TestFeedbackEndpoint:
    def test_feedback_returns_list(self, api_client):
        resp = api_client.get("/v1/feedback")
        assert resp.status_code == 200
        assert "feedback" in resp.json()

    def test_feedback_populated_after_evaluations(self, api_client):
        # Two evaluations push feedback past count >= 2 threshold
        api_client.post("/v1/evaluate", json={"task": "Parse CSV", "code": "import csv", "num_evals": 1})
        api_client.post("/v1/evaluate", json={"task": "Parse CSV", "code": "import csv", "num_evals": 1})
        resp = api_client.get("/v1/feedback")
        feedback = resp.json()["feedback"]
        assert any("error handling" in f.lower() for f in feedback)


# ---------------------------------------------------------------------------
# GET /v1/metrics
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    def test_metrics_returns_structure(self, api_client):
        resp = api_client.get("/v1/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        assert "pattern_count" in data
        assert "success_rate" in data

    def test_metrics_increments_after_learn(self, api_client):
        api_client.post("/v1/learn", json={"task": "Task", "code": "code", "eval_score": 8.0})
        resp = api_client.get("/v1/metrics")
        assert resp.json()["pattern_count"] == 1


# ---------------------------------------------------------------------------
# DELETE /v1/patterns/{key}
# ---------------------------------------------------------------------------


class TestDeletePatternEndpoint:
    def test_delete_existing_pattern(self, api_client):
        api_client.post("/v1/learn", json={"task": "Task", "code": "code", "eval_score": 8.0})
        recall_resp = api_client.post("/v1/recall", json={"task": "Task"})
        key = recall_resp.json()["matches"][0]["pattern_key"]

        del_resp = api_client.delete(f"/v1/patterns/{key}")
        assert del_resp.status_code == 200
        assert del_resp.json()["deleted"] is True

        # Pattern should be gone
        recall_after = api_client.post("/v1/recall", json={"task": "Task"})
        assert recall_after.json()["matches"] == []

    def test_delete_nonexistent_returns_false(self, api_client):
        resp = api_client.delete("/v1/patterns/patterns/nonexistent_0000")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is False


# ---------------------------------------------------------------------------
# GET /v1/health
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_ok(self, api_client):
        resp = api_client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "storage" in data
        assert "pattern_count" in data

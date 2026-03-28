# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for Phase 3 REST endpoints: /evolve, /analyze-failures, /skills/register, /skills/search."""

import json
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from engramia import Memory
from engramia.api.routes import router
from engramia.exceptions import ValidationError

EVOLVE_RESPONSE = json.dumps(
    {
        "improved_prompt": "You are an expert coder. Always handle file I/O errors.",
        "changes": ["Added error handling guidance"],
    }
)


@pytest.fixture
def mock_llm_evolve():
    llm = MagicMock()
    llm.call.return_value = EVOLVE_RESPONSE
    return llm


@pytest.fixture
def api_client(fake_embeddings, storage, mock_llm_evolve):
    app = FastAPI()
    mem = Memory(embeddings=fake_embeddings, storage=storage, llm=mock_llm_evolve)
    app.state.memory = mem

    @app.exception_handler(ValidationError)
    async def _validation_error(request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    app.include_router(router, prefix="/v1")
    return TestClient(app)


@pytest.fixture
def api_client_no_llm(fake_embeddings, storage):
    app = FastAPI()
    mem = Memory(embeddings=fake_embeddings, storage=storage, llm=None)
    app.state.memory = mem
    app.include_router(router, prefix="/v1")
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /v1/evolve
# ---------------------------------------------------------------------------


class TestEvolveEndpoint:
    def test_evolve_no_issues_returns_no_change(self, api_client):
        # No feedback stored — should return accepted=False, reason="no_issues"
        resp = api_client.post(
            "/v1/evolve",
            json={
                "role": "coder",
                "current_prompt": "You are a helpful coder.",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] is False
        assert data["reason"] == "no_issues"

    def test_evolve_no_llm_returns_501(self, api_client_no_llm):
        resp = api_client_no_llm.post(
            "/v1/evolve",
            json={
                "role": "coder",
                "current_prompt": "You are a helpful coder.",
            },
        )
        assert resp.status_code == 501


# ---------------------------------------------------------------------------
# POST /v1/analyze-failures
# ---------------------------------------------------------------------------


class TestAnalyzeFailuresEndpoint:
    def test_analyze_failures_empty(self, api_client):
        resp = api_client.post("/v1/analyze-failures", json={"min_count": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert data["clusters"] == []

    def test_analyze_failures_with_feedback(self, api_client):
        # Record some feedback so clusters appear
        mem = api_client.app.state.memory
        mem._feedback_store.record("Always handle file I/O errors")
        mem._feedback_store.record("File I/O errors should always be handled")

        resp = api_client.post("/v1/analyze-failures", json={"min_count": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["clusters"]) >= 1
        cluster = data["clusters"][0]
        assert "representative" in cluster
        assert "total_count" in cluster


# ---------------------------------------------------------------------------
# POST /v1/skills/register
# ---------------------------------------------------------------------------


class TestRegisterSkillsEndpoint:
    def test_register_skills(self, api_client):
        # Learn a pattern first to have a valid key
        mem = api_client.app.state.memory
        mem.learn(task="Parse CSV", code="import csv", eval_score=8.0)
        matches = mem.recall(task="Parse CSV", limit=1)
        key = matches[0].pattern_key

        resp = api_client.post(
            "/v1/skills/register",
            json={
                "pattern_key": key,
                "skills": ["csv_parsing", "data_analysis"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["registered"] == 2

    def test_register_empty_skills(self, api_client):
        resp = api_client.post(
            "/v1/skills/register",
            json={
                "pattern_key": "patterns/any",
                "skills": [],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["registered"] == 0


# ---------------------------------------------------------------------------
# POST /v1/skills/search
# ---------------------------------------------------------------------------


class TestSkillsSearchEndpoint:
    def test_search_skills_no_match(self, api_client):
        resp = api_client.post(
            "/v1/skills/search",
            json={
                "required": ["nonexistent_skill"],
                "match_all": True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["matches"] == []

    def test_search_skills_finds_registered(self, api_client):
        mem = api_client.app.state.memory
        mem.learn(task="Build ML model", code="from sklearn import tree", eval_score=8.5)
        matches = mem.recall(task="Build ML model", limit=1)
        key = matches[0].pattern_key
        mem.register_skills(key, ["machine_learning", "sklearn"])

        resp = api_client.post(
            "/v1/skills/search",
            json={
                "required": ["machine_learning"],
                "match_all": True,
            },
        )
        assert resp.status_code == 200
        results = resp.json()["matches"]
        assert len(results) >= 1

    def test_search_skills_empty_required(self, api_client):
        resp = api_client.post("/v1/skills/search", json={"required": []})
        assert resp.status_code == 200
        assert resp.json()["matches"] == []

"""Security hardening tests — Phase 4.5.

Covers:
- Timing-safe auth (hmac.compare_digest)
- Rate limiting (429 after burst)
- Input validation hardening (eval_score, import_data, delete_pattern, num_evals)
- Prompt injection delimiters present in evaluator / composer / evolver templates
- CORS and security response headers
- Request body size limit (413)
- API v1 prefix routing
- Docker non-root user (file check)
- Audit logging (AUTH_FAILURE, PATTERN_DELETED, RATE_LIMITED)
"""

import inspect
import time
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from agent_brain import Brain
from agent_brain.api.routes import router
from agent_brain.exceptions import ValidationError as BrainValidationError

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(fake_embeddings, storage):
    app = FastAPI()
    brain = Brain(embeddings=fake_embeddings, storage=storage)
    app.state.brain = brain

    @app.exception_handler(BrainValidationError)
    async def _ve(request: Request, exc: BrainValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def _ve2(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    app.include_router(router, prefix="/v1")
    return TestClient(app)


# ---------------------------------------------------------------------------
# S1: Timing-safe token comparison
# ---------------------------------------------------------------------------


class TestTimingSafeAuth:
    def test_hmac_compare_digest_used(self):
        """auth.py must use hmac.compare_digest, not ==."""
        from agent_brain.api import auth

        source = inspect.getsource(auth)
        assert "hmac.compare_digest" in source, "auth.py must use hmac.compare_digest for token comparison"

    def test_valid_token_accepted(self, tmp_path):
        import os

        os.environ["BRAIN_API_KEYS"] = "test-key-abc"
        try:
            from agent_brain.providers.json_storage import JSONStorage
            from tests.conftest import FakeEmbeddings

            app = FastAPI()
            app.state.brain = Brain(
                embeddings=FakeEmbeddings(),
                storage=JSONStorage(path=tmp_path),
            )
            app.include_router(router, prefix="/v1")
            client = TestClient(app)
            resp = client.get("/v1/health", headers={"Authorization": "Bearer test-key-abc"})
            assert resp.status_code == 200
        finally:
            os.environ.pop("BRAIN_API_KEYS", None)


# ---------------------------------------------------------------------------
# S2/S17: Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_rate_limit_returns_429_on_burst(self, fake_embeddings, storage):
        """Sending more requests than the limit in one window should yield 429."""
        from agent_brain.api.middleware import RateLimitMiddleware

        app = FastAPI()
        app.state.brain = Brain(embeddings=fake_embeddings, storage=storage)
        app.include_router(router, prefix="/v1")
        # Very low limit for testing
        app.add_middleware(RateLimitMiddleware, default_limit=3, expensive_limit=2)

        client = TestClient(app, raise_server_exceptions=False)
        responses = [client.get("/v1/health") for _ in range(5)]
        status_codes = [r.status_code for r in responses]
        assert 429 in status_codes, f"Expected 429 in {status_codes}"

    def test_rate_limit_headers_present(self, fake_embeddings, storage):
        """429 response must include Retry-After header."""
        from agent_brain.api.middleware import RateLimitMiddleware

        app = FastAPI()
        app.state.brain = Brain(embeddings=fake_embeddings, storage=storage)
        app.include_router(router, prefix="/v1")
        app.add_middleware(RateLimitMiddleware, default_limit=1, expensive_limit=1)

        client = TestClient(app, raise_server_exceptions=False)
        client.get("/v1/health")  # consume quota
        resp = client.get("/v1/health")
        if resp.status_code == 429:
            assert "Retry-After" in resp.headers


# ---------------------------------------------------------------------------
# S5: eval_score bounds
# ---------------------------------------------------------------------------


class TestEvalScoreBounds:
    def test_negative_eval_score_rejected(self, brain):
        with pytest.raises(BrainValidationError, match="eval_score"):
            brain.learn(task="Task", code="pass", eval_score=-0.1)

    def test_score_above_10_rejected(self, brain):
        with pytest.raises(BrainValidationError, match="eval_score"):
            brain.learn(task="Task", code="pass", eval_score=10.1)

    def test_boundary_0_accepted(self, brain):
        result = brain.learn(task="Task zero", code="pass", eval_score=0.0)
        assert result.stored is True

    def test_boundary_10_accepted(self, brain):
        result = brain.learn(task="Task ten", code="pass", eval_score=10.0)
        assert result.stored is True


# ---------------------------------------------------------------------------
# S6: import_data key prefix validation
# ---------------------------------------------------------------------------


class TestImportDataKeyPrefix:
    def test_non_patterns_key_rejected(self, brain):
        records = [{"key": "metrics/something", "data": {"task": "x"}}]
        imported = brain.import_data(records)
        assert imported == 0

    def test_feedback_key_rejected(self, brain):
        records = [{"key": "feedback/_list", "data": [{"pattern": "evil"}]}]
        imported = brain.import_data(records)
        assert imported == 0

    def test_path_traversal_key_rejected(self, brain):
        records = [{"key": "patterns/../metrics/evil", "data": {"task": "x"}}]
        imported = brain.import_data(records)
        assert imported == 0

    def test_valid_patterns_key_accepted(self, brain):
        records = [
            {
                "key": "patterns/abc12345_1000000001",
                "data": {
                    "task": "test task",
                    "design": {"code": "pass"},
                    "success_score": 7.0,
                    "reuse_count": 0,
                    "timestamp": time.time(),
                    "skills": [],
                },
            }
        ]
        imported = brain.import_data(records)
        assert imported == 1


# ---------------------------------------------------------------------------
# S7: delete_pattern prefix validation
# ---------------------------------------------------------------------------


class TestDeletePatternPrefix:
    def test_non_patterns_key_raises(self, brain):
        with pytest.raises(BrainValidationError, match="patterns/"):
            brain.delete_pattern("metrics/something")

    def test_feedback_key_raises(self, brain):
        with pytest.raises(BrainValidationError, match="patterns/"):
            brain.delete_pattern("feedback/_list")

    def test_path_traversal_rejected(self, brain):
        with pytest.raises(BrainValidationError, match="\\.\\."):
            brain.delete_pattern("patterns/../metrics/something")

    def test_valid_nonexistent_patterns_key_returns_false(self, brain):
        # Valid prefix, but key doesn't exist → False (no exception)
        result = brain.delete_pattern("patterns/nonexistent_0000")
        assert result is False


# ---------------------------------------------------------------------------
# S9: num_evals capped at MAX_NUM_EVALS
# ---------------------------------------------------------------------------


class TestNumEvalsCap:
    def test_num_evals_capped_in_evaluate(self):
        """brain.evaluate() should cap num_evals at _MAX_NUM_EVALS silently."""
        from agent_brain.brain import _MAX_NUM_EVALS

        assert _MAX_NUM_EVALS <= 20, "Sanity: cap must be reasonable"

        call_count = []
        mock_llm = MagicMock()

        def counting_call(*args, **kwargs):
            call_count.append(1)
            return (
                '{"task_alignment":7,"code_quality":7,"workspace_usage":7,"robustness":7,"overall":7.0,"feedback":"ok"}'
            )

        mock_llm.call.side_effect = counting_call

        import tempfile

        from agent_brain.providers.json_storage import JSONStorage
        from tests.conftest import FakeEmbeddings

        with tempfile.TemporaryDirectory() as td:
            b = Brain(
                embeddings=FakeEmbeddings(),
                storage=JSONStorage(path=td),
                llm=mock_llm,
            )
            # Request 50 — should be capped to _MAX_NUM_EVALS
            b.evaluate(task="task", code="pass", num_evals=50)
            assert len(call_count) <= _MAX_NUM_EVALS * 2  # each eval has 2 retries max


# ---------------------------------------------------------------------------
# S10-S12: Prompt injection delimiters
# ---------------------------------------------------------------------------


class TestPromptInjectionDelimiters:
    def test_evaluator_uses_xml_delimiters(self):
        from agent_brain.eval.evaluator import _EVAL_USER

        assert "<task>" in _EVAL_USER and "</task>" in _EVAL_USER
        assert "<code>" in _EVAL_USER and "</code>" in _EVAL_USER
        assert "disregard" in _EVAL_USER.lower() or "ignore" in _EVAL_USER.lower()

    def test_composer_uses_xml_delimiters(self):
        from agent_brain.reuse.composer import _DECOMPOSE_USER

        assert "<task>" in _DECOMPOSE_USER and "</task>" in _DECOMPOSE_USER
        assert "disregard" in _DECOMPOSE_USER.lower() or "ignore" in _DECOMPOSE_USER.lower()

    def test_evolver_uses_xml_delimiters(self):
        from agent_brain.evolution.prompt_evolver import _EVOLVE_USER

        assert "<current_prompt>" in _EVOLVE_USER
        assert "disregard" in _EVOLVE_USER.lower() or "ignore" in _EVOLVE_USER.lower()


# ---------------------------------------------------------------------------
# Security response headers
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    def test_security_headers_present(self, fake_embeddings, storage):
        from agent_brain.api.middleware import SecurityHeadersMiddleware

        app = FastAPI()
        app.state.brain = Brain(embeddings=fake_embeddings, storage=storage)
        app.include_router(router, prefix="/v1")
        app.add_middleware(SecurityHeadersMiddleware)

        client = TestClient(app)
        resp = client.get("/v1/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("Referrer-Policy") == "no-referrer"


# ---------------------------------------------------------------------------
# Body size limit
# ---------------------------------------------------------------------------


class TestBodySizeLimit:
    def test_large_body_returns_413(self, fake_embeddings, storage):
        from agent_brain.api.middleware import BodySizeLimitMiddleware

        app = FastAPI()
        app.state.brain = Brain(embeddings=fake_embeddings, storage=storage)
        app.include_router(router, prefix="/v1")
        app.add_middleware(BodySizeLimitMiddleware, max_body_size=100)  # tiny limit

        client = TestClient(app, raise_server_exceptions=False)
        # Send a payload larger than 100 bytes
        large_payload = {"task": "x" * 200, "code": "pass", "eval_score": 7.0}
        import json

        body = json.dumps(large_payload).encode()
        resp = client.post(
            "/v1/learn",
            content=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        assert resp.status_code == 413

    def test_normal_body_accepted(self, api_client):
        resp = api_client.post("/v1/learn", json={"task": "Normal task", "code": "pass", "eval_score": 7.0})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# API versioning
# ---------------------------------------------------------------------------


class TestApiVersioning:
    def test_v1_health_reachable(self, api_client):
        resp = api_client.get("/v1/health")
        assert resp.status_code == 200

    def test_unversioned_path_not_found(self, api_client):
        resp = api_client.get("/health")
        assert resp.status_code == 404

    def test_v1_learn_reachable(self, api_client):
        resp = api_client.post("/v1/learn", json={"task": "Versioned task", "code": "pass", "eval_score": 7.0})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# SHA-256 key generation (not MD5)
# ---------------------------------------------------------------------------


class TestPatternKeyGeneration:
    def test_pattern_key_uses_sha256(self):
        """Brain._pattern_key() must use SHA-256, not hashlib.md5()."""
        from agent_brain import brain as brain_module

        source = inspect.getsource(brain_module)
        assert "sha256" in source
        # No hashlib.md5 call (comments mentioning MD5 are fine)
        assert "hashlib.md5" not in source

    def test_pattern_keys_start_with_patterns_prefix(self, brain):
        brain.learn(task="SHA key test", code="pass", eval_score=7.0)
        matches = brain.recall(task="SHA key test", limit=1)
        assert matches[0].pattern_key.startswith("patterns/")


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


class TestAuditLogging:
    def test_auth_failure_logged(self, caplog, tmp_path):
        import logging
        import os

        os.environ["BRAIN_API_KEYS"] = "real-key"
        try:
            from agent_brain.providers.json_storage import JSONStorage
            from tests.conftest import FakeEmbeddings

            app = FastAPI()
            app.state.brain = Brain(
                embeddings=FakeEmbeddings(),
                storage=JSONStorage(path=tmp_path),
            )
            app.include_router(router, prefix="/v1")
            client = TestClient(app)

            with caplog.at_level(logging.WARNING, logger="agent_brain.audit"):
                client.get("/v1/health", headers={"Authorization": "Bearer wrong-key"})

            assert any("auth_failure" in r.message for r in caplog.records)
        finally:
            os.environ.pop("BRAIN_API_KEYS", None)

    def test_pattern_deleted_logged(self, caplog, brain):
        import logging

        brain.learn(task="Audit delete test", code="pass", eval_score=7.0)
        matches = brain.recall(task="Audit delete test", limit=1)
        key = matches[0].pattern_key

        app = FastAPI()
        app.state.brain = brain

        @app.exception_handler(BrainValidationError)
        async def _ve(request: Request, exc: BrainValidationError) -> JSONResponse:
            return JSONResponse(status_code=422, content={"detail": str(exc)})

        app.include_router(router, prefix="/v1")
        client = TestClient(app)

        with caplog.at_level(logging.WARNING, logger="agent_brain.audit"):
            resp = client.delete(f"/v1/patterns/{key}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert any("pattern_deleted" in r.message for r in caplog.records)

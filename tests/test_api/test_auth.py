"""Tests for API authentication middleware."""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from remanence.brain import Memory
from remanence.providers.json_storage import JSONStorage
from tests.conftest import FakeEmbeddings


@pytest.fixture(autouse=True)
def _clean_env():
    """Ensure REMANENCE_API_KEYS is cleaned up after each test."""
    old = os.environ.pop("REMANENCE_API_KEYS", None)
    yield
    if old is not None:
        os.environ["REMANENCE_API_KEYS"] = old
    else:
        os.environ.pop("REMANENCE_API_KEYS", None)


def _make_test_app(api_keys: str = "") -> FastAPI:
    """Create a minimal test app with auth middleware."""
    if api_keys:
        os.environ["REMANENCE_API_KEYS"] = api_keys
    else:
        os.environ.pop("REMANENCE_API_KEYS", None)

    # Import router fresh (auth reads env at request time)
    from remanence.api.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/v1")
    return app


@pytest.fixture
def tmp_brain(tmp_path):
    storage = JSONStorage(path=tmp_path)
    embeddings = FakeEmbeddings()
    return Memory(embeddings=embeddings, storage=storage)


class TestAuthDevMode:
    """When REMANENCE_API_KEYS is empty, all requests pass (dev mode)."""

    def test_no_auth_required_in_dev_mode(self, tmp_brain):
        app = _make_test_app("")
        app.state.brain = tmp_brain

        client = TestClient(app)
        resp = client.get("/v1/health")
        assert resp.status_code == 200

    def test_request_with_token_also_works_in_dev(self, tmp_brain):
        app = _make_test_app("")
        app.state.brain = tmp_brain

        client = TestClient(app)
        resp = client.get("/v1/health", headers={"Authorization": "Bearer any-token"})
        assert resp.status_code == 200


class TestAuthEnabled:
    """When REMANENCE_API_KEYS is set, Bearer tokens are required."""

    def test_missing_token_returns_401(self, tmp_brain):
        app = _make_test_app("secret-key-123")
        app.state.brain = tmp_brain

        client = TestClient(app)
        resp = client.get("/v1/health")
        assert resp.status_code == 401

    def test_wrong_token_returns_401(self, tmp_brain):
        app = _make_test_app("secret-key-123")
        app.state.brain = tmp_brain

        client = TestClient(app)
        resp = client.get("/v1/health", headers={"Authorization": "Bearer wrong-key"})
        assert resp.status_code == 401

    def test_valid_token_returns_200(self, tmp_brain):
        app = _make_test_app("secret-key-123")
        app.state.brain = tmp_brain

        client = TestClient(app)
        resp = client.get("/v1/health", headers={"Authorization": "Bearer secret-key-123"})
        assert resp.status_code == 200

    def test_multiple_keys_supported(self, tmp_brain):
        app = _make_test_app("key-a,key-b,key-c")
        app.state.brain = tmp_brain

        client = TestClient(app)
        for key in ("key-a", "key-b", "key-c"):
            resp = client.get("/v1/health", headers={"Authorization": f"Bearer {key}"})
            assert resp.status_code == 200

    def test_invalid_auth_scheme_returns_401(self, tmp_brain):
        app = _make_test_app("secret-key-123")
        app.state.brain = tmp_brain

        client = TestClient(app)
        resp = client.get("/v1/health", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 401

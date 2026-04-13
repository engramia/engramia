# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Shared test fixtures and helpers.

Provides:
- FakeEmbeddings   — deterministic MD5-seeded embeddings (no API key)
- fake_embeddings  — fixture returning FakeEmbeddings()
- storage          — fixture returning JSONStorage(tmp_path)
- mem              — fixture returning Memory with fake providers
- mock_llm         — fixture returning a MagicMock LLM with fixed eval response
- app_client       — fixture returning a TestClient backed by create_app()
                     with dev auth, JSON storage, and mocked LLM/embeddings
"""

import hashlib
import json
from unittest.mock import MagicMock

import numpy as np
import pytest
from fastapi.testclient import TestClient

import engramia._factory as factory
from engramia.memory import Memory
from engramia.providers.base import EmbeddingProvider
from engramia.providers.json_storage import JSONStorage


@pytest.fixture(autouse=True)
def _reset_scope_contextvar():
    """Reset the scope contextvar after every test.

    Tests that call ``set_scope()`` without a matching ``reset_scope()``
    leak the scope into the main thread's context, which then mismatches
    worker-thread writes (ThreadPoolExecutor workers start with a fresh
    default context). This manifests as `0 == N` assertions in concurrent
    tests when the scope leaks between tests during full-suite runs.
    """
    from engramia._context import _scope_var
    from engramia.types import Scope

    token = _scope_var.set(Scope())
    yield
    _scope_var.reset(token)

# ---------------------------------------------------------------------------
# Fixed LLM response for deterministic eval/compose tests
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


class FakeEmbeddings(EmbeddingProvider):
    """Deterministic embeddings for tests — no API key required.

    Produces a stable 1536-dimensional unit vector derived from the MD5 hash
    of the input text. Identical texts produce identical vectors, so
    cosine similarity of a text with itself is always 1.0.
    """

    DIM = 1536

    def embed(self, text: str) -> list[float]:
        seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2**32)
        rng = np.random.RandomState(seed)
        vec = rng.randn(self.DIM).astype(np.float32)
        norm = np.linalg.norm(vec)
        return (vec / norm).tolist()


@pytest.fixture
def fake_embeddings() -> FakeEmbeddings:
    return FakeEmbeddings()


@pytest.fixture
def storage(tmp_path) -> JSONStorage:
    return JSONStorage(path=tmp_path)


@pytest.fixture
def mem(fake_embeddings, storage) -> Memory:
    return Memory(embeddings=fake_embeddings, storage=storage)


@pytest.fixture
def mock_llm() -> MagicMock:
    """MagicMock LLM whose .call() returns a fixed evaluator JSON response."""
    llm = MagicMock()
    llm.call.return_value = EVAL_RESPONSE
    return llm


# ---------------------------------------------------------------------------
# Integration test fixture: full create_app() with mocked providers
# ---------------------------------------------------------------------------


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """TestClient backed by ``create_app()`` with the full middleware stack.

    Uses dev auth (no authentication required), JSON storage, and mocked
    embeddings + LLM so no API keys or Docker are needed.

    This fixture exercises the COMPLETE production wiring:
    CORS, SecurityHeaders, BodySize, RateLimit, RequestID, Timing,
    error handlers, dependency injection, and all routers.

    For tests that need a specific RBAC role, override require_auth
    after obtaining the client::

        from engramia.api.auth import require_auth
        from tests.factories import make_auth_dep

        app_client.app.dependency_overrides[require_auth] = make_auth_dep("reader")
    """
    monkeypatch.setenv("ENGRAMIA_ALLOW_NO_AUTH", "true")
    monkeypatch.setenv("ENGRAMIA_AUTH_MODE", "dev")
    monkeypatch.setenv("ENGRAMIA_STORAGE", "json")
    monkeypatch.setenv("ENGRAMIA_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("ENGRAMIA_LLM_PROVIDER", "none")
    monkeypatch.setenv("ENGRAMIA_SKIP_AUTO_APP", "1")

    mock_embeddings = MagicMock()
    mock_embeddings.embed.return_value = [0.1] * 1536
    _mock_llm = MagicMock()
    _mock_llm.call.return_value = EVAL_RESPONSE

    monkeypatch.setattr(factory, "make_embeddings", lambda: mock_embeddings)
    monkeypatch.setattr(factory, "make_llm", lambda: _mock_llm)

    from engramia.api.app import create_app

    app = create_app()
    return TestClient(app)

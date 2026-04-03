# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for api/keys.py — API key management endpoints (Phase 5.2).

Uses a mock SQLAlchemy engine; no real PostgreSQL required.
"""

import hashlib
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from engramia.api.keys import _generate_key
from engramia.api.keys import router as keys_router
from engramia.types import AuthContext, Scope

# ---------------------------------------------------------------------------
# _generate_key helper
# ---------------------------------------------------------------------------


class TestGenerateKey:
    def test_format_starts_with_prefix(self):
        full_key, _prefix, _ = _generate_key()
        assert full_key.startswith("engramia_sk_")

    def test_hash_matches_key(self):
        full_key, _, key_hash = _generate_key()
        expected = hashlib.sha256(full_key.encode()).hexdigest()
        assert key_hash == expected

    def test_prefix_shown_in_display(self):
        full_key, prefix, _ = _generate_key()
        suffix = full_key[len("engramia_sk_"):]
        assert prefix.startswith(f"engramia_sk_{suffix[:8]}")

    def test_keys_are_unique(self):
        keys = {_generate_key()[0] for _ in range(20)}
        assert len(keys) == 20


# ---------------------------------------------------------------------------
# App setup helpers
# ---------------------------------------------------------------------------


def _make_keys_app(engine=None, role: str = "owner") -> FastAPI:
    app = FastAPI()
    app.include_router(keys_router)
    app.state.auth_engine = engine

    from fastapi import Request
    from starlette.middleware.base import BaseHTTPMiddleware

    class FakeAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request.state.auth_context = AuthContext(
                key_id="caller-key-id",
                tenant_id="default",
                project_id="default",
                role=role,
                scope=Scope(),
            )
            return await call_next(request)

    app.add_middleware(FakeAuthMiddleware)
    return app


def _mock_engine_for_bootstrap(empty: bool = True):
    """Return an engine that simulates an empty (or non-empty) api_keys table."""
    count_val = 0 if empty else 1
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = (count_val,)
    engine = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    mock_begin = MagicMock()
    mock_begin.__enter__ = MagicMock(return_value=MagicMock())
    mock_begin.__exit__ = MagicMock(return_value=False)
    engine.begin.return_value = mock_begin
    return engine


# ---------------------------------------------------------------------------
# Bootstrap endpoint
# ---------------------------------------------------------------------------


class TestBootstrap:
    def test_bootstrap_returns_409_when_keys_exist(self):
        engine = _mock_engine_for_bootstrap(empty=False)
        app = _make_keys_app(engine=engine)
        client = TestClient(app)

        resp = client.post("/keys/bootstrap", json={})
        assert resp.status_code == 409

    def test_bootstrap_returns_503_without_engine(self):
        app = _make_keys_app(engine=None)
        client = TestClient(app)
        resp = client.post("/keys/bootstrap", json={})
        assert resp.status_code == 503

    def test_bootstrap_success_returns_201(self):
        # connect() used only for COUNT(*) check — returns 0
        count_conn = MagicMock()
        count_conn.execute.return_value.fetchone.return_value = (0,)
        engine = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=count_conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        # begin() used for INSERT tenants/projects and INSERT+SELECT api_key
        begin_inner = MagicMock()
        begin_inner.execute.return_value.fetchone.return_value = ("2026-01-01T00:00:00Z",)
        begin_ctx = MagicMock()
        begin_ctx.__enter__ = MagicMock(return_value=begin_inner)
        begin_ctx.__exit__ = MagicMock(return_value=False)
        engine.begin.return_value = begin_ctx

        app = _make_keys_app(engine=engine)
        client = TestClient(app)
        resp = client.post("/keys/bootstrap", json={"tenant_name": "Test Org", "key_name": "My Key"})

        assert resp.status_code == 201
        data = resp.json()
        assert data["role"] == "owner"
        assert data["key"].startswith("engramia_sk_")


# ---------------------------------------------------------------------------
# Create key endpoint
# ---------------------------------------------------------------------------


class TestCreateKey:
    def test_create_returns_503_without_engine(self):
        app = _make_keys_app(engine=None)
        client = TestClient(app)
        resp = client.post("/keys", json={"name": "test", "role": "editor"})
        assert resp.status_code == 503

    def test_create_returns_201_with_engine(self):
        created_at_row = ("2026-01-01T00:00:00Z",)
        select_conn = MagicMock()
        select_conn.execute.return_value.fetchone.return_value = created_at_row

        begin_inner = MagicMock()
        begin_inner.execute.return_value.fetchone.return_value = created_at_row
        begin_ctx = MagicMock()
        begin_ctx.__enter__ = MagicMock(return_value=begin_inner)
        begin_ctx.__exit__ = MagicMock(return_value=False)

        engine = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=select_conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        engine.begin.return_value = begin_ctx

        app = _make_keys_app(engine=engine)
        client = TestClient(app)
        resp = client.post("/keys", json={"name": "CI key", "role": "reader"})

        assert resp.status_code == 201
        data = resp.json()
        assert data["role"] == "reader"
        assert data["key"].startswith("engramia_sk_")
        assert data["name"] == "CI key"


# ---------------------------------------------------------------------------
# List keys endpoint
# ---------------------------------------------------------------------------


class TestListKeys:
    def test_list_returns_503_without_engine(self):
        app = _make_keys_app(engine=None)
        client = TestClient(app)
        resp = client.get("/keys")
        assert resp.status_code == 503

    def test_list_returns_empty_list(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        engine = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        app = _make_keys_app(engine=engine)
        client = TestClient(app)
        resp = client.get("/keys")
        assert resp.status_code == 200
        assert resp.json() == {"keys": []}

    def test_list_returns_keys_with_fields(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("key-id-1", "CI Key", "engramia_sk_abc12345...", "editor",
             "default", "default", 100, "2026-01-01T00:00:00", None, None, None),
        ]
        engine = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        app = _make_keys_app(engine=engine)
        client = TestClient(app)
        resp = client.get("/keys")
        assert resp.status_code == 200
        keys = resp.json()["keys"]
        assert len(keys) == 1
        assert keys[0]["id"] == "key-id-1"
        assert keys[0]["role"] == "editor"
        assert keys[0]["max_patterns"] == 100

    def test_reader_cannot_list_keys(self):
        engine = MagicMock()
        app = _make_keys_app(engine=engine, role="reader")
        client = TestClient(app)
        resp = client.get("/keys")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Revoke key endpoint
# ---------------------------------------------------------------------------


class TestRevokeKey:
    def test_revoke_returns_404_when_key_not_found(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        engine = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        app = _make_keys_app(engine=engine)
        client = TestClient(app)
        resp = client.delete("/keys/nonexistent-id")
        assert resp.status_code == 404

    def test_revoke_returns_409_when_already_revoked(self):
        mock_conn = MagicMock()
        # Row with revoked_at set
        mock_conn.execute.return_value.fetchone.return_value = ("some-hash", "2026-01-01")
        engine = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        app = _make_keys_app(engine=engine)
        client = TestClient(app)
        resp = client.delete("/keys/already-revoked-id")
        assert resp.status_code == 409

    def test_revoke_success_returns_200(self):
        key_hash = hashlib.sha256(b"active-key").hexdigest()

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (key_hash, None)
        engine = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        begin_inner = MagicMock()
        begin_ctx = MagicMock()
        begin_ctx.__enter__ = MagicMock(return_value=begin_inner)
        begin_ctx.__exit__ = MagicMock(return_value=False)
        engine.begin.return_value = begin_ctx

        app = _make_keys_app(engine=engine)
        client = TestClient(app)
        resp = client.delete("/keys/active-key-id")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "active-key-id"
        assert data["revoked"] is True

    def test_revoke_returns_503_without_engine(self):
        app = _make_keys_app(engine=None)
        client = TestClient(app)
        resp = client.delete("/keys/some-id")
        assert resp.status_code == 503

    def test_reader_cannot_revoke(self):
        engine = MagicMock()
        app = _make_keys_app(engine=engine, role="reader")
        client = TestClient(app)
        resp = client.delete("/keys/some-id")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Rotate key endpoint
# ---------------------------------------------------------------------------


class TestRotateKey:
    def test_rotate_returns_404_when_key_not_found(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        engine = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        app = _make_keys_app(engine=engine)
        client = TestClient(app)
        resp = client.post("/keys/nonexistent-id/rotate")
        assert resp.status_code == 404

    def test_rotate_returns_409_when_key_already_revoked(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = ("some-hash", "2026-01-01")
        engine = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        app = _make_keys_app(engine=engine)
        client = TestClient(app)
        resp = client.post("/keys/revoked-key-id/rotate")
        assert resp.status_code == 409

    def test_rotate_returns_503_without_engine(self):
        app = _make_keys_app(engine=None)
        client = TestClient(app)
        resp = client.post("/keys/some-id/rotate")
        assert resp.status_code == 503

    def test_reader_cannot_rotate(self):
        engine = MagicMock()
        app = _make_keys_app(engine=engine, role="reader")
        client = TestClient(app)
        resp = client.post("/keys/some-id/rotate")
        assert resp.status_code == 403

    def test_rotate_success_returns_200_with_new_key(self):
        old_hash = hashlib.sha256(b"old-key").hexdigest()

        mock_conn = MagicMock()
        # First call: get key row (hash, revoked_at=None)
        mock_conn.execute.return_value.fetchone.return_value = (old_hash, None)

        begin_inner = MagicMock()
        begin_ctx = MagicMock()
        begin_ctx.__enter__ = MagicMock(return_value=begin_inner)
        begin_ctx.__exit__ = MagicMock(return_value=False)

        engine = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        engine.begin.return_value = begin_ctx

        app = _make_keys_app(engine=engine)
        client = TestClient(app)
        resp = client.post("/keys/some-key-id/rotate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"].startswith("engramia_sk_")
        assert data["id"] == "some-key-id"

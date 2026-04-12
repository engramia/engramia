# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for the DB auth path in api/auth.py (Phase 5.2).

Uses a mock DB engine so no real PostgreSQL is needed.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from engramia.api.auth import (
    _hash_key,
    _key_cache,
    _lookup_key_cached,
    invalidate_key_cache,
)

# ---------------------------------------------------------------------------
# _hash_key
# ---------------------------------------------------------------------------


class TestHashKey:
    def test_returns_64_char_hex_string(self):
        h = _hash_key("engramia_sk_test")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self):
        assert _hash_key("abc") == _hash_key("abc")

    def test_different_keys_produce_different_hashes(self):
        assert _hash_key("key-a") != _hash_key("key-b")


# ---------------------------------------------------------------------------
# Cache operations
# ---------------------------------------------------------------------------


class TestKeyCache:
    def setup_method(self):
        _key_cache.clear()

    def test_invalidate_removes_entry(self):
        h = _hash_key("test-token")
        _key_cache[h] = (time.monotonic() + 60, {"id": "x"})
        invalidate_key_cache(h)
        assert h not in _key_cache

    def test_invalidate_nonexistent_is_noop(self):
        invalidate_key_cache("nonexistent-hash-that-does-not-exist")

    def test_cached_entry_returned_without_db_lookup(self):
        h = _hash_key("cached-token")
        fake_row = {"id": "key-1", "tenant_id": "acme", "project_id": "prod", "role": "editor", "max_patterns": None}
        _key_cache[h] = (time.monotonic() + 60, fake_row)

        mock_engine = MagicMock()
        result = _lookup_key_cached(mock_engine, h)

        assert result == fake_row
        mock_engine.connect.assert_not_called()  # DB not hit

    def test_expired_entry_triggers_db_lookup(self):
        h = _hash_key("stale-token")
        # Insert a cache entry that already expired
        _key_cache[h] = (time.monotonic() - 1, {"id": "old"})

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        result = _lookup_key_cached(mock_engine, h)
        assert result is None
        mock_engine.connect.assert_called_once()

    def test_cache_stores_db_result(self):
        h = _hash_key("new-token")
        fake_row = (
            "key-uuid",
            "tenant-x",
            "proj-x",
            "admin",
            5000,
        )
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = fake_row
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        result = _lookup_key_cached(mock_engine, h)

        assert result["tenant_id"] == "tenant-x"
        assert h in _key_cache


# ---------------------------------------------------------------------------
# DB auth integration (require_auth with mock engine)
# ---------------------------------------------------------------------------


class TestRequireAuthDBMode:
    def setup_method(self):
        _key_cache.clear()

    @pytest.fixture
    def mock_engine_for_key(self):
        """Return a mock engine that matches key_hash for 'secret-db-key'."""
        token = "secret-db-key"
        h = _hash_key(token)
        fake_row = (
            "key-001",
            "acme",
            "prod",
            "editor",
            None,
        )
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = fake_row
        engine = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        return engine, token, h

    def test_valid_db_key_sets_auth_context(self, tmp_path, mock_engine_for_key):
        import os

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from engramia import Memory
        from engramia.api.routes import router
        from engramia.providers.json_storage import JSONStorage
        from tests.conftest import FakeEmbeddings

        os.environ.pop("ENGRAMIA_API_KEYS", None)

        engine, token, _ = mock_engine_for_key

        with patch("engramia.api.auth._use_db_auth", return_value=True):
            app = FastAPI()
            app.include_router(router, prefix="/v1")
            app.state.memory = Memory(
                embeddings=FakeEmbeddings(),
                storage=JSONStorage(path=tmp_path),
            )
            app.state.auth_engine = engine

            client = TestClient(app)
            resp = client.get("/v1/health", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200

    def test_invalid_db_key_returns_401(self, tmp_path):
        import os

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from engramia import Memory
        from engramia.api.routes import router
        from engramia.providers.json_storage import JSONStorage
        from tests.conftest import FakeEmbeddings

        os.environ.pop("ENGRAMIA_API_KEYS", None)

        # Engine returns None (key not found)
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        engine = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        with patch("engramia.api.auth._use_db_auth", return_value=True):
            app = FastAPI()
            app.include_router(router, prefix="/v1")
            app.state.memory = Memory(
                embeddings=FakeEmbeddings(),
                storage=JSONStorage(path=tmp_path),
            )
            app.state.auth_engine = engine

            client = TestClient(app)
            resp = client.get("/v1/health", headers={"Authorization": "Bearer bad-key"})
            assert resp.status_code == 401

    def test_missing_auth_engine_returns_503(self, tmp_path):
        import os

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from engramia import Memory
        from engramia.api.routes import router
        from engramia.providers.json_storage import JSONStorage
        from tests.conftest import FakeEmbeddings

        os.environ.pop("ENGRAMIA_API_KEYS", None)

        with patch("engramia.api.auth._use_db_auth", return_value=True):
            app = FastAPI()
            app.include_router(router, prefix="/v1")
            app.state.memory = Memory(
                embeddings=FakeEmbeddings(),
                storage=JSONStorage(path=tmp_path),
            )
            app.state.auth_engine = None  # not configured

            client = TestClient(app)
            resp = client.get("/v1/health", headers={"Authorization": "Bearer some-key"})
            assert resp.status_code == 503

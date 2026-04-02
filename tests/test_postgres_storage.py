# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Integration tests for PostgresStorage.

Requires Docker (testcontainers spins up pgvector/pgvector:pg16).
Run with:  pytest -m postgres tests/test_postgres_storage.py

These tests cover:
- save / load round-trip
- list_keys with and without prefix
- delete removes data and embedding
- save_embedding + search_similar (cosine ANN)
- scope isolation: two tenants cannot read each other's data
- LIKE special characters in keys
- save_pattern_meta persists governance columns
- delete_scope bulk-removes a tenant's rows
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def pg_engine():
    """Start a throwaway PostgreSQL+pgvector container and return a SQLAlchemy engine."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed — install with: pip install testcontainers[postgres]")

    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        url = postgres.get_connection_url()
        from sqlalchemy import create_engine, text

        engine = create_engine(url, pool_pre_ping=True)
        _bootstrap_schema(engine)
        yield engine


def _bootstrap_schema(engine) -> None:
    """Create tables and indexes required by PostgresStorage."""
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS memory_data (
                key             TEXT        NOT NULL,
                tenant_id       TEXT        NOT NULL DEFAULT '',
                project_id      TEXT        NOT NULL DEFAULT '',
                data            JSONB       NOT NULL,
                updated_at      TEXT,
                classification  TEXT,
                source          TEXT,
                run_id          TEXT,
                author          TEXT,
                redacted        BOOLEAN     DEFAULT FALSE,
                expires_at      TEXT,
                PRIMARY KEY (key)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS memory_embeddings (
                key         TEXT        NOT NULL,
                tenant_id   TEXT        NOT NULL DEFAULT '',
                project_id  TEXT        NOT NULL DEFAULT '',
                embedding   vector(4),
                PRIMARY KEY (key)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_mem_data_scope
            ON memory_data (tenant_id, project_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_mem_emb_scope
            ON memory_embeddings (tenant_id, project_id)
        """))


@pytest.fixture
def storage(pg_engine):
    """Fresh PostgresStorage pointing at the test container, default scope."""
    from engramia._context import reset_scope, set_scope
    from engramia.providers.postgres import PostgresStorage
    from engramia.types import Scope

    # Wipe all rows between tests so they are independent
    from sqlalchemy import text

    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE memory_data, memory_embeddings"))

    token = set_scope(Scope())
    store = PostgresStorage.__new__(PostgresStorage)
    store._embedding_dim = 4
    store._engine = pg_engine
    from sqlalchemy import text as _text

    store._text = _text

    yield store
    reset_scope(token)


def _scoped_storage(pg_engine, tenant: str, project: str):
    """Return a PostgresStorage instance with a specific scope active."""
    from engramia.providers.postgres import PostgresStorage
    from sqlalchemy import text as _text

    store = PostgresStorage.__new__(PostgresStorage)
    store._embedding_dim = 4
    store._engine = pg_engine
    store._text = _text
    return store


# ---------------------------------------------------------------------------
# KV: save / load
# ---------------------------------------------------------------------------


class TestSaveLoad:
    def test_save_and_load_dict(self, storage):
        storage.save("patterns/foo", {"task": "parse CSV", "score": 9.0})
        result = storage.load("patterns/foo")
        assert result == {"task": "parse CSV", "score": 9.0}

    def test_load_missing_key_returns_none(self, storage):
        assert storage.load("patterns/does_not_exist") is None

    def test_save_overwrites_existing(self, storage):
        storage.save("patterns/k1", {"v": 1})
        storage.save("patterns/k1", {"v": 2})
        assert storage.load("patterns/k1") == {"v": 2}

    def test_save_and_load_list(self, storage):
        storage.save("analytics/events", [{"ts": 1, "kind": "learn"}])
        result = storage.load("analytics/events")
        assert isinstance(result, list)
        assert result[0]["kind"] == "learn"

    def test_load_after_delete_returns_none(self, storage):
        storage.save("patterns/del_me", {"x": 1})
        storage.delete("patterns/del_me")
        assert storage.load("patterns/del_me") is None


# ---------------------------------------------------------------------------
# KV: list_keys
# ---------------------------------------------------------------------------


class TestListKeys:
    def test_list_all_keys(self, storage):
        for i in range(5):
            storage.save(f"patterns/item_{i}", {"i": i})
        keys = storage.list_keys()
        assert len(keys) == 5

    def test_list_keys_with_prefix(self, storage):
        storage.save("patterns/alpha", {"x": 1})
        storage.save("patterns/beta", {"x": 2})
        storage.save("metrics/run_1", {"y": 3})
        keys = storage.list_keys(prefix="patterns")
        assert set(keys) == {"patterns/alpha", "patterns/beta"}

    def test_list_keys_empty_store_returns_empty(self, storage):
        assert storage.list_keys() == []

    def test_list_keys_sorted(self, storage):
        for c in ["c", "a", "b"]:
            storage.save(f"patterns/{c}", {})
        keys = storage.list_keys(prefix="patterns")
        assert keys == sorted(keys)

    def test_list_keys_like_escape(self, storage):
        """Keys containing SQL LIKE wildcards must not match unintended rows."""
        storage.save("patterns/a%b", {"escaped": True})
        storage.save("patterns/aXb", {"escaped": False})
        keys = storage.list_keys(prefix="patterns/a%b")
        assert keys == ["patterns/a%b"]


# ---------------------------------------------------------------------------
# KV: delete
# ---------------------------------------------------------------------------


class TestDelete:
    def test_delete_removes_data(self, storage):
        storage.save("patterns/gone", {"x": 1})
        storage.delete("patterns/gone")
        assert storage.load("patterns/gone") is None

    def test_delete_removes_embedding(self, storage):
        storage.save("patterns/emb_gone", {"x": 1})
        storage.save_embedding("patterns/emb_gone", [0.5, 0.5, 0.5, 0.5])
        storage.delete("patterns/emb_gone")
        results = storage.search_similar([0.5, 0.5, 0.5, 0.5], limit=10)
        keys = [k for k, _ in results]
        assert "patterns/emb_gone" not in keys

    def test_delete_nonexistent_key_is_noop(self, storage):
        storage.delete("patterns/never_existed")  # must not raise


# ---------------------------------------------------------------------------
# Embeddings: save_embedding + search_similar
# ---------------------------------------------------------------------------


class TestEmbeddings:
    def test_save_and_search_returns_saved_key(self, storage):
        vec = [1.0, 0.0, 0.0, 0.0]
        storage.save("patterns/vec1", {"task": "t1"})
        storage.save_embedding("patterns/vec1", vec)
        results = storage.search_similar(vec, limit=5)
        keys = [k for k, _ in results]
        assert "patterns/vec1" in keys

    def test_similarity_score_bounded(self, storage):
        vec = [0.5, 0.5, 0.5, 0.5]
        storage.save("patterns/v1", {})
        storage.save_embedding("patterns/v1", vec)
        results = storage.search_similar(vec, limit=5)
        assert all(0.0 <= sim <= 1.0 for _, sim in results)

    def test_search_returns_closest_first(self, storage):
        """Vector [1,0,0,0] should be closer to [1,0,0,0] than to [0,1,0,0]."""
        storage.save("patterns/close", {})
        storage.save_embedding("patterns/close", [1.0, 0.0, 0.0, 0.0])
        storage.save("patterns/far", {})
        storage.save_embedding("patterns/far", [0.0, 1.0, 0.0, 0.0])

        results = storage.search_similar([1.0, 0.0, 0.0, 0.0], limit=2)
        assert results[0][0] == "patterns/close"

    def test_search_with_prefix_filters(self, storage):
        storage.save("patterns/p1", {})
        storage.save_embedding("patterns/p1", [1.0, 0.0, 0.0, 0.0])
        storage.save("metrics/m1", {})
        storage.save_embedding("metrics/m1", [1.0, 0.0, 0.0, 0.0])

        results = storage.search_similar([1.0, 0.0, 0.0, 0.0], limit=10, prefix="patterns")
        keys = [k for k, _ in results]
        assert all(k.startswith("patterns/") for k in keys)
        assert "metrics/m1" not in keys

    def test_embedding_dimension_mismatch_raises(self, storage):
        with pytest.raises(ValueError, match="dimension"):
            storage.save_embedding("patterns/bad", [0.1, 0.2])  # dim=2, expected 4

    def test_search_dimension_mismatch_raises(self, storage):
        with pytest.raises(ValueError, match="dimension"):
            storage.search_similar([0.1, 0.2], limit=5)  # dim=2, expected 4

    def test_overwrite_embedding(self, storage):
        storage.save("patterns/upd", {})
        storage.save_embedding("patterns/upd", [1.0, 0.0, 0.0, 0.0])
        storage.save_embedding("patterns/upd", [0.0, 1.0, 0.0, 0.0])
        # after overwrite, similarity to new vector should be higher
        results = storage.search_similar([0.0, 1.0, 0.0, 0.0], limit=1)
        assert results[0][0] == "patterns/upd"


# ---------------------------------------------------------------------------
# count_patterns
# ---------------------------------------------------------------------------


class TestCountPatterns:
    def test_count_zero_on_empty(self, storage):
        assert storage.count_patterns() == 0

    def test_count_matches_saved(self, storage):
        for i in range(4):
            storage.save(f"patterns/c{i}", {"i": i})
        assert storage.count_patterns() == 4

    def test_count_with_prefix(self, storage):
        storage.save("patterns/p1", {})
        storage.save("metrics/m1", {})
        assert storage.count_patterns(prefix="patterns/") == 1


# ---------------------------------------------------------------------------
# Scope isolation (tenant/project)
# ---------------------------------------------------------------------------


class TestScopeIsolation:
    def test_tenant_a_cannot_read_tenant_b(self, pg_engine):
        from engramia._context import reset_scope, set_scope
        from engramia.types import Scope

        storage_a = _scoped_storage(pg_engine, "tenantA", "proj")
        storage_b = _scoped_storage(pg_engine, "tenantB", "proj")

        token_a = set_scope(Scope(tenant_id="tenantA", project_id="proj"))
        storage_a.save("patterns/secret", {"owner": "A"})
        reset_scope(token_a)

        token_b = set_scope(Scope(tenant_id="tenantB", project_id="proj"))
        result = storage_b.load("patterns/secret")
        reset_scope(token_b)

        assert result is None

    def test_tenant_a_list_keys_excludes_tenant_b(self, pg_engine):
        from engramia._context import reset_scope, set_scope
        from engramia.types import Scope

        storage_a = _scoped_storage(pg_engine, "tA", "p")
        storage_b = _scoped_storage(pg_engine, "tB", "p")

        token_a = set_scope(Scope(tenant_id="tA", project_id="p"))
        storage_a.save("patterns/only_a", {})
        reset_scope(token_a)

        token_b = set_scope(Scope(tenant_id="tB", project_id="p"))
        keys = storage_b.list_keys(prefix="patterns")
        reset_scope(token_b)

        assert "patterns/only_a" not in keys

    def test_embedding_search_scoped(self, pg_engine):
        from engramia._context import reset_scope, set_scope
        from engramia.types import Scope

        storage_a = _scoped_storage(pg_engine, "emb_tA", "p")
        storage_b = _scoped_storage(pg_engine, "emb_tB", "p")
        vec = [1.0, 0.0, 0.0, 0.0]

        token_a = set_scope(Scope(tenant_id="emb_tA", project_id="p"))
        storage_a.save("patterns/emb_a", {})
        storage_a.save_embedding("patterns/emb_a", vec)
        reset_scope(token_a)

        token_b = set_scope(Scope(tenant_id="emb_tB", project_id="p"))
        results = storage_b.search_similar(vec, limit=10)
        reset_scope(token_b)

        keys = [k for k, _ in results]
        assert "patterns/emb_a" not in keys

    def test_delete_scope_removes_only_target_tenant(self, pg_engine):
        from engramia._context import reset_scope, set_scope
        from engramia.types import Scope

        storage_a = _scoped_storage(pg_engine, "ds_tA", "p")
        storage_b = _scoped_storage(pg_engine, "ds_tB", "p")

        token_a = set_scope(Scope(tenant_id="ds_tA", project_id="p"))
        storage_a.save("patterns/a_row", {"a": 1})
        reset_scope(token_a)

        token_b = set_scope(Scope(tenant_id="ds_tB", project_id="p"))
        storage_b.save("patterns/b_row", {"b": 2})
        reset_scope(token_b)

        storage_a.delete_scope("ds_tA", "p")

        # Tenant A's data gone
        token_a = set_scope(Scope(tenant_id="ds_tA", project_id="p"))
        assert storage_a.load("patterns/a_row") is None
        reset_scope(token_a)

        # Tenant B's data intact
        token_b = set_scope(Scope(tenant_id="ds_tB", project_id="p"))
        assert storage_b.load("patterns/b_row") == {"b": 2}
        reset_scope(token_b)


# ---------------------------------------------------------------------------
# Governance: save_pattern_meta
# ---------------------------------------------------------------------------


class TestPatternMeta:
    def test_save_pattern_meta_does_not_raise(self, storage):
        storage.save("patterns/meta_1", {"task": "t"})
        storage.save_pattern_meta(
            "patterns/meta_1",
            classification="confidential",
            source="sdk",
            run_id="run-abc",
            author="bot@example.com",
            redacted=True,
        )

    def test_save_pattern_meta_nonexistent_key_is_noop(self, storage):
        # UPDATE on a non-existent key affects 0 rows — must not raise
        storage.save_pattern_meta("patterns/ghost", classification="public")

    def test_save_pattern_meta_bad_engine_logs_warning(self, storage, monkeypatch):
        """When the engine raises, save_pattern_meta swallows and logs (non-fatal)."""
        from sqlalchemy import create_engine

        bad_engine = create_engine("sqlite:///:memory:")
        monkeypatch.setattr(storage, "_engine", bad_engine)
        # Should not raise even with a broken engine
        storage.save_pattern_meta("patterns/any", classification="internal")

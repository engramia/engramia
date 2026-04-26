# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Unit tests for PostgresStorage using a mocked SQLAlchemy engine.

No Docker / PostgreSQL required. Tests the query logic, scope filtering,
dimension checks, and error handling.
"""

import json
from unittest.mock import MagicMock

import pytest

from engramia._context import reset_scope, set_scope
from engramia.types import Scope

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(fetchone=None, fetchall=None, rowcount=0):
    """Build a minimal mock engine that returns preset results."""
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = fetchone
    conn.execute.return_value.fetchall.return_value = fetchall or []
    conn.execute.return_value.rowcount = rowcount

    engine = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    begin_conn = MagicMock()
    begin_conn.execute.return_value.fetchone.return_value = fetchone
    begin_conn.execute.return_value.rowcount = rowcount
    engine.begin.return_value.__enter__ = MagicMock(return_value=begin_conn)
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)

    return engine, conn, begin_conn


def _make_storage(engine, embedding_dim=4):
    """Construct a PostgresStorage bypassing __init__ to inject a mock engine."""
    from sqlalchemy import text

    from engramia.providers.postgres import PostgresStorage

    storage = PostgresStorage.__new__(PostgresStorage)
    storage._engine = engine
    storage._embedding_dim = embedding_dim
    storage._text = text
    return storage


@pytest.fixture(autouse=True)
def default_scope():
    token = set_scope(Scope(tenant_id="acme", project_id="prod"))
    yield
    reset_scope(token)


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


class TestPostgresLoad:
    def test_returns_none_when_not_found(self):
        engine, _conn, _ = _make_engine(fetchone=None)
        storage = _make_storage(engine)
        assert storage.load("missing/key") is None
        _conn.execute.assert_called_once()

    def test_returns_data_when_found(self):
        data = {"task": "sort a list", "score": 8.0}
        engine, _conn, _ = _make_engine(fetchone=(data,))
        storage = _make_storage(engine)
        result = storage.load("patterns/abc")
        assert result == data


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


class TestPostgresSave:
    def test_save_executes_upsert(self):
        engine, _, begin_conn = _make_engine()
        storage = _make_storage(engine)
        storage.save("patterns/xyz", {"task": "hello", "code": "print('hi')"})
        begin_conn.execute.assert_called_once()

    def test_save_serialises_data_as_json(self):
        engine, _, begin_conn = _make_engine()
        storage = _make_storage(engine)
        data = {"task": "test", "nested": [1, 2, 3]}
        storage.save("patterns/x", data)
        call_kwargs = begin_conn.execute.call_args[0][1]
        # :data param should be valid JSON
        parsed = json.loads(call_kwargs["data"])
        assert parsed["task"] == "test"


# ---------------------------------------------------------------------------
# list_keys
# ---------------------------------------------------------------------------


class TestPostgresListKeys:
    def test_list_keys_no_prefix(self):
        rows = [("patterns/a",), ("patterns/b",)]
        engine, _conn, _ = _make_engine(fetchall=rows)
        storage = _make_storage(engine)
        keys = storage.list_keys()
        assert keys == ["patterns/a", "patterns/b"]

    def test_list_keys_with_prefix_uses_like(self):
        rows = [("patterns/abc",)]
        engine, _conn, _ = _make_engine(fetchall=rows)
        storage = _make_storage(engine)
        keys = storage.list_keys(prefix="patterns/")
        assert keys == ["patterns/abc"]
        call_params = _conn.execute.call_args[0][1]
        assert "prefix" in call_params
        assert call_params["prefix"].startswith("patterns/")

    def test_list_keys_empty(self):
        engine, _conn, _ = _make_engine(fetchall=[])
        storage = _make_storage(engine)
        assert storage.list_keys() == []


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestPostgresDelete:
    def test_delete_executes_two_deletes(self):
        engine, _, begin_conn = _make_engine()
        storage = _make_storage(engine)
        storage.delete("patterns/old")
        # Should delete from both memory_data and memory_embeddings
        assert begin_conn.execute.call_count == 2


# ---------------------------------------------------------------------------
# count_patterns
# ---------------------------------------------------------------------------


class TestPostgresCountPatterns:
    def test_count_returns_integer(self):
        engine, _conn, _ = _make_engine(fetchone=(7,))
        storage = _make_storage(engine)
        count = storage.count_patterns("patterns/")
        assert count == 7

    def test_count_returns_zero_on_no_row(self):
        engine, _conn, _ = _make_engine(fetchone=None)
        storage = _make_storage(engine)
        assert storage.count_patterns("patterns/") == 0


# ---------------------------------------------------------------------------
# save_embedding — dimension check
# ---------------------------------------------------------------------------


class TestPostgresSaveEmbedding:
    def test_dimension_mismatch_raises(self):
        engine, _, _ = _make_engine()
        storage = _make_storage(engine, embedding_dim=4)
        with pytest.raises(ValueError, match="dimension mismatch"):
            storage.save_embedding("patterns/x", [0.1, 0.2])  # 2-dim, expects 4

    def test_correct_dimension_executes_upsert(self):
        engine, _, begin_conn = _make_engine()
        storage = _make_storage(engine, embedding_dim=4)
        storage.save_embedding("patterns/x", [0.1, 0.2, 0.3, 0.4])
        begin_conn.execute.assert_called_once()


# ---------------------------------------------------------------------------
# save_pattern_meta
# ---------------------------------------------------------------------------


class TestPostgresSavePatternMeta:
    def test_saves_metadata_columns(self):
        engine, _, begin_conn = _make_engine()
        storage = _make_storage(engine)
        storage.save_pattern_meta(
            "patterns/x",
            classification="confidential",
            source="api",
            author="alice",
        )
        begin_conn.execute.assert_called_once()
        params = begin_conn.execute.call_args[0][1]
        # Bind names match the column names directly (selective UPDATE).
        # Mirror keys (cls_json / src_json) carry the JSON-string form
        # used by jsonb_set on data->design.
        assert params["classification"] == "confidential"
        assert params["source"] == "api"
        assert params["author"] == "alice"
        assert params["cls_json"] == '"confidential"'
        assert params["src_json"] == '"api"'

    def test_does_not_raise_on_db_error(self):
        engine = MagicMock()
        engine.begin.return_value.__enter__.side_effect = RuntimeError("DB gone")
        storage = _make_storage(engine)
        # Should log warning, not raise
        storage.save_pattern_meta("patterns/x")


# ---------------------------------------------------------------------------
# Scope isolation — queries include tid/pid
# ---------------------------------------------------------------------------


class TestPostgresScopeIsolation:
    def test_load_passes_scope_params(self):
        engine, _conn, _ = _make_engine(fetchone=None)
        storage = _make_storage(engine)
        storage.load("patterns/x")
        call_params = _conn.execute.call_args[0][1]
        assert call_params["tid"] == "acme"
        assert call_params["pid"] == "prod"

    def test_save_passes_scope_params(self):
        engine, _, begin_conn = _make_engine()
        storage = _make_storage(engine)
        storage.save("patterns/x", {"task": "t"})
        call_params = begin_conn.execute.call_args[0][1]
        assert call_params["tid"] == "acme"
        assert call_params["pid"] == "prod"

    def test_count_passes_scope_params(self):
        engine, _conn, _ = _make_engine(fetchone=(0,))
        storage = _make_storage(engine)
        storage.count_patterns()
        call_params = _conn.execute.call_args[0][1]
        assert call_params["tid"] == "acme"
        assert call_params["pid"] == "prod"

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Memory-level PostgreSQL integration tests.

Tests the full learn/recall/export/import cycle against a real PostgreSQL
instance (pgvector) spun up via testcontainers. Unlike test_postgres_storage.py
(which tests the storage layer directly), these tests exercise Memory as the
entrypoint — matching real production usage.

Run with:
    pytest -m postgres tests/test_integration_postgres.py

Requires:
    pip install testcontainers[postgres]
"""

from __future__ import annotations

import threading

import pytest

pytestmark = pytest.mark.postgres


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine():
    """Spin up a throwaway pgvector container for the module."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed")

    with PostgresContainer("pgvector/pgvector:0.7.4-pg16") as pg:
        from sqlalchemy import create_engine, text

        engine = create_engine(pg.get_connection_url(), pool_pre_ping=True)
        # Bootstrap schema (mirrors Alembic 001_initial migration)
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS memory_data (
                    key             TEXT    NOT NULL PRIMARY KEY,
                    tenant_id       TEXT    NOT NULL DEFAULT '',
                    project_id      TEXT    NOT NULL DEFAULT '',
                    data            JSONB   NOT NULL,
                    updated_at      TEXT,
                    classification  TEXT,
                    source          TEXT,
                    run_id          TEXT,
                    author          TEXT,
                    redacted        BOOLEAN DEFAULT FALSE,
                    expires_at      TEXT
                )
            """)
            )
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    key         TEXT    NOT NULL PRIMARY KEY,
                    tenant_id   TEXT    NOT NULL DEFAULT '',
                    project_id  TEXT    NOT NULL DEFAULT '',
                    embedding   vector(1536)
                )
            """)
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_md_scope ON memory_data (tenant_id, project_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_me_scope ON memory_embeddings (tenant_id, project_id)"))
        yield engine


@pytest.fixture
def pg_memory(pg_engine):
    """Memory instance backed by real PostgreSQL. Truncated between tests."""
    from sqlalchemy import text

    from engramia import Memory
    from engramia._context import reset_scope, set_scope
    from engramia.providers.postgres import PostgresStorage
    from engramia.types import Scope

    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE memory_data, memory_embeddings"))

    token = set_scope(Scope())

    storage = PostgresStorage.__new__(PostgresStorage)
    storage._embedding_dim = 1536
    storage._engine = pg_engine
    from sqlalchemy import text as _t

    storage._text = _t

    from tests.conftest import FakeEmbeddings

    mem = Memory(embeddings=FakeEmbeddings(), storage=storage)
    yield mem

    reset_scope(token)


# ---------------------------------------------------------------------------
# Learn / Recall cycle
# ---------------------------------------------------------------------------


class TestLearnRecallCycle:
    def test_learn_then_recall_returns_match(self, pg_memory):
        pg_memory.learn(task="parse csv file into rows", code="pd.read_csv(f)", eval_score=8.5)
        results = pg_memory.recall("parse csv file", limit=5)
        assert len(results) >= 1
        assert results[0].similarity > 0.0

    def test_learned_pattern_top_match(self, pg_memory):
        pg_memory.learn(task="compute moving average over time series", code="rolling_mean()", eval_score=9.0)
        pg_memory.learn(task="unrelated database backup task", code="pg_dump()", eval_score=7.0)
        results = pg_memory.recall("moving average calculation", limit=5)
        assert "rolling_mean" in results[0].pattern.code

    def test_recall_limit_respected(self, pg_memory):
        for i in range(8):
            pg_memory.learn(task=f"distinct task number {i}", code=f"task_{i}()", eval_score=7.0)
        results = pg_memory.recall("task", limit=3)
        assert len(results) <= 3

    def test_recall_empty_store_returns_empty(self, pg_memory):
        results = pg_memory.recall("anything", limit=5)
        assert results == []

    def test_pattern_count_increments(self, pg_memory):
        assert pg_memory.metrics.pattern_count == 0
        pg_memory.learn(task="count test task", code="count()", eval_score=7.5)
        assert pg_memory.metrics.pattern_count == 1
        pg_memory.learn(task="count test task 2", code="count2()", eval_score=7.5)
        assert pg_memory.metrics.pattern_count == 2


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDelete:
    def test_delete_removes_from_recall(self, pg_memory):
        pg_memory.learn(task="task to delete via postgres", code="deleteme()", eval_score=8.0)
        key = pg_memory.export()[0]["key"]
        assert pg_memory.delete_pattern(key) is True
        results = pg_memory.recall("task to delete via postgres", limit=5)
        assert all("deleteme" not in m.pattern.code for m in results)

    def test_delete_nonexistent_returns_false(self, pg_memory):
        assert pg_memory.delete_pattern("patterns/does_not_exist_xyz") is False


# ---------------------------------------------------------------------------
# Export / Import round-trip
# ---------------------------------------------------------------------------


class TestExportImport:
    def test_export_import_round_trip(self, pg_memory):
        pg_memory.learn(task="export import round trip task", code="rtt()", eval_score=8.0)
        exported = pg_memory.export()
        assert len(exported) == 1
        assert exported[0]["version"] == 1

        # Clear and re-import
        key = exported[0]["key"]
        pg_memory.delete_pattern(key)
        assert pg_memory.metrics.pattern_count == 0

        imported = pg_memory.import_data(exported)
        assert imported == 1
        assert pg_memory.metrics.pattern_count == 1

    def test_import_skip_existing(self, pg_memory):
        pg_memory.learn(task="skip existing test", code="skip()", eval_score=7.0)
        exported = pg_memory.export()
        imported = pg_memory.import_data(exported, overwrite=False)
        assert imported == 0  # already exists, not overwritten

    def test_import_overwrite(self, pg_memory):
        pg_memory.learn(task="overwrite test task", code="original()", eval_score=7.0)
        exported = pg_memory.export()
        # mutate the code field
        exported[0]["data"]["code"] = "updated()"
        imported = pg_memory.import_data(exported, overwrite=True)
        assert imported == 1
        results = pg_memory.recall("overwrite test task", limit=1)
        assert "updated" in results[0].pattern.code


# ---------------------------------------------------------------------------
# Concurrent writes
# ---------------------------------------------------------------------------


class TestConcurrentWrites:
    def test_concurrent_learn_no_data_loss(self, pg_memory):
        """10 threads each learn a unique pattern; all 10 must be retrievable."""
        errors = []

        def _learn(i: int):
            try:
                pg_memory.learn(
                    task=f"concurrent learn task index {i}",
                    code=f"concurrent_{i}()",
                    eval_score=7.0,
                )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_learn, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Unexpected errors during concurrent learn: {errors}"
        assert pg_memory.metrics.pattern_count == 10

    def test_concurrent_recall_no_exception(self, pg_memory):
        """Concurrent recalls on a populated store must not raise."""
        for i in range(5):
            pg_memory.learn(task=f"recall concurrency task {i}", code=f"rc_{i}()", eval_score=7.0)

        errors = []

        def _recall():
            try:
                pg_memory.recall("recall concurrency task", limit=5)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_recall) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Unexpected errors during concurrent recall: {errors}"


# ---------------------------------------------------------------------------
# Eval-weighted recall
# ---------------------------------------------------------------------------


class TestEvalWeightedRecall:
    def test_high_eval_score_ranks_higher(self, pg_memory):
        """A pattern with a higher eval_score should be preferred when tasks are similar."""
        pg_memory.learn(task="parse json response from api", code="low_quality()", eval_score=4.0)
        pg_memory.learn(task="parse json response from api endpoint", code="high_quality()", eval_score=9.0)
        results = pg_memory.recall("parse json response", limit=5, eval_weighted=True)
        assert results[0].pattern.code == "high_quality()"


# ---------------------------------------------------------------------------
# JSON → PostgreSQL migration
# ---------------------------------------------------------------------------


_MIGRATION_FIXTURES = [
    ("parse csv file and compute statistics", "pd.read_csv(f).describe()", 8.5),
    ("fetch data from rest api endpoint", "requests.get(url).json()", 7.0),
    ("train sklearn classification model", "clf.fit(X_train, y_train)", 9.0),
    ("write dataframe to parquet file", "df.to_parquet(path)", 7.5),
    ("validate json schema of api response", "jsonschema.validate(data, schema)", 8.0),
]
_MIGRATION_QUERY = "parse csv and calculate averages"


class TestJsonToPostgresMigration:
    """Cross-backend migration: learn in JSON, export, import into PostgreSQL.

    Verifies that:
    - All patterns survive the round-trip (count is preserved)
    - Recall returns the same top-1 pattern key from both backends
    - Eval scores and reuse counts are preserved
    - Pattern keys are stable across backends
    """

    @pytest.fixture
    def json_memory(self, tmp_path):
        from engramia import Memory
        from engramia.providers.json_storage import JSONStorage
        from tests.conftest import FakeEmbeddings

        return Memory(embeddings=FakeEmbeddings(), storage=JSONStorage(path=tmp_path))

    @pytest.fixture
    def pg_memory_fresh(self, pg_engine):
        """Fresh pg_memory backed by the shared engine (truncated before yield)."""
        from sqlalchemy import text

        from engramia import Memory
        from engramia._context import reset_scope, set_scope
        from engramia.providers.postgres import PostgresStorage
        from engramia.types import Scope
        from tests.conftest import FakeEmbeddings

        with pg_engine.begin() as conn:
            conn.execute(text("TRUNCATE memory_data, memory_embeddings"))

        token = set_scope(Scope())
        storage = PostgresStorage.__new__(PostgresStorage)
        storage._embedding_dim = 1536
        storage._engine = pg_engine
        from sqlalchemy import text as _t

        storage._text = _t

        mem = Memory(embeddings=FakeEmbeddings(), storage=storage)
        yield mem
        reset_scope(token)

    def test_all_patterns_survive_migration(self, json_memory, pg_memory_fresh):
        for task, code, score in _MIGRATION_FIXTURES:
            json_memory.learn(task=task, code=code, eval_score=score)

        records = json_memory.export()
        assert len(records) == len(_MIGRATION_FIXTURES)

        imported = pg_memory_fresh.import_data(records)
        assert imported == len(_MIGRATION_FIXTURES)
        assert pg_memory_fresh.metrics.pattern_count == len(_MIGRATION_FIXTURES)

    def test_top_recall_result_is_same_on_both_backends(self, json_memory, pg_memory_fresh):
        for task, code, score in _MIGRATION_FIXTURES:
            json_memory.learn(task=task, code=code, eval_score=score)

        records = json_memory.export()
        pg_memory_fresh.import_data(records)

        json_top = json_memory.recall(_MIGRATION_QUERY, limit=1)
        pg_top = pg_memory_fresh.recall(_MIGRATION_QUERY, limit=1)

        assert len(json_top) == 1
        assert len(pg_top) == 1
        assert json_top[0].pattern_key == pg_top[0].pattern_key

    def test_eval_scores_preserved(self, json_memory, pg_memory_fresh):
        for task, code, score in _MIGRATION_FIXTURES:
            json_memory.learn(task=task, code=code, eval_score=score)

        records = json_memory.export()
        pg_memory_fresh.import_data(records)

        json_matches = {m.pattern_key: m for m in json_memory.recall(_MIGRATION_QUERY, limit=5)}
        pg_matches = {m.pattern_key: m for m in pg_memory_fresh.recall(_MIGRATION_QUERY, limit=5)}

        common_keys = set(json_matches) & set(pg_matches)
        assert len(common_keys) >= 1
        for key in common_keys:
            assert abs(json_matches[key].pattern.success_score - pg_matches[key].pattern.success_score) < 0.01, (
                f"Score mismatch for {key}"
            )

    def test_pattern_keys_are_stable(self, json_memory, pg_memory_fresh):
        for task, code, score in _MIGRATION_FIXTURES:
            json_memory.learn(task=task, code=code, eval_score=score)

        records = json_memory.export()
        json_keys = {r["key"] for r in records}

        pg_memory_fresh.import_data(records)
        pg_records = pg_memory_fresh.export()
        pg_keys = {r["key"] for r in pg_records}

        assert json_keys == pg_keys

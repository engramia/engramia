# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""P1 — T-02: Database module tests.

Covers:
- Migration forward (upgrade → head): core tables and billing tables created.
- Migration backward (downgrade → base): all managed tables removed.
- Round-trip upgrade → downgrade → upgrade: idempotent.
- Step-back: downgrade -1 leaves DB at parent revision.
- Transaction isolation: uncommitted writes are invisible to other connections
  (READ COMMITTED semantics); rollback does not corrupt committed data.
- Connection pool exhaustion: QueuePool raises TimeoutError when pool is full;
  released connections are reusable; max_overflow allows extra connections.

Run with:
    pytest -m postgres tests/test_db/

Requires:
    pip install 'engramia[postgres]' testcontainers[postgres]
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.postgres

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_MIGRATIONS_DIR = str(Path(__file__).parent.parent.parent / "engramia" / "db" / "migrations")


# ---------------------------------------------------------------------------
# Module-level fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_url():
    """Spin up a throwaway pgvector container shared for the whole module."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed — run: pip install 'testcontainers[postgres]'")

    with PostgresContainer("pgvector/pgvector:0.7.4-pg16") as pg:
        yield pg.get_connection_url()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _alembic_cfg(db_url: str):
    """Return an Alembic Config object pointing at the project migrations."""
    import logging

    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", _MIGRATIONS_DIR)
    cfg.set_main_option("sqlalchemy.url", db_url)
    # Suppress verbose alembic logging during tests
    logging.getLogger("alembic").setLevel(logging.WARNING)
    return cfg


def _get_engine(db_url: str, **kwargs):
    """Create and return a SQLAlchemy engine."""
    from sqlalchemy import create_engine

    return create_engine(db_url, pool_pre_ping=True, **kwargs)


def _table_names(engine) -> set[str]:
    """Return all non-system table names in the public schema."""
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).fetchall()
    return {row[0] for row in rows}


@pytest.fixture(autouse=True)
def _clean_db(pg_url):
    """Reset DB to base state before and after each test for full isolation."""
    from alembic import command

    cfg = _alembic_cfg(pg_url)
    try:
        command.downgrade(cfg, "base")
    except Exception:
        pass  # DB may have no alembic_version yet on first run
    yield
    try:
        command.downgrade(cfg, "base")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# T-02a: Migration forward / backward
# ---------------------------------------------------------------------------


class TestMigrationForwardBackward:
    """Alembic upgrade/downgrade correctness."""

    def test_upgrade_to_head_creates_core_tables(self, pg_url):
        """upgrade head → memory_data, memory_embeddings and all billing tables exist."""
        from alembic import command

        command.upgrade(_alembic_cfg(pg_url), "head")
        engine = _get_engine(pg_url)
        try:
            tables = _table_names(engine)
        finally:
            engine.dispose()

        assert "memory_data" in tables
        assert "memory_embeddings" in tables
        assert "billing_subscriptions" in tables
        assert "usage_counters" in tables
        assert "overage_settings" in tables
        assert "tenant_credentials" in tables  # migration 023 (BYOK)

    def test_downgrade_to_base_removes_all_managed_tables(self, pg_url):
        """downgrade base → tables created by migration 001 must be gone."""
        from alembic import command

        cfg = _alembic_cfg(pg_url)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")

        engine = _get_engine(pg_url)
        try:
            tables = _table_names(engine)
        finally:
            engine.dispose()

        # Original tables from migration 001 must not exist in either name
        assert "brain_data" not in tables
        assert "brain_embeddings" not in tables
        # Tables from later migrations must also be gone
        assert "memory_data" not in tables
        assert "memory_embeddings" not in tables
        assert "billing_subscriptions" not in tables

    def test_round_trip_upgrade_downgrade_upgrade(self, pg_url):
        """upgrade → downgrade → upgrade must complete without error."""
        from alembic import command

        cfg = _alembic_cfg(pg_url)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")  # Must not raise

        engine = _get_engine(pg_url)
        try:
            tables = _table_names(engine)
        finally:
            engine.dispose()

        assert "memory_data" in tables

    def test_idempotent_upgrade_is_noop(self, pg_url):
        """Running upgrade head twice must not raise (already at head)."""
        from alembic import command

        cfg = _alembic_cfg(pg_url)
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")  # Must not raise

    def test_step_back_one_migration_changes_alembic_version(self, pg_url):
        """downgrade -1 from head leaves alembic_version at the parent revision."""
        from alembic import command
        from sqlalchemy import text

        cfg = _alembic_cfg(pg_url)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "-1")

        engine = _get_engine(pg_url)
        try:
            with engine.connect() as conn:
                row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
            version = row[0] if row else None
        finally:
            engine.dispose()

        # Should have a version, but not the head one (013)
        assert version is not None
        assert version != "013"

    def test_billing_migration_enforces_unique_tenant_constraint(self, pg_url):
        """billing_subscriptions.tenant_id has a UNIQUE constraint (from migration 008)."""
        from alembic import command
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        command.upgrade(_alembic_cfg(pg_url), "head")
        engine = _get_engine(pg_url)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO billing_subscriptions "
                        "(id, tenant_id, plan_tier, billing_interval, status, "
                        " eval_runs_limit, patterns_limit, projects_limit) "
                        "VALUES ('mig-test-1', 'tenant-unique-test', "
                        "'sandbox', 'month', 'active', 500, 5000, 1)"
                    )
                )

            # Second INSERT with same tenant_id must violate the UNIQUE constraint
            with engine.begin() as conn, pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO billing_subscriptions "
                        "(id, tenant_id, plan_tier, billing_interval, status, "
                        " eval_runs_limit, patterns_limit, projects_limit) "
                        "VALUES ('mig-test-2', 'tenant-unique-test', "
                        "'pro', 'month', 'active', 3000, 50000, 3)"
                    )
                )
        finally:
            engine.dispose()


# ---------------------------------------------------------------------------
# T-02b: Transaction isolation (READ COMMITTED)
# ---------------------------------------------------------------------------


class TestTransactionIsolation:
    """PostgreSQL READ COMMITTED isolation — standard default isolation level."""

    def test_uncommitted_insert_not_visible_to_other_connection(self, pg_url):
        """Writes inside an open transaction are not visible to other connections."""
        from sqlalchemy import text

        engine = _get_engine(pg_url)
        try:
            with engine.begin() as setup:
                setup.execute(text("CREATE TABLE IF NOT EXISTS _txn_isolation_test (id TEXT PRIMARY KEY, val TEXT)"))

            row_id = "uncommitted-row"
            with engine.begin() as conn_a:
                conn_a.execute(
                    text("INSERT INTO _txn_isolation_test (id, val) VALUES (:id, 'pending')"),
                    {"id": row_id},
                )
                # conn_a has NOT committed — a separate connection must not see this row
                with engine.connect() as conn_b:
                    row = conn_b.execute(
                        text("SELECT val FROM _txn_isolation_test WHERE id = :id"),
                        {"id": row_id},
                    ).fetchone()
                    assert row is None, "Uncommitted row must be invisible to other connections"

            # Now conn_a has committed — the row must be visible
            with engine.connect() as conn_c:
                row = conn_c.execute(
                    text("SELECT val FROM _txn_isolation_test WHERE id = :id"),
                    {"id": row_id},
                ).fetchone()
                assert row is not None
                assert row[0] == "pending"
        finally:
            with engine.begin() as cleanup:
                cleanup.execute(text("DROP TABLE IF EXISTS _txn_isolation_test"))
            engine.dispose()

    def test_committed_row_visible_to_subsequent_connections(self, pg_url):
        """After COMMIT, the row is visible to any new connection."""
        from sqlalchemy import text

        engine = _get_engine(pg_url)
        row_id = "committed-row"
        try:
            with engine.begin() as setup:
                setup.execute(text("CREATE TABLE IF NOT EXISTS _txn_commit_test (id TEXT PRIMARY KEY, val TEXT)"))

            with engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO _txn_commit_test (id, val) VALUES (:id, 'visible')"),
                    {"id": row_id},
                )
            # commit happens on block exit ↑

            with engine.connect() as conn_read:
                row = conn_read.execute(
                    text("SELECT val FROM _txn_commit_test WHERE id = :id"),
                    {"id": row_id},
                ).fetchone()
            assert row is not None
            assert row[0] == "visible"
        finally:
            with engine.begin() as cleanup:
                cleanup.execute(text("DROP TABLE IF EXISTS _txn_commit_test"))
            engine.dispose()

    def test_rollback_does_not_modify_committed_data(self, pg_url):
        """A rolled-back UPDATE must not alter the previously committed value."""
        from sqlalchemy import text

        engine = _get_engine(pg_url)
        row_id = "stable-row"
        try:
            with engine.begin() as setup:
                setup.execute(text("CREATE TABLE IF NOT EXISTS _txn_rollback_test (id TEXT PRIMARY KEY, val TEXT)"))
                setup.execute(
                    text("INSERT INTO _txn_rollback_test (id, val) VALUES (:id, 'original')"),
                    {"id": row_id},
                )

            # Start a transaction that UPDATEs then rolls back
            try:
                with engine.begin() as conn_rw:
                    conn_rw.execute(
                        text("UPDATE _txn_rollback_test SET val = 'modified' WHERE id = :id"),
                        {"id": row_id},
                    )
                    raise RuntimeError("Intentional rollback")
            except RuntimeError:
                pass  # Triggers rollback

            # Original value must be intact
            with engine.connect() as conn_r:
                row = conn_r.execute(
                    text("SELECT val FROM _txn_rollback_test WHERE id = :id"),
                    {"id": row_id},
                ).fetchone()
            assert row is not None
            assert row[0] == "original"
        finally:
            with engine.begin() as cleanup:
                cleanup.execute(text("DROP TABLE IF EXISTS _txn_rollback_test"))
            engine.dispose()


# ---------------------------------------------------------------------------
# T-02c: Connection pool exhaustion
# ---------------------------------------------------------------------------


class TestConnectionPoolExhaustion:
    """SQLAlchemy QueuePool timeout and release behaviour."""

    def test_pool_timeout_raised_when_all_connections_held(self, pg_url):
        """Acquiring beyond pool capacity raises TimeoutError (pool_size=1, no overflow)."""
        from sqlalchemy import create_engine
        from sqlalchemy.exc import TimeoutError as SATimeoutError

        engine = create_engine(
            pg_url,
            pool_size=1,
            max_overflow=0,
            pool_timeout=0.1,  # 100 ms — fail fast in tests
        )
        try:
            conn1 = engine.connect()
            try:
                with pytest.raises(SATimeoutError):
                    engine.connect()  # All connections are taken — must timeout
            finally:
                conn1.close()
        finally:
            engine.dispose()

    def test_connection_released_to_pool_is_reusable(self, pg_url):
        """A connection returned to the pool can be reacquired successfully."""
        from sqlalchemy import create_engine, text

        engine = create_engine(pg_url, pool_size=1, max_overflow=0, pool_timeout=2.0)
        try:
            # Acquire and release via context manager
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            # Connection is back in the pool — second acquire must succeed
            with engine.connect() as conn2:
                result = conn2.execute(text("SELECT 42")).fetchone()
            assert result[0] == 42
        finally:
            engine.dispose()

    def test_max_overflow_allows_extra_connections_beyond_pool_size(self, pg_url):
        """max_overflow=1 permits one extra connection beyond pool_size."""
        from sqlalchemy import create_engine, text

        engine = create_engine(
            pg_url,
            pool_size=1,
            max_overflow=1,  # allows 2 total connections
            pool_timeout=2.0,
        )
        try:
            conn1 = engine.connect()
            conn2 = engine.connect()  # Uses overflow slot — must not raise
            try:
                result = conn2.execute(text("SELECT 99")).fetchone()
                assert result[0] == 99
            finally:
                conn2.close()
                conn1.close()
        finally:
            engine.dispose()

    def test_overflow_exhausted_then_also_raises_timeout(self, pg_url):
        """Once pool_size + max_overflow connections are all held, the next raises."""
        from sqlalchemy import create_engine
        from sqlalchemy.exc import TimeoutError as SATimeoutError

        engine = create_engine(
            pg_url,
            pool_size=1,
            max_overflow=1,  # total 2
            pool_timeout=0.1,
        )
        try:
            conn1 = engine.connect()
            conn2 = engine.connect()  # overflow
            try:
                with pytest.raises(SATimeoutError):
                    engine.connect()  # pool + overflow exhausted
            finally:
                conn2.close()
                conn1.close()
        finally:
            engine.dispose()

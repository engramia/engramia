# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Auto-skip PostgreSQL tests when Docker is unavailable or container fails to start."""

import subprocess

import pytest


def pytest_collection_modifyitems(config, items):
    """Skip all postgres-marked tests if Docker daemon is not reachable."""
    if not _docker_available():
        skip = pytest.mark.skip(reason="Docker daemon not available — skipping postgres tests")
        for item in items:
            if "postgres" in item.keywords:
                item.add_marker(skip)


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


@pytest.fixture(scope="module")
def pg_engine():
    """Start a throwaway PostgreSQL+pgvector container and return a SQLAlchemy engine.

    Overrides the local pg_engine fixture to add container startup error
    handling — skips the entire module if the container fails to start.
    """
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed")

    try:
        with PostgresContainer("pgvector/pgvector:0.7.4-pg16") as pg:
            from sqlalchemy import create_engine, text

            engine = create_engine(pg.get_connection_url(), pool_pre_ping=True)
            with engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            yield engine
            engine.dispose()
    except Exception as exc:
        pytest.skip(f"Failed to start PostgreSQL container: {exc}")

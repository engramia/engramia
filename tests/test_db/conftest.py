# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Auto-skip database migration tests when Docker is unavailable or container fails to start."""

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
def pg_url():
    """Spin up a throwaway pgvector container shared for the whole module.

    Overrides the local pg_url fixture in test_migrations.py to add
    container startup error handling.
    """
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed — run: pip install 'testcontainers[postgres]'")

    try:
        with PostgresContainer("pgvector/pgvector:0.7.4-pg16") as pg:
            yield pg.get_connection_url()
    except Exception as exc:
        pytest.skip(f"Failed to start PostgreSQL container: {exc}")

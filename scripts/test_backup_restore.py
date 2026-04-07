#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Backup restore test — GTM launch blocker A12.

Validates that a PostgreSQL backup produced by ``backup.sh`` can be fully
restored and passes schema + data integrity checks.

Flow
----
1. Spin up a **source** ephemeral pgvector container.
2. Apply the full Alembic migration chain (``alembic upgrade head``).
3. Seed test data (extra tenant, project, and memory rows).
4. ``pg_dump`` the source database to a gzip-compressed SQL file.
5. Spin up a **target** ephemeral pgvector container.
6. Restore the dump with ``psql``.
7. Run validation checks (extension, tables, Alembic revision, seed data).
8. Tear down both containers and delete the temp backup file.
9. Exit 0 (PASS) or 1 (FAIL).

Usage
-----
Run from the project root with the postgres extras installed::

    pip install -e ".[dev,postgres]"
    python scripts/test_backup_restore.py

Environment overrides
---------------------
ENGRAMIA_BRT_SOURCE_PORT   Host port for the source container (default: 15441)
ENGRAMIA_BRT_TARGET_PORT   Host port for the target container (default: 15442)
ENGRAMIA_BRT_PGIMAGE       pgvector Docker image to use (default: pgvector/pgvector:0.7.4-pg16)
"""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────────

PGVECTOR_IMAGE: str = os.environ.get(
    "ENGRAMIA_BRT_PGIMAGE", "pgvector/pgvector:0.7.4-pg16"
)
SOURCE_PORT: int = int(os.environ.get("ENGRAMIA_BRT_SOURCE_PORT", "15441"))
TARGET_PORT: int = int(os.environ.get("ENGRAMIA_BRT_TARGET_PORT", "15442"))

DB_USER = "engramia"
DB_PASSWORD = "engramia_brt_ci"
DB_NAME = "engramia"

# All tables present after a full Alembic migration (001 → 013).
EXPECTED_TABLES: frozenset[str] = frozenset(
    {
        "memory_data",
        "memory_embeddings",
        "tenants",
        "projects",
        "api_keys",
        "audit_log",
        "jobs",
        "billing_subscriptions",
        "usage_counters",
        "overage_settings",
        "dsr_requests",
        "processed_webhook_events",
        "cloud_users",
        "alembic_version",
    }
)

# Head revision produced by migration 013.
EXPECTED_ALEMBIC_REVISION = "013"

# Seed rows inserted beyond what the migration itself creates.
SEED_TENANT_ID = "brt-tenant-1"
SEED_PROJECT_ID = "brt-project-1"
SEED_KEYS = ("brt-key-1", "brt-key-2")


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class Container:
    name: str
    port: int
    _started: bool = field(default=False, init=False)

    @property
    def dsn(self) -> str:
        return f"postgresql://{DB_USER}:{DB_PASSWORD}@localhost:{self.port}/{DB_NAME}"


# ── Logging ────────────────────────────────────────────────────────────────────


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── Docker helpers ─────────────────────────────────────────────────────────────


def _run(cmd: list[str], input: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(cmd, capture_output=True, input=input, check=check)


def start_container(c: Container) -> None:
    log(f"Starting {c.name} on port {c.port} ...")
    _run(
        [
            "docker", "run", "-d",
            "--name", c.name,
            "--rm",
            "-e", f"POSTGRES_USER={DB_USER}",
            "-e", f"POSTGRES_PASSWORD={DB_PASSWORD}",
            "-e", f"POSTGRES_DB={DB_NAME}",
            "-p", f"{c.port}:5432",
            PGVECTOR_IMAGE,
        ]
    )
    c._started = True


def stop_container(c: Container) -> None:
    if not c._started:
        return
    try:
        _run(["docker", "stop", c.name], check=False)
        log(f"Stopped {c.name}")
    except Exception:
        pass


def wait_ready(c: Container, timeout: int = 90) -> None:
    log(f"Waiting for {c.name} to accept connections ...")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = _run(
            ["docker", "exec", "-e", f"PGPASSWORD={DB_PASSWORD}",
             c.name, "pg_isready", "-U", DB_USER],
            check=False,
        )
        if result.returncode == 0:
            log(f"{c.name} ready.")
            return
        time.sleep(2)
    raise RuntimeError(f"{c.name} did not become ready within {timeout}s")


def psql_exec(c: Container, sql: str) -> subprocess.CompletedProcess[bytes]:
    """Run a single SQL statement inside the container; raise on error."""
    return _run(
        [
            "docker", "exec",
            "-e", f"PGPASSWORD={DB_PASSWORD}",
            c.name,
            "psql", "-U", DB_USER, "-d", DB_NAME,
            "-c", sql,
        ]
    )


def psql_value(c: Container, sql: str) -> str:
    """Return a single scalar result from a SQL query (tuples-only, unaligned)."""
    result = _run(
        [
            "docker", "exec",
            "-e", f"PGPASSWORD={DB_PASSWORD}",
            c.name,
            "psql", "-U", DB_USER, "-d", DB_NAME,
            "-t", "-A",
            "-c", sql,
        ]
    )
    return result.stdout.decode().strip()


def psql_column(c: Container, sql: str) -> list[str]:
    """Return each output row as a string (tuples-only, unaligned)."""
    result = _run(
        [
            "docker", "exec",
            "-e", f"PGPASSWORD={DB_PASSWORD}",
            c.name,
            "psql", "-U", DB_USER, "-d", DB_NAME,
            "-t", "-A",
            "-c", sql,
        ]
    )
    return [line for line in result.stdout.decode().splitlines() if line.strip()]


# ── Core steps ─────────────────────────────────────────────────────────────────


def run_migrations(source: Container, project_root: Path) -> None:
    log("Applying Alembic migrations to source database ...")
    env = {**os.environ, "ENGRAMIA_DATABASE_URL": source.dsn}
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        env=env,
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError("alembic upgrade head failed")
    log("Migrations applied.")


def seed_test_data(source: Container) -> None:
    log("Seeding test data ...")
    psql_exec(
        source,
        f"INSERT INTO tenants (id, name, plan_tier) "
        f"VALUES ('{SEED_TENANT_ID}', 'BRT Tenant', 'pro') "
        f"ON CONFLICT DO NOTHING;",
    )
    psql_exec(
        source,
        f"INSERT INTO projects (id, tenant_id, name) "
        f"VALUES ('{SEED_PROJECT_ID}', '{SEED_TENANT_ID}', 'BRT Project') "
        f"ON CONFLICT DO NOTHING;",
    )
    for key in SEED_KEYS:
        psql_exec(
            source,
            f"INSERT INTO memory_data (key, data, tenant_id, project_id) "
            f"VALUES ('{key}', '{{\"brt\": true}}', '{SEED_TENANT_ID}', '{SEED_PROJECT_ID}') "
            f"ON CONFLICT DO NOTHING;",
        )
    log(f"Seeded: tenant={SEED_TENANT_ID}, project={SEED_PROJECT_ID}, keys={SEED_KEYS}")


def create_backup(source: Container, backup_path: Path) -> None:
    log("Creating pg_dump backup ...")
    result = _run(
        [
            "docker", "exec",
            "-e", f"PGPASSWORD={DB_PASSWORD}",
            source.name,
            "pg_dump", "-U", DB_USER, "--no-password", DB_NAME,
        ]
    )
    with gzip.open(backup_path, "wb") as fh:
        fh.write(result.stdout)
    size_kb = backup_path.stat().st_size // 1024
    log(f"Backup written: {backup_path} ({size_kb} KiB compressed)")


def restore_backup(target: Container, backup_path: Path) -> None:
    log("Restoring backup into target database ...")
    with gzip.open(backup_path, "rb") as fh:
        sql_bytes = fh.read()

    result = subprocess.run(
        [
            "docker", "exec", "-i",
            "-e", f"PGPASSWORD={DB_PASSWORD}",
            target.name,
            "psql", "-U", DB_USER, "-d", DB_NAME,
            "-v", "ON_ERROR_STOP=1",
        ],
        input=sql_bytes,
        capture_output=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr.decode())
        raise RuntimeError("psql restore failed")
    log("Restore complete.")


# ── Validation ─────────────────────────────────────────────────────────────────


def validate(target: Container) -> list[str]:
    failures: list[str] = []

    # 1. pgvector extension active
    ext_count = psql_value(target, "SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector';")
    if ext_count != "1":
        failures.append(f"pgvector extension not active (count={ext_count!r})")

    # 2. All expected tables present
    present_tables = set(
        psql_column(
            target,
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;",
        )
    )
    missing = EXPECTED_TABLES - present_tables
    if missing:
        failures.append(f"Missing tables after restore: {', '.join(sorted(missing))}")

    extra = present_tables - EXPECTED_TABLES
    if extra:
        # Informational — not a failure, but log it so we can update the expected set
        log(f"  INFO: unexpected tables present (may need EXPECTED_TABLES update): {', '.join(sorted(extra))}")

    # 3. Alembic schema at head revision
    revision = psql_value(target, "SELECT version_num FROM alembic_version;")
    if revision != EXPECTED_ALEMBIC_REVISION:
        failures.append(
            f"Alembic revision mismatch: expected {EXPECTED_ALEMBIC_REVISION!r}, got {revision!r}"
        )

    # 4. Default tenant seeded by migration 003 is present
    default_tenant = psql_value(target, "SELECT COUNT(*) FROM tenants WHERE id = 'default';")
    if default_tenant != "1":
        failures.append("Default tenant (id='default') missing from restored DB")

    # 5. Test seed data preserved through backup/restore cycle
    seed_tenant = psql_value(target, f"SELECT COUNT(*) FROM tenants WHERE id = '{SEED_TENANT_ID}';")
    if seed_tenant != "1":
        failures.append(f"Seed tenant {SEED_TENANT_ID!r} missing from restored DB")

    seed_keys_count = psql_value(
        target,
        f"SELECT COUNT(*) FROM memory_data WHERE key LIKE 'brt-key-%' "
        f"AND tenant_id = '{SEED_TENANT_ID}';",
    )
    expected_key_count = str(len(SEED_KEYS))
    if seed_keys_count != expected_key_count:
        failures.append(
            f"Expected {expected_key_count} seed memory_data rows, got {seed_keys_count!r}"
        )

    # 6. Total tenant count sanity (default + our seed = ≥ 2)
    total_tenants = psql_value(target, "SELECT COUNT(*) FROM tenants;")
    if int(total_tenants) < 2:
        failures.append(f"Expected ≥2 tenants in restored DB, got {total_tenants}")

    return failures


# ── Entry point ────────────────────────────────────────────────────────────────


def main() -> int:
    run_id = uuid.uuid4().hex[:8]
    source = Container(name=f"engramia-brt-src-{run_id}", port=SOURCE_PORT)
    target = Container(name=f"engramia-brt-tgt-{run_id}", port=TARGET_PORT)
    tmp_dir = Path(tempfile.mkdtemp(prefix="engramia-brt-"))
    backup_path = tmp_dir / f"brt_{run_id}.sql.gz"
    project_root = Path(__file__).resolve().parent.parent

    log(f"{'='*60}")
    log(f"Engramia Backup Restore Test  run={run_id}")
    log(f"  image       : {PGVECTOR_IMAGE}")
    log(f"  source port : {SOURCE_PORT}")
    log(f"  target port : {TARGET_PORT}")
    log(f"  project root: {project_root}")
    log(f"  backup path : {backup_path}")
    log(f"{'='*60}")

    # Verify Docker is available before doing anything
    if shutil.which("docker") is None:
        log("ERROR: 'docker' not found in PATH")
        return 1

    # Verify alembic is available
    if shutil.which("alembic") is None:
        log("ERROR: 'alembic' not found in PATH — install with: pip install -e '.[postgres]'")
        return 1

    t_start = time.monotonic()

    try:
        # ── Phase 1: Source DB ─────────────────────────────────────────
        log("[Phase 1/4] Preparing source database")
        start_container(source)
        wait_ready(source)
        run_migrations(source, project_root)
        seed_test_data(source)

        # ── Phase 2: Backup ────────────────────────────────────────────
        log("[Phase 2/4] Creating backup")
        create_backup(source, backup_path)

        # ── Phase 3: Restore ───────────────────────────────────────────
        log("[Phase 3/4] Restoring into target database")
        start_container(target)
        wait_ready(target)
        restore_backup(target, backup_path)

        # ── Phase 4: Validate ──────────────────────────────────────────
        log("[Phase 4/4] Running validation checks")
        failures = validate(target)

        elapsed = time.monotonic() - t_start

        if failures:
            log(f"\nRESULT: FAIL  ({elapsed:.1f}s)")
            for msg in failures:
                log(f"  ✗ {msg}")
            return 1

        log(f"\nRESULT: PASS  ({elapsed:.1f}s)")
        log(f"  ✓ pgvector extension active")
        log(f"  ✓ all {len(EXPECTED_TABLES)} expected tables present")
        log(f"  ✓ alembic_version = {EXPECTED_ALEMBIC_REVISION}")
        log(f"  ✓ default tenant present")
        log(f"  ✓ seed tenant {SEED_TENANT_ID!r} present")
        log(f"  ✓ {len(SEED_KEYS)} seed memory_data rows present")
        return 0

    except Exception as exc:
        elapsed = time.monotonic() - t_start
        log(f"\nRESULT: ERROR  ({elapsed:.1f}s) — {exc}")
        return 1

    finally:
        log("\nCleaning up ...")
        stop_container(source)
        stop_container(target)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        log("Done.")


if __name__ == "__main__":
    sys.exit(main())

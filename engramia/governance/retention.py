# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Retention policy management (Phase 5.6).

Resolves effective data retention per scope (most specific wins):

    pattern.expires_at  >  project.retention_days  >  tenant.retention_days  >  global default

Usage::

    manager = RetentionManager(engine=engine)
    result = manager.apply(dry_run=True)   # preview what would be deleted
    result = manager.apply(dry_run=False)  # actually delete expired patterns
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from sqlalchemy import text

from engramia._context import get_scope
from engramia._util import PATTERNS_PREFIX

_log = logging.getLogger(__name__)

# Global fallback retention — 365 days if nothing configured
_DEFAULT_RETENTION_DAYS = 365

# Batch size to avoid long transactions
_DELETE_BATCH_SIZE = 100


@dataclass
class PurgeResult:
    """Result of a retention cleanup run.

    Args:
        purged_count: Number of patterns deleted.
        dry_run: True if no actual deletion occurred.
        purged_keys: Keys that were (or would be) deleted.
    """

    purged_count: int
    dry_run: bool
    purged_keys: list[str] = field(default_factory=list)


class RetentionManager:
    """Applies retention policies to patterns in the current scope.

    Works with both storage backends. For PostgreSQL, queries the ``projects``
    and ``tenants`` tables to resolve per-scope retention. For JSON storage,
    falls back to the global default retention.

    Args:
        engine: SQLAlchemy engine for DB lookups. None = JSON storage mode.
        default_retention_days: Global fallback when no scope policy is set.
    """

    def __init__(
        self,
        engine=None,
        default_retention_days: int = _DEFAULT_RETENTION_DAYS,
    ) -> None:
        self._engine = engine
        self._default_days = default_retention_days

    def get_policy(self, tenant_id: str, project_id: str) -> int:
        """Resolve effective retention in days for a scope.

        Order: project.retention_days → tenant.retention_days → global default.

        Args:
            tenant_id: Tenant identifier.
            project_id: Project identifier.

        Returns:
            Effective retention in days.
        """
        if self._engine is None:
            return self._default_days

        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT p.retention_days AS proj_days, t.retention_days AS tenant_days "
                        "FROM projects p "
                        "JOIN tenants t ON t.id = p.tenant_id "
                        "WHERE p.id = :pid AND p.tenant_id = :tid"
                    ),
                    {"pid": project_id, "tid": tenant_id},
                ).fetchone()

            if row is None:
                return self._default_days
            if row.proj_days is not None:
                return int(row.proj_days)
            if row.tenant_days is not None:
                return int(row.tenant_days)
        except Exception as exc:
            _log.warning("RetentionManager.get_policy failed: %s — using default", exc)

        return self._default_days

    def set_project_policy(self, project_id: str, tenant_id: str, days: int | None) -> None:
        """Set or clear retention for a project.

        Args:
            project_id: Project to update.
            tenant_id: Tenant the project belongs to (for scope check).
            days: Retention days, or None to inherit from tenant.
        """
        if self._engine is None:
            _log.warning("RetentionManager: no DB engine — cannot persist policy")
            return
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text("UPDATE projects SET retention_days = :days WHERE id = :pid AND tenant_id = :tid"),
                    {"days": days, "pid": project_id, "tid": tenant_id},
                )
        except Exception as exc:
            _log.error("RetentionManager.set_project_policy failed: %s", exc)
            raise

    def set_tenant_policy(self, tenant_id: str, days: int | None) -> None:
        """Set or clear retention for a tenant.

        Args:
            tenant_id: Tenant to update.
            days: Retention days, or None to use global default.
        """
        if self._engine is None:
            _log.warning("RetentionManager: no DB engine — cannot persist policy")
            return
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text("UPDATE tenants SET retention_days = :days WHERE id = :tid"),
                    {"days": days, "tid": tenant_id},
                )
        except Exception as exc:
            _log.error("RetentionManager.set_tenant_policy failed: %s", exc)
            raise

    def apply(self, storage, dry_run: bool = False) -> PurgeResult:
        """Delete patterns that have passed their expiry time in the current scope.

        For PostgreSQL storage, uses the ``expires_at`` column directly (fast).
        For JSON storage, falls back to timestamp-based retention from the
        effective retention policy.

        Args:
            storage: StorageBackend instance (scoped to current tenant/project).
            dry_run: If True, return what would be deleted without deleting.

        Returns:
            PurgeResult with count and list of purged keys.
        """
        scope = get_scope()

        # Try DB-backed fast path first (Postgres + expires_at column)
        if self._engine is not None and _is_postgres_storage(storage):
            return self._apply_postgres(storage, scope, dry_run)

        # Fallback: scan patterns by timestamp
        return self._apply_storage_scan(storage, scope, dry_run)

    def _apply_postgres(self, storage, scope, dry_run: bool) -> PurgeResult:
        """Fast purge using the expires_at column."""
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT key FROM memory_data "
                        "WHERE tenant_id = :tid AND project_id = :pid "
                        "AND expires_at IS NOT NULL AND expires_at <= :now "
                        "AND key LIKE :prefix"
                    ),
                    {
                        "tid": scope.tenant_id,
                        "pid": scope.project_id,
                        "now": now_iso,
                        "prefix": f"{PATTERNS_PREFIX}/%",
                    },
                ).fetchall()

            expired_keys = [row.key for row in rows]

            if not dry_run:
                for i in range(0, len(expired_keys), _DELETE_BATCH_SIZE):
                    batch = expired_keys[i : i + _DELETE_BATCH_SIZE]
                    for key in batch:
                        storage.delete(key)
                _log.info(
                    "RetentionManager: purged %d expired patterns in %s/%s",
                    len(expired_keys),
                    scope.tenant_id,
                    scope.project_id,
                )

            return PurgeResult(
                purged_count=len(expired_keys),
                dry_run=dry_run,
                purged_keys=expired_keys,
            )

        except Exception as exc:
            _log.error("RetentionManager._apply_postgres failed: %s", exc)
            raise

    def _apply_storage_scan(self, storage, scope, dry_run: bool) -> PurgeResult:
        """Fallback: scan pattern timestamps against effective retention policy."""
        retention_days = self.get_policy(scope.tenant_id, scope.project_id)
        cutoff_ts = time.time() - retention_days * 86400

        keys = storage.list_keys(prefix=PATTERNS_PREFIX)
        expired: list[str] = []

        for key in keys:
            data = storage.load(key)
            if data is None:
                continue
            ts = data.get("timestamp", 0)
            if ts > 0 and ts < cutoff_ts:
                expired.append(key)

        if not dry_run:
            for key in expired:
                storage.delete(key)
            _log.info(
                "RetentionManager: purged %d patterns older than %d days in %s/%s",
                len(expired),
                retention_days,
                scope.tenant_id,
                scope.project_id,
            )

        return PurgeResult(purged_count=len(expired), dry_run=dry_run, purged_keys=expired)


def compute_expiry_iso(retention_days: int) -> str:
    """Return an ISO-8601 UTC timestamp ``retention_days`` from now.

    Args:
        retention_days: Number of days until expiry.

    Returns:
        ISO-8601 UTC string (``YYYY-MM-DDTHH:MM:SSZ``).
    """
    expiry_ts = time.time() + retention_days * 86400
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expiry_ts))


def _is_postgres_storage(storage) -> bool:
    return type(storage).__name__ == "PostgresStorage"

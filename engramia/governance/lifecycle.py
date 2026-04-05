# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Background data lifecycle jobs (Phase 5.6).

Maintenance operations that keep the database clean over time:

- cleanup_expired_patterns — delete patterns past their expires_at date
- compact_audit_log        — archive/purge old audit_log entries
- cleanup_old_jobs         — remove completed/failed jobs past retention

These are dispatched via the existing async job system. Each function
receives the Memory instance and a params dict (same signature as other
job dispatchers in engramia/jobs/dispatch.py).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from engramia._context import get_scope

_log = logging.getLogger(__name__)

# Default retention for audit logs (days)
_DEFAULT_AUDIT_RETENTION_DAYS = 90
# Default retention for completed/failed jobs (days)
_DEFAULT_JOB_RETENTION_DAYS = 30


def cleanup_expired_patterns(memory, params: dict[str, Any]) -> dict[str, Any]:
    """Delete all patterns in the current scope that have passed their expires_at.

    Job params:
        dry_run (bool): Preview without deleting. Default False.

    Returns:
        dict with ``purged_count`` and ``dry_run`` keys.
    """
    from engramia.governance.retention import RetentionManager

    engine = getattr(memory.storage, "_engine", None)
    manager = RetentionManager(engine=engine)
    dry_run = bool(params.get("dry_run", False))
    result = manager.apply(memory.storage, dry_run=dry_run)

    return {"purged_count": result.purged_count, "dry_run": result.dry_run}


def compact_audit_log(memory, params: dict[str, Any]) -> dict[str, Any]:
    """Delete audit_log entries older than the configured retention period.

    Only runs against PostgreSQL storage. No-op for JSON storage.

    Job params:
        retention_days (int): Age threshold in days. Default 90.
        dry_run (bool): Preview without deleting. Default False.

    Returns:
        dict with ``deleted_count`` and ``dry_run`` keys.
    """
    engine = getattr(memory.storage, "_engine", None)
    if engine is None:
        _log.info("compact_audit_log: no DB engine, skipping.")
        return {"deleted_count": 0, "dry_run": False}

    retention_days = int(params.get("retention_days", _DEFAULT_AUDIT_RETENTION_DAYS))
    dry_run = bool(params.get("dry_run", False))
    scope = get_scope()
    cutoff = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(time.time() - retention_days * 86400),
    )

    try:
        from sqlalchemy import text

        if dry_run:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM audit_log "
                        "WHERE tenant_id = :tid AND created_at < :cutoff"
                    ),
                    {"tid": scope.tenant_id, "cutoff": cutoff},
                ).fetchone()
            count = int(row[0]) if row else 0
            return {"deleted_count": count, "dry_run": True}

        with engine.begin() as conn:
            r = conn.execute(
                text(
                    "DELETE FROM audit_log "
                    "WHERE tenant_id = :tid AND created_at < :cutoff"
                ),
                {"tid": scope.tenant_id, "cutoff": cutoff},
            )
        _log.info("compact_audit_log: deleted %d entries older than %s", r.rowcount, cutoff)
        return {"deleted_count": r.rowcount, "dry_run": False}

    except Exception as exc:
        _log.error("compact_audit_log failed: %s", exc)
        raise


def cleanup_old_jobs(memory, params: dict[str, Any]) -> dict[str, Any]:
    """Delete completed/failed jobs older than the configured retention period.

    Job params:
        retention_days (int): Age threshold in days. Default 30.
        dry_run (bool): Preview without deleting. Default False.

    Returns:
        dict with ``deleted_count`` and ``dry_run`` keys.
    """
    engine = getattr(memory.storage, "_engine", None)
    if engine is None:
        return {"deleted_count": 0, "dry_run": False}

    retention_days = int(params.get("retention_days", _DEFAULT_JOB_RETENTION_DAYS))
    dry_run = bool(params.get("dry_run", False))
    scope = get_scope()
    cutoff = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(time.time() - retention_days * 86400),
    )
    terminal_statuses = ("completed", "failed", "cancelled", "expired")

    try:
        from sqlalchemy import text

        status_placeholders = ", ".join(f":s{i}" for i in range(len(terminal_statuses)))
        status_params = {f"s{i}": s for i, s in enumerate(terminal_statuses)}
        base_params = {"tid": scope.tenant_id, "pid": scope.project_id, "cutoff": cutoff}
        all_params = {**base_params, **status_params}

        count_query = (
            f"SELECT COUNT(*) FROM jobs "
            f"WHERE tenant_id = :tid AND project_id = :pid "
            f"AND created_at < :cutoff AND status IN ({status_placeholders})"
        )
        delete_query = (
            f"DELETE FROM jobs "
            f"WHERE tenant_id = :tid AND project_id = :pid "
            f"AND created_at < :cutoff AND status IN ({status_placeholders})"
        )

        if dry_run:
            with engine.connect() as conn:
                row = conn.execute(text(count_query), all_params).fetchone()
            count = int(row[0]) if row else 0
            return {"deleted_count": count, "dry_run": True}

        with engine.begin() as conn:
            r = conn.execute(text(delete_query), all_params)
        _log.info("cleanup_old_jobs: deleted %d terminal jobs", r.rowcount)
        return {"deleted_count": r.rowcount, "dry_run": False}

    except Exception as exc:
        _log.error("cleanup_old_jobs failed: %s", exc)
        raise


class LifecycleJobs:
    """Namespace for all lifecycle job dispatch functions.

    Used by the job dispatch table in ``engramia/jobs/dispatch.py``.
    """

    cleanup_expired_patterns = staticmethod(cleanup_expired_patterns)
    compact_audit_log = staticmethod(compact_audit_log)
    cleanup_old_jobs = staticmethod(cleanup_old_jobs)

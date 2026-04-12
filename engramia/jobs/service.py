# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""DB-backed job queue using PostgreSQL FOR UPDATE SKIP LOCKED.

JobService is the core interface for submitting, querying, and executing
async jobs. It works with both PostgreSQL (production) and an in-memory
fallback for JSON storage mode.
"""

import concurrent.futures
import contextvars
import logging
import time
import traceback
import uuid
from typing import Any

from engramia._context import get_scope, reset_scope, set_scope
from engramia.jobs.dispatch import dispatch_job
from engramia.jobs.models import JobInfo, JobOperation, JobStatus, JobSubmitResult
from engramia.telemetry import metrics as _metrics
from engramia.telemetry.context import get_request_id, reset_request_id, set_request_id
from engramia.types import Scope

_log = logging.getLogger(__name__)


def _run_jobs(
    executor: concurrent.futures.Executor | None,
    execute_fn,
    jobs: list[dict],
) -> None:
    """Run a batch of jobs serially (executor=None) or in parallel.

    Each parallel job gets its own ``contextvars`` snapshot so that
    ``set_scope`` / ``set_request_id`` inside ``execute_fn`` do not leak
    across concurrent jobs sharing the same executor pool.
    """
    if not jobs:
        return
    if executor is None or len(jobs) == 1:
        for job in jobs:
            execute_fn(job)
        return

    futures = []
    for job in jobs:
        ctx = contextvars.copy_context()
        futures.append(executor.submit(ctx.run, execute_fn, job))
    concurrent.futures.wait(futures)
    # Surface exceptions that bubbled past the per-job try/except.
    for fut in futures:
        exc = fut.exception()
        if exc is not None:
            _log.error("Unexpected exception escaped job execution: %s", exc)


#: Default job expiry: 1 hour from creation.
_DEFAULT_EXPIRES_SECONDS = 3600


class JobService:
    """Manages async job lifecycle backed by PostgreSQL or in-memory store.

    In PostgreSQL mode, uses ``SELECT ... FOR UPDATE SKIP LOCKED`` for
    concurrent worker safety. In JSON/memory mode, uses a simple dict.
    """

    def __init__(self, engine: Any | None = None, memory: Any | None = None) -> None:
        """Initialize the job service.

        Args:
            engine: SQLAlchemy engine for PostgreSQL mode. None for in-memory.
            memory: Memory instance for executing job operations.
        """
        self._engine = engine
        self._memory = memory
        # In-memory fallback for JSON storage / tests
        self._mem_store: dict[str, dict] = {}

        if engine is None:
            _log.warning(
                "Async jobs running in best-effort in-memory mode — jobs are lost on crash. "
                "Configure ENGRAMIA_DATABASE_URL for durable job execution."
            )

    @property
    def _use_db(self) -> bool:
        return self._engine is not None

    def submit(
        self,
        operation: str,
        params: dict,
        scope: Scope | None = None,
        key_id: str | None = None,
        max_execution_seconds: int | None = None,
    ) -> JobSubmitResult:
        """Submit a new job for async processing.

        Args:
            operation: Operation name (must be a valid JobOperation).
            params: Serialized request parameters.
            scope: Tenant/project scope. Uses current context if None.
            key_id: API key ID of the submitter.
            max_execution_seconds: Optional hard cap on execution time. If the
                job runs longer than this, the worker marks it expired and frees
                the concurrency slot. Defaults to passive TTL-based expiry.

        Returns:
            JobSubmitResult with the job ID and initial status.
        """
        if operation not in {op.value for op in JobOperation}:
            raise ValueError(f"Unknown operation: {operation}")

        scope = scope or get_scope()
        request_id = get_request_id()
        job_id = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        expires = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() + _DEFAULT_EXPIRES_SECONDS),
        )

        if self._use_db:
            self._db_submit(
                job_id,
                operation,
                params,
                scope,
                key_id,
                now,
                expires,
                request_id,
                max_execution_seconds,
            )
        else:
            self._mem_store[job_id] = {
                "id": job_id,
                "tenant_id": scope.tenant_id,
                "project_id": scope.project_id,
                "key_id": key_id,
                "request_id": request_id or None,
                "operation": operation,
                "params": params,
                "status": JobStatus.PENDING,
                "result": None,
                "error": None,
                "attempts": 0,
                "max_attempts": 3,
                "created_at": now,
                "scheduled_at": None,
                "started_at": None,
                "completed_at": None,
                "expires_at": expires,
                "max_execution_seconds": max_execution_seconds,
            }

        _log.info("Job %s submitted: operation=%s, scope=%s/%s", job_id, operation, scope.tenant_id, scope.project_id)
        _metrics.inc_job_submitted(operation)
        return JobSubmitResult(job_id=job_id, status=JobStatus.PENDING)

    def get(self, job_id: str, scope: Scope | None = None) -> JobInfo | None:
        """Get job info by ID, scoped to tenant/project.

        Args:
            job_id: UUID of the job.
            scope: Tenant/project scope. Uses current context if None.

        Returns:
            JobInfo or None if not found (or not in scope).
        """
        scope = scope or get_scope()

        if self._use_db:
            return self._db_get(job_id, scope)

        job = self._mem_store.get(job_id)
        if job is None:
            return None
        if job["tenant_id"] != scope.tenant_id or job["project_id"] != scope.project_id:
            return None
        return self._to_info(job)

    def list_jobs(
        self,
        scope: Scope | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[JobInfo]:
        """List jobs for a tenant/project, optionally filtered by status.

        Args:
            scope: Tenant/project scope. Uses current context if None.
            status: Filter by job status (e.g. 'pending', 'completed').
            limit: Maximum number of jobs to return.

        Returns:
            List of JobInfo, newest first.
        """
        scope = scope or get_scope()

        if self._use_db:
            return self._db_list(scope, status, limit)

        jobs = [
            j
            for j in self._mem_store.values()
            if j["tenant_id"] == scope.tenant_id
            and j["project_id"] == scope.project_id
            and (status is None or j["status"] == status)
        ]
        jobs.sort(key=lambda j: j["created_at"], reverse=True)
        return [self._to_info(j) for j in jobs[:limit]]

    def cancel(self, job_id: str, scope: Scope | None = None) -> bool:
        """Cancel a pending job. Running jobs cannot be cancelled.

        Args:
            job_id: UUID of the job.
            scope: Tenant/project scope.

        Returns:
            True if the job was cancelled, False if not found or not cancellable.
        """
        scope = scope or get_scope()

        if self._use_db:
            return self._db_cancel(job_id, scope)

        job = self._mem_store.get(job_id)
        if job is None:
            return False
        if job["tenant_id"] != scope.tenant_id or job["project_id"] != scope.project_id:
            return False
        if job["status"] != JobStatus.PENDING:
            return False
        job["status"] = JobStatus.CANCELLED
        job["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return True

    def poll_and_execute(
        self,
        batch_size: int = 1,
        executor: concurrent.futures.Executor | None = None,
    ) -> int:
        """Claim and execute pending jobs.

        Args:
            batch_size: Maximum number of jobs to claim in one poll.
            executor: Optional thread/process pool for parallel execution.
                When provided, claimed jobs are dispatched concurrently (each
                with its own ``contextvars`` snapshot so scope/request_id do
                not leak between jobs). When ``None``, jobs run serially in
                the calling thread.

        Returns:
            Number of jobs executed.
        """
        if self._use_db:
            return self._db_poll_and_execute(batch_size, executor)
        return self._mem_poll_and_execute(batch_size, executor)

    def reap_expired(self) -> int:
        """Mark expired running jobs as expired. Returns count reaped."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if self._use_db:
            return self._db_reap_expired(now)

        count = 0
        for job in self._mem_store.values():
            if job["status"] == JobStatus.RUNNING and job.get("expires_at") and job["expires_at"] < now:
                job["status"] = JobStatus.EXPIRED
                job["error"] = "Job expired (exceeded time limit)"
                job["completed_at"] = now
                count += 1
        return count

    # ------------------------------------------------------------------
    # In-memory implementation (JSON storage / tests)
    # ------------------------------------------------------------------

    def _mem_poll_and_execute(
        self,
        batch_size: int,
        executor: concurrent.futures.Executor | None = None,
    ) -> int:
        now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        pending = [
            j
            for j in self._mem_store.values()
            if j["status"] == JobStatus.PENDING
            and j["attempts"] < j["max_attempts"]
            and (j["scheduled_at"] is None or j["scheduled_at"] <= now_str)
        ]
        pending.sort(key=lambda j: j["created_at"])
        claimed = pending[:batch_size]

        for job in claimed:
            job["status"] = JobStatus.RUNNING
            job["started_at"] = now_str
            job["attempts"] += 1

        _run_jobs(executor, self._execute_job, claimed)
        return len(claimed)

    def _execute_job(self, job: dict) -> None:
        """Execute a single job dict, updating status and result in place.

        If ``max_execution_seconds`` is set on the job, execution is run in a
        thread and cancelled (marked expired) if the deadline is exceeded.
        """
        max_exec = job.get("max_execution_seconds")
        scope = Scope(tenant_id=job["tenant_id"], project_id=job["project_id"])
        token = set_scope(scope)
        rid_token = set_request_id(job.get("request_id") or "")
        try:
            if max_exec is not None:
                # Capture context vars so the worker thread sees the same scope/request_id.
                ctx = contextvars.copy_context()
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    fut = ex.submit(ctx.run, dispatch_job, self._memory, job["operation"], job["params"])
                    try:
                        result = fut.result(timeout=max_exec)
                    except concurrent.futures.TimeoutError:
                        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        job["status"] = JobStatus.EXPIRED
                        job["error"] = f"Job exceeded max execution time ({max_exec}s)"
                        job["completed_at"] = now
                        _log.warning("Job %s timed out after %ds", job["id"], max_exec)
                        return
            else:
                result = dispatch_job(self._memory, job["operation"], job["params"])

            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            job["status"] = JobStatus.COMPLETED
            job["result"] = result
            job["completed_at"] = now
            _log.info("Job %s completed: operation=%s", job["id"], job["operation"])
            _metrics.inc_job_completed(job["operation"], "completed")
        except Exception as exc:
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _log.warning("Job %s failed (attempt %d): %s", job["id"], job["attempts"], exc)
            if job["attempts"] >= job["max_attempts"]:
                job["status"] = JobStatus.FAILED
                job["error"] = f"{type(exc).__name__}: {exc}"
                job["completed_at"] = now
                _metrics.inc_job_completed(job["operation"], "failed")
            else:
                # Return to pending with backoff
                job["status"] = JobStatus.PENDING
                backoff = 2 ** job["attempts"]
                job["scheduled_at"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(time.time() + backoff),
                )
        finally:
            reset_scope(token)
            reset_request_id(rid_token)

    # ------------------------------------------------------------------
    # PostgreSQL implementation
    # ------------------------------------------------------------------

    def _db_submit(
        self, job_id, operation, params, scope, key_id, now, expires, request_id=None, max_execution_seconds=None
    ):
        from sqlalchemy import text

        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO jobs (id, tenant_id, project_id, key_id, request_id, operation, "
                    "params, status, attempts, max_attempts, created_at, expires_at, max_execution_seconds) "
                    "VALUES (:id, :tid, :pid, :kid, :rid, :op, :params, 'pending', 0, 3, :now, :exp, :max_exec)"
                ),
                {
                    "id": job_id,
                    "tid": scope.tenant_id,
                    "pid": scope.project_id,
                    "kid": key_id,
                    "rid": request_id or None,
                    "op": operation,
                    "params": params,
                    "now": now,
                    "exp": expires,
                    "max_exec": max_execution_seconds,
                },
            )

    def _db_get(self, job_id, scope):
        from sqlalchemy import text

        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, operation, status, result, error, attempts, "
                    "created_at, started_at, completed_at, request_id "
                    "FROM jobs WHERE id = :id AND tenant_id = :tid AND project_id = :pid"
                ),
                {"id": job_id, "tid": scope.tenant_id, "pid": scope.project_id},
            ).fetchone()

        if row is None:
            return None
        return JobInfo(
            id=row[0],
            operation=row[1],
            status=row[2],
            result=row[3],
            error=row[4],
            attempts=row[5],
            created_at=row[6],
            started_at=row[7],
            completed_at=row[8],
            request_id=row[9],
        )

    def _db_list(self, scope, status_filter, limit):
        from sqlalchemy import text

        query = (
            "SELECT id, operation, status, result, error, attempts, "
            "created_at, started_at, completed_at, request_id "
            "FROM jobs WHERE tenant_id = :tid AND project_id = :pid"
        )
        params: dict = {"tid": scope.tenant_id, "pid": scope.project_id}
        if status_filter:
            query += " AND status = :status"
            params["status"] = status_filter
        query += " ORDER BY created_at DESC LIMIT :limit"
        params["limit"] = limit

        with self._engine.connect() as conn:
            rows = conn.execute(text(query), params).fetchall()

        return [
            JobInfo(
                id=r[0],
                operation=r[1],
                status=r[2],
                result=r[3],
                error=r[4],
                attempts=r[5],
                created_at=r[6],
                started_at=r[7],
                completed_at=r[8],
                request_id=r[9],
            )
            for r in rows
        ]

    def _db_cancel(self, job_id, scope):
        from sqlalchemy import text

        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "UPDATE jobs SET status = 'cancelled', completed_at = now()::text "
                    "WHERE id = :id AND tenant_id = :tid AND project_id = :pid "
                    "AND status = 'pending'"
                ),
                {"id": job_id, "tid": scope.tenant_id, "pid": scope.project_id},
            )
            return result.rowcount > 0

    def _db_poll_and_execute(self, batch_size, executor=None):
        from sqlalchemy import text

        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    "UPDATE jobs SET status = 'running', started_at = now()::text, "
                    "attempts = attempts + 1 "
                    "WHERE id IN ("
                    "  SELECT id FROM jobs "
                    "  WHERE status = 'pending' AND attempts < max_attempts "
                    "  AND (scheduled_at IS NULL OR scheduled_at <= now()::text) "
                    "  ORDER BY created_at "
                    "  LIMIT :batch "
                    "  FOR UPDATE SKIP LOCKED"
                    ") RETURNING id, operation, params, tenant_id, project_id, attempts, max_attempts, request_id, max_execution_seconds"
                ),
                {"batch": batch_size},
            ).fetchall()

        job_dicts = [
            {
                "id": row[0],
                "operation": row[1],
                "params": row[2],
                "tenant_id": row[3],
                "project_id": row[4],
                "attempts": row[5],
                "max_attempts": row[6],
                "request_id": row[7],
                "max_execution_seconds": row[8],
            }
            for row in rows
        ]
        _run_jobs(executor, self._db_execute_one, job_dicts)
        return len(job_dicts)

    def _db_execute_one(self, job_dict):
        from sqlalchemy import text

        max_exec = job_dict.get("max_execution_seconds")
        scope = Scope(tenant_id=job_dict["tenant_id"], project_id=job_dict["project_id"])
        token = set_scope(scope)
        rid_token = set_request_id(job_dict.get("request_id") or "")
        try:
            if max_exec is not None:
                # Capture context vars so the worker thread sees the same scope/request_id.
                ctx = contextvars.copy_context()
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    fut = ex.submit(ctx.run, dispatch_job, self._memory, job_dict["operation"], job_dict["params"])
                    try:
                        result = fut.result(timeout=max_exec)
                    except concurrent.futures.TimeoutError:
                        with self._engine.begin() as conn:
                            conn.execute(
                                text(
                                    "UPDATE jobs SET status = 'expired', "
                                    "error = :error, completed_at = now()::text WHERE id = :id"
                                ),
                                {
                                    "id": job_dict["id"],
                                    "error": f"Job exceeded max execution time ({max_exec}s)",
                                },
                            )
                        _log.warning("Job %s timed out after %ds", job_dict["id"], max_exec)
                        return
            else:
                result = dispatch_job(self._memory, job_dict["operation"], job_dict["params"])

            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE jobs SET status = 'completed', result = :result, "
                        "completed_at = now()::text WHERE id = :id"
                    ),
                    {"id": job_dict["id"], "result": result},
                )
            _log.info("Job %s completed: operation=%s", job_dict["id"], job_dict["operation"])
            _metrics.inc_job_completed(job_dict["operation"], "completed")
        except Exception as exc:
            _log.warning(
                "Job %s failed (attempt %d): %s",
                job_dict["id"],
                job_dict["attempts"],
                exc,
            )
            tb = traceback.format_exc()
            # Log full traceback server-side only — never exposed to API clients.
            _log.error(
                "Job %s failed permanently after %d attempts:\n%s",
                job_dict["id"],
                job_dict["attempts"],
                tb,
            )
            if job_dict["attempts"] >= job_dict["max_attempts"]:
                _metrics.inc_job_completed(job_dict["operation"], "failed")
                # Store only a sanitized public error message in the DB.
                public_error = f"{type(exc).__name__}: {exc}"
                with self._engine.begin() as conn:
                    conn.execute(
                        text(
                            "UPDATE jobs SET status = 'failed', "
                            "error = :error, completed_at = now()::text WHERE id = :id"
                        ),
                        {"id": job_dict["id"], "error": public_error},
                    )
            else:
                backoff = 2 ** job_dict["attempts"]
                scheduled = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(time.time() + backoff),
                )
                with self._engine.begin() as conn:
                    conn.execute(
                        text("UPDATE jobs SET status = 'pending', scheduled_at = :sched WHERE id = :id"),
                        {"id": job_dict["id"], "sched": scheduled},
                    )
        finally:
            reset_scope(token)
            reset_request_id(rid_token)

    def _db_reap_expired(self, now):
        from sqlalchemy import text

        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "UPDATE jobs SET status = 'expired', "
                    "error = 'Job expired (exceeded time limit)', "
                    "completed_at = :now "
                    "WHERE status = 'running' AND expires_at IS NOT NULL AND expires_at < :now"
                ),
                {"now": now},
            )
            return result.rowcount

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_info(job: dict) -> JobInfo:
        return JobInfo(
            id=job["id"],
            operation=job["operation"],
            status=job["status"],
            result=job.get("result"),
            error=job.get("error"),
            attempts=job.get("attempts", 0),
            created_at=job["created_at"],
            started_at=job.get("started_at"),
            completed_at=job.get("completed_at"),
            request_id=job.get("request_id"),
        )

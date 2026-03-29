# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Pydantic models for the async job system.

Jobs represent long-running operations (evaluate, compose, aging, import, etc.)
that can be executed asynchronously via the ``Prefer: respond-async`` header.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    """Lifecycle states for an async job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class JobOperation(StrEnum):
    """Operations that can be submitted as async jobs."""

    EVALUATE = "evaluate"
    COMPOSE = "compose"
    EVOLVE = "evolve"
    AGING = "aging"
    FEEDBACK_DECAY = "feedback_decay"
    IMPORT = "import"
    EXPORT = "export"
    # Phase 5.6: Data Governance lifecycle jobs
    RETENTION_CLEANUP = "retention_cleanup"
    COMPACT_AUDIT_LOG = "compact_audit_log"
    CLEANUP_OLD_JOBS = "cleanup_old_jobs"


class JobInfo(BaseModel):
    """Public representation of a job returned by the API."""

    id: str
    operation: str
    status: JobStatus
    result: dict | None = None
    error: str | None = None
    attempts: int = 0
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    request_id: str | None = None


class JobSubmitResult(BaseModel):
    """Response returned when a job is accepted for async processing."""

    job_id: str
    status: JobStatus = Field(default=JobStatus.PENDING)

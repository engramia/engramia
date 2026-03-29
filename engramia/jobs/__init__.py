# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Async job system for long-running Engramia operations.

Uses PostgreSQL ``SELECT ... FOR UPDATE SKIP LOCKED`` as a job queue
with an in-process background worker thread. No Redis/Celery required.
"""

from engramia.jobs.models import JobInfo, JobOperation, JobStatus, JobSubmitResult
from engramia.jobs.service import JobService
from engramia.jobs.worker import JobWorker

__all__ = [
    "JobInfo",
    "JobOperation",
    "JobService",
    "JobStatus",
    "JobSubmitResult",
    "JobWorker",
]

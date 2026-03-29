# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""API endpoints for async job management.

Provides job status polling, listing, and cancellation. Job submission
happens via dual-mode endpoints (evaluate, compose, etc.) when the
``Prefer: respond-async`` header is present.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from engramia.api.auth import require_auth
from engramia.api.permissions import require_permission
from engramia.api.schemas import JobCancelResponse, JobListResponse, JobResponse

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", dependencies=[Depends(require_auth)])


def _get_job_service(request: Request):
    """Retrieve the JobService from app state."""
    service = getattr(request.app.state, "job_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Async job processing is not configured.",
        )
    return service


# ---------------------------------------------------------------------------
# GET /v1/jobs
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=JobListResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("jobs:list")],
)
def list_jobs(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status", max_length=20),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List async jobs for the current tenant/project."""
    service = _get_job_service(request)
    jobs = service.list_jobs(status=status_filter, limit=limit)
    return JobListResponse(
        jobs=[
            JobResponse(
                id=j.id,
                operation=j.operation,
                status=j.status,
                result=j.result,
                error=j.error,
                attempts=j.attempts,
                created_at=j.created_at,
                started_at=j.started_at,
                completed_at=j.completed_at,
            )
            for j in jobs
        ]
    )


# ---------------------------------------------------------------------------
# GET /v1/jobs/{job_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("jobs:read")],
)
def get_job(job_id: str, request: Request):
    """Get the status and result of an async job."""
    service = _get_job_service(request)
    job = service.get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return JobResponse(
        id=job.id,
        operation=job.operation,
        status=job.status,
        result=job.result,
        error=job.error,
        attempts=job.attempts,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


# ---------------------------------------------------------------------------
# POST /v1/jobs/{job_id}/cancel
# ---------------------------------------------------------------------------


@router.post(
    "/{job_id}/cancel",
    response_model=JobCancelResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("jobs:cancel")],
)
def cancel_job(job_id: str, request: Request):
    """Cancel a pending async job."""
    service = _get_job_service(request)
    cancelled = service.cancel(job_id)
    return JobCancelResponse(cancelled=cancelled, job_id=job_id)

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""ROI Analytics API endpoints (Phase 5.7).

All endpoints are mounted under ``/v1/analytics/``.

Permissions required:
- analytics:read   — reader+  — read rollups and raw events
- analytics:rollup — editor+  — trigger rollup computation
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from engramia import Memory
from engramia._context import get_scope
from engramia.api.auth import require_auth
from engramia.api.deps import get_memory
from engramia.api.permissions import require_permission
from engramia.api.routes import _try_async
from engramia.api.schemas import (
    ROIEventOut,
    ROIEventsResponse,
    ROIRollupListResponse,
    ROIRollupRequest,
    ROIRollupResponse,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", dependencies=[Depends(require_auth)])


# ---------------------------------------------------------------------------
# POST /v1/analytics/rollup
# ---------------------------------------------------------------------------


@router.post(
    "/rollup",
    response_model=ROIRollupListResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("analytics:rollup")],
)
def trigger_rollup(
    body: ROIRollupRequest,
    request: Request,
    memory: Memory = Depends(get_memory),
) -> ROIRollupListResponse:
    """Compute and persist ROI rollup for the given window.

    Aggregates all raw events collected in the last window period and
    persists per-scope ROIRollup snapshots. Supports ``Prefer: respond-async``
    to offload to the background job worker.

    Args:
        body: Request body with ``window`` field (hourly|daily|weekly).

    Returns:
        ROIRollupListResponse with computed rollups, one per scope.
    """
    async_resp = _try_async(request, "roi_rollup", {"window": body.window})
    if async_resp is not None:
        return async_resp  # type: ignore[return-value]

    from engramia.analytics.aggregator import ROIAggregator
    from engramia.analytics.collector import ROICollector

    collector = ROICollector(memory._storage)
    aggregator = ROIAggregator(memory._storage, collector)
    try:
        rollups = aggregator.rollup(window=body.window)
    except ValueError as exc:
        _log.warning("ROI rollup request rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid rollup parameters.",
        ) from exc

    _log.info("ROI rollup triggered: window=%s scopes=%d", body.window, len(rollups))
    return ROIRollupListResponse(
        window=body.window,
        rollups=[ROIRollupResponse(**r.model_dump()) for r in rollups],
    )


# ---------------------------------------------------------------------------
# GET /v1/analytics/rollup/{window}
# ---------------------------------------------------------------------------


@router.get(
    "/rollup/{window}",
    response_model=ROIRollupResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("analytics:read")],
)
def get_rollup(
    window: str,
    memory: Memory = Depends(get_memory),
) -> ROIRollupResponse:
    """Fetch the most recently computed ROI rollup for the current scope.

    Args:
        window: Aggregation window — one of ``hourly``, ``daily``, ``weekly``.

    Returns:
        ROIRollupResponse with recall, learn, and composite roi_score.

    Raises:
        HTTPException 404: If no rollup has been computed for this window yet.
        HTTPException 422: If the window value is invalid.
    """
    _VALID_WINDOWS = {"hourly", "daily", "weekly"}
    if window not in _VALID_WINDOWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid window {window!r}. Valid values: {sorted(_VALID_WINDOWS)}",
        )

    from engramia.analytics.aggregator import ROIAggregator
    from engramia.analytics.collector import ROICollector

    scope = get_scope()
    collector = ROICollector(memory._storage)
    aggregator = ROIAggregator(memory._storage, collector)
    rollup = aggregator.get_rollup(
        window=window,
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
    )
    if rollup is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(f"No {window!r} rollup found for this scope. POST /v1/analytics/rollup to compute one."),
        )
    return ROIRollupResponse(**rollup.model_dump())


# ---------------------------------------------------------------------------
# GET /v1/analytics/events
# ---------------------------------------------------------------------------


@router.get(
    "/events",
    response_model=ROIEventsResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("analytics:read")],
)
def get_events(
    memory: Memory = Depends(get_memory),
    limit: int = Query(default=100, ge=1, le=1000),
    since: float | None = Query(default=None, description="Unix timestamp lower bound"),
) -> ROIEventsResponse:
    """Return raw ROI events for the current scope (newest first).

    Args:
        limit: Maximum number of events to return (1-1000).
        since: Optional Unix timestamp — only return events after this time.

    Returns:
        ROIEventsResponse with events and total count.
    """
    from engramia.analytics.collector import ROICollector

    scope = get_scope()
    collector = ROICollector(memory._storage)
    events = collector.load_events(
        since_ts=since,
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
    )
    # Return newest-first, capped at limit
    events = list(reversed(events))[:limit]
    return ROIEventsResponse(
        events=[ROIEventOut(**e.model_dump()) for e in events],
        total=len(events),
    )

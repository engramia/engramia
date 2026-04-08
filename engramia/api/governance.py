# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Data Governance + Privacy API endpoints (Phase 5.6).

All endpoints are mounted under ``/v1/governance/``.

Permissions required:
- governance:read  — admin+  — read retention policy, list DSRs
- governance:write — admin+  — update retention policy, reclassify patterns, create/update DSRs
- governance:admin — admin+  — trigger retention cleanup
- governance:delete — admin+ — scoped deletion (GDPR Art. 17)
- export           — admin+  — scoped export (GDPR Art. 20)
"""

import logging
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from engramia.api.audit import AuditEvent, log_event
from engramia.api.auth import require_auth
from engramia.api.deps import get_auth_context, get_memory
from engramia.api.permissions import require_permission
from engramia.api.routes import _try_async
from engramia.api.schemas import (
    ClassifyPatternRequest,
    ClassifyPatternResponse,
    DSRCreateRequest,
    DSRListResponse,
    DSRResponse,
    DSRUpdateRequest,
    RetentionApplyRequest,
    RetentionApplyResponse,
    RetentionPolicyResponse,
    ScopedDeleteResponse,
    SetRetentionRequest,
)
from engramia.types import AuthContext, DataClassification

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/governance", dependencies=[Depends(require_auth)])

_VALID_CLASSIFICATIONS = {c.value for c in DataClassification}


# ---------------------------------------------------------------------------
# GET /v1/governance/retention
# ---------------------------------------------------------------------------


@router.get(
    "/retention",
    response_model=RetentionPolicyResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("governance:read")],
)
def get_retention(
    request: Request,
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> RetentionPolicyResponse:
    """Return the effective retention policy for the current scope."""
    from engramia._context import get_scope
    from engramia.governance.retention import RetentionManager

    scope = get_scope()
    engine = _get_engine(request)
    manager = RetentionManager(engine=engine)

    # Determine source of the policy
    policy_source = "default"
    effective_days = manager._default_days

    if engine is not None:
        try:
            from sqlalchemy import text

            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT p.retention_days AS proj_days, t.retention_days AS tenant_days "
                        "FROM projects p "
                        "JOIN tenants t ON t.id = p.tenant_id "
                        "WHERE p.id = :pid AND p.tenant_id = :tid"
                    ),
                    {"pid": scope.project_id, "tid": scope.tenant_id},
                ).fetchone()
            if row is not None:
                if row.proj_days is not None:
                    effective_days = int(row.proj_days)
                    policy_source = "project"
                elif row.tenant_days is not None:
                    effective_days = int(row.tenant_days)
                    policy_source = "tenant"
        except Exception as exc:
            _log.warning("get_retention: DB lookup failed: %s", exc)

    return RetentionPolicyResponse(
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
        retention_days=effective_days,
        source=policy_source,
    )


# ---------------------------------------------------------------------------
# PUT /v1/governance/retention
# ---------------------------------------------------------------------------


@router.put(
    "/retention",
    response_model=RetentionPolicyResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("governance:write")],
)
def set_retention(
    body: SetRetentionRequest,
    request: Request,
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> RetentionPolicyResponse:
    """Set the retention policy for the current project."""
    from engramia._context import get_scope
    from engramia.governance.retention import RetentionManager

    scope = get_scope()
    engine = _get_engine(request)

    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Retention policies require DB auth mode. JSON storage does not persist policies.",
        )

    manager = RetentionManager(engine=engine)
    manager.set_project_policy(
        project_id=scope.project_id,
        tenant_id=scope.tenant_id,
        days=body.retention_days,
    )

    effective_days = manager.get_policy(scope.tenant_id, scope.project_id)
    return RetentionPolicyResponse(
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
        retention_days=effective_days,
        source="project" if body.retention_days is not None else "tenant",
    )


# ---------------------------------------------------------------------------
# POST /v1/governance/retention/apply
# ---------------------------------------------------------------------------


@router.post(
    "/retention/apply",
    response_model=RetentionApplyResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("governance:admin")],
)
def apply_retention(
    body: RetentionApplyRequest,
    request: Request,
    memory=Depends(get_memory),
    auth_ctx: AuthContext | None = Depends(get_auth_context),
):
    """Apply retention policy — delete expired patterns in the current scope.

    Supports async execution via ``Prefer: respond-async`` header.
    """
    async_resp = _try_async(request, "retention_cleanup", {"dry_run": body.dry_run})
    if async_resp is not None:
        return async_resp

    from engramia.governance.retention import RetentionManager

    engine = _get_engine(request)
    manager = RetentionManager(engine=engine)
    result = manager.apply(memory.storage, dry_run=body.dry_run)

    log_event(
        AuditEvent.RETENTION_APPLIED,
        purged_count=result.purged_count,
        dry_run=result.dry_run,
    )
    return RetentionApplyResponse(purged_count=result.purged_count, dry_run=result.dry_run)


# ---------------------------------------------------------------------------
# GET /v1/governance/export
# ---------------------------------------------------------------------------


@router.get(
    "/export",
    dependencies=[require_permission("export")],
)
def export_scope(
    request: Request,
    memory=Depends(get_memory),
    auth_ctx: AuthContext | None = Depends(get_auth_context),
    classification: str | None = Query(
        default=None,
        description="Comma-separated classification filter (e.g. public,internal)",
        max_length=100,
    ),
):
    """Stream all patterns for the current scope as NDJSON (GDPR Art. 20).

    Each line is a JSON object with keys: version, key, data, classification, redacted.
    """
    import json

    from engramia.governance.export import DataExporter

    cls_filter: list[str] | None = None
    if classification:
        cls_filter = [c.strip() for c in classification.split(",") if c.strip()]
        for cls in cls_filter:
            if cls not in _VALID_CLASSIFICATIONS:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid classification '{cls}'. Valid values: {sorted(_VALID_CLASSIFICATIONS)}",
                )

    engine = _get_engine(request)
    exporter = DataExporter()

    def _stream():
        for record in exporter.stream(memory.storage, classification_filter=cls_filter, engine=engine):
            yield json.dumps(record, default=str) + "\n"

    log_event(AuditEvent.SCOPE_EXPORTED, classification_filter=cls_filter)

    return StreamingResponse(
        _stream(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=engramia_export.ndjson"},
    )


# ---------------------------------------------------------------------------
# PUT /v1/governance/patterns/{pattern_key:path}/classify
# ---------------------------------------------------------------------------


@router.put(
    "/patterns/{pattern_key:path}/classify",
    response_model=ClassifyPatternResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("governance:write")],
)
def classify_pattern(
    pattern_key: str,
    body: ClassifyPatternRequest,
    auth_ctx: AuthContext | None = Depends(get_auth_context),
    memory=Depends(get_memory),
) -> ClassifyPatternResponse:
    """Update the classification label of a stored pattern."""
    if body.classification not in _VALID_CLASSIFICATIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid classification. Valid values: {sorted(_VALID_CLASSIFICATIONS)}",
        )

    # Ensure pattern exists
    data = memory.storage.load(pattern_key)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pattern not found.")

    memory.storage.save_pattern_meta(pattern_key, classification=body.classification)
    return ClassifyPatternResponse(pattern_key=pattern_key, classification=body.classification)


# ---------------------------------------------------------------------------
# DELETE /v1/governance/projects/{project_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/projects/{project_id}",
    response_model=ScopedDeleteResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("governance:delete")],
)
def delete_project(
    project_id: str,
    request: Request,
    memory=Depends(get_memory),
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> ScopedDeleteResponse:
    """Delete ALL data for a project (GDPR Art. 17 right to erasure).

    This is irreversible. Patterns, embeddings, and jobs are permanently
    deleted. API keys are revoked. Audit logs are scrubbed.

    Authorization:
    - admin: may only delete their own project (project_id must match scope).
    - owner: may delete any project within their tenant.
    """
    from engramia._context import get_scope
    from engramia.governance.deletion import ScopedDeletion

    scope = get_scope()

    # Admins are scoped to their own project — only owners may perform
    # cross-project deletion within the tenant.
    if auth_ctx is not None and auth_ctx.role != "owner" and project_id != scope.project_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Role '{auth_ctx.role}' may only delete its own project. "
                "Cross-project deletion requires the 'owner' role."
            ),
        )

    engine = _get_engine(request)
    deletion = ScopedDeletion(engine=engine)

    result = deletion.delete_project(
        memory.storage,
        tenant_id=scope.tenant_id,
        project_id=project_id,
    )

    ip = request.client.host if request.client else "unknown"
    log_event(
        AuditEvent.SCOPE_DELETED,
        tenant_id=scope.tenant_id,
        project_id=project_id,
        patterns_deleted=result.patterns_deleted,
        ip=ip,
    )

    return ScopedDeleteResponse(
        tenant_id=result.tenant_id,
        project_id=result.project_id,
        patterns_deleted=result.patterns_deleted,
        jobs_deleted=result.jobs_deleted,
        keys_revoked=result.keys_revoked,
        projects_deleted=result.projects_deleted,
    )


# ---------------------------------------------------------------------------
# DELETE /v1/governance/tenants/{tenant_id}  (owner only)
# ---------------------------------------------------------------------------


@router.delete(
    "/tenants/{tenant_id}",
    response_model=ScopedDeleteResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("*")],  # owner wildcard only
)
def delete_tenant(
    tenant_id: str,
    request: Request,
    memory=Depends(get_memory),
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> ScopedDeleteResponse:
    """Delete ALL data for an entire tenant (owner-only, GDPR Art. 17).

    Wipes all projects, patterns, embeddings, jobs. Irreversible.
    """
    from engramia.governance.deletion import ScopedDeletion

    # Extra check: caller must be owner of this specific tenant
    if auth_ctx is not None and auth_ctx.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own tenant.",
        )

    engine = _get_engine(request)
    deletion = ScopedDeletion(engine=engine)

    result = deletion.delete_tenant(memory.storage, tenant_id=tenant_id)

    ip = request.client.host if request.client else "unknown"
    log_event(
        AuditEvent.SCOPE_DELETED,
        tenant_id=tenant_id,
        project_id="*",
        patterns_deleted=result.patterns_deleted,
        ip=ip,
    )

    return ScopedDeleteResponse(
        tenant_id=result.tenant_id,
        project_id=result.project_id,
        patterns_deleted=result.patterns_deleted,
        jobs_deleted=result.jobs_deleted,
        keys_revoked=result.keys_revoked,
        projects_deleted=result.projects_deleted,
    )


# ---------------------------------------------------------------------------
# POST /v1/governance/dsr  — create a Data Subject Request
# ---------------------------------------------------------------------------


@router.post(
    "/dsr",
    response_model=DSRResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_permission("governance:write")],
)
def create_dsr(
    body: DSRCreateRequest,
    request: Request,
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> DSRResponse:
    """Create a new Data Subject Request (GDPR Art. 15-20).

    The SLA deadline (``due_at``) is calculated as ``now + ENGRAMIA_DSR_SLA_DAYS``
    (default 30 days). A WARNING is logged if the deadline is within 7 days.
    """
    from engramia._context import get_scope
    from engramia.governance.dsr import DSRTracker

    scope = get_scope()
    engine = _get_engine(request)
    tracker = DSRTracker(engine=engine)

    from engramia.governance.dsr import DSRType

    dsr = tracker.create(
        tenant_id=scope.tenant_id,
        request_type=cast(DSRType, body.request_type),
        subject_email=body.subject_email,
        handler_notes=body.handler_notes,
    )
    return _dsr_to_response(dsr)


# ---------------------------------------------------------------------------
# GET /v1/governance/dsr  — list Data Subject Requests for current tenant
# ---------------------------------------------------------------------------


@router.get(
    "/dsr",
    response_model=DSRListResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("governance:read")],
)
def list_dsrs(
    request: Request,
    auth_ctx: AuthContext | None = Depends(get_auth_context),
    filter_status: str | None = Query(
        default=None,
        alias="status",
        description="Filter by status: pending | in_progress | completed | rejected",
        pattern="^(pending|in_progress|completed|rejected)$",
    ),
    overdue_only: bool = Query(default=False, description="Return only past-deadline open requests."),
    limit: int = Query(default=100, ge=1, le=500),
) -> DSRListResponse:
    """List Data Subject Requests for the current tenant.

    Near-deadline requests (within 7 days of ``due_at``) emit WARNING log
    messages so alert rules can pick them up.
    """
    from engramia._context import get_scope
    from engramia.governance.dsr import DSRTracker

    scope = get_scope()
    engine = _get_engine(request)
    tracker = DSRTracker(engine=engine)

    from engramia.governance.dsr import DSRStatus

    requests = tracker.list_requests(
        tenant_id=scope.tenant_id,
        status=cast(DSRStatus, filter_status) if filter_status else None,
        overdue_only=overdue_only,
        limit=limit,
    )
    pending_counts = tracker.pending_count(scope.tenant_id)

    return DSRListResponse(
        requests=[_dsr_to_response(r) for r in requests],
        total=len(requests),
        pending_counts=pending_counts,
    )


# ---------------------------------------------------------------------------
# PATCH /v1/governance/dsr/{dsr_id}  — update DSR status
# ---------------------------------------------------------------------------


@router.patch(
    "/dsr/{dsr_id}",
    response_model=DSRResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("governance:write")],
)
def update_dsr(
    dsr_id: str,
    body: DSRUpdateRequest,
    request: Request,
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> DSRResponse:
    """Update the status (and optionally append handler notes) of a DSR."""
    from engramia._context import get_scope
    from engramia.governance.dsr import DSRTracker

    scope = get_scope()
    engine = _get_engine(request)
    tracker = DSRTracker(engine=engine)

    # Verify the DSR belongs to the caller's tenant
    existing = tracker.get(dsr_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DSR not found.")
    if existing.tenant_id != scope.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You may only modify DSRs belonging to your tenant.",
        )

    from engramia.governance.dsr import DSRStatus

    updated = tracker.update_status(
        dsr_id=dsr_id,
        status=cast(DSRStatus, body.status),
        handler_notes=body.handler_notes,
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DSR not found.")
    return _dsr_to_response(updated)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_engine(request: Request):
    """Return the auth DB engine from app state, or None if not configured."""
    return getattr(request.app.state, "auth_engine", None)


def _dsr_to_response(dsr) -> DSRResponse:
    """Convert a :class:`DSRRequest` domain object to the API response schema."""
    return DSRResponse(
        id=dsr.id,
        tenant_id=dsr.tenant_id,
        request_type=dsr.request_type,
        subject_email=dsr.subject_email,
        status=dsr.status,
        created_at=dsr.created_at,
        due_at=dsr.due_at,
        updated_at=dsr.updated_at,
        completed_at=dsr.completed_at,
        handler_notes=dsr.handler_notes,
        overdue=dsr.overdue,
    )

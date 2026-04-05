# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Engramia API endpoint definitions.

All endpoints use sync FastAPI handlers (FastAPI runs them in a threadpool),
which is correct for the CPU-light, I/O-bound Engramia operations.
Async is deferred until a concrete bottleneck is identified.

Each endpoint carries a ``require_permission`` dependency that enforces RBAC
when the request was authenticated via DB auth mode. In env-var auth mode the
check is a no-op for backward compatibility.

Pattern-count quota is enforced on write operations (``/learn``, ``/import``)
by checking the storage backend's scoped count against the per-key limit.
"""

import logging
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from engramia import Memory
from engramia.api.audit import AuditEvent, log_event
from engramia.api.auth import require_auth
from engramia.api.deps import get_auth_context, get_memory
from engramia.api.permissions import PERMISSIONS, require_permission
from engramia.api.schemas import (
    AgingResponse,
    AnalyzeFailuresRequest,
    AnalyzeFailuresResponse,
    ComposeRequest,
    ComposeResponse,
    DeepHealthCheckResult,
    DeepHealthResponse,
    DeletePatternResponse,
    EvalScoreOut,
    EvaluateRequest,
    EvaluateResponse,
    EvolveRequest,
    EvolveResponse,
    ExportResponse,
    FailureClusterOut,
    FeedbackDecayResponse,
    FeedbackResponse,
    HealthResponse,
    ImportRequest,
    ImportResponse,
    LearnRequest,
    LearnResponse,
    MatchOut,
    MetricsResponse,
    PatternOut,
    RecallRequest,
    RecallResponse,
    RegisterSkillsRequest,
    RegisterSkillsResponse,
    SkillsSearchRequest,
    StageOut,
)
from engramia.exceptions import ProviderError
from engramia.types import AuthContext
from engramia.versioning import API_VERSION, APP_VERSION, BUILD_TIME, GIT_COMMIT

_STARTUP_TIME = time.monotonic()

_log = logging.getLogger(__name__)

# Hard cap on LLM-generated text in API responses. Prevents unbounded response
# bodies when a model returns an unexpectedly verbose output. Configurable via
# env var for deployments that need longer prompts.
_MAX_LLM_RESPONSE = int(os.environ.get("ENGRAMIA_MAX_LLM_RESPONSE", "20000"))


def _trunc(s: str) -> str:
    """Truncate an LLM-generated string to _MAX_LLM_RESPONSE characters."""
    if len(s) <= _MAX_LLM_RESPONSE:
        return s
    return s[:_MAX_LLM_RESPONSE] + "…[truncated]"


# ---------------------------------------------------------------------------
# Async job helper (Phase 5.4)
# ---------------------------------------------------------------------------


def _try_async(request: Request, operation: str, params: dict) -> JSONResponse | None:
    """If ``Prefer: respond-async`` header is set and job service is available,
    submit an async job and return a 202 response. Otherwise return None.
    """
    if request.headers.get("Prefer") != "respond-async":
        return None

    service = getattr(request.app.state, "job_service", None)
    if service is None:
        return None

    auth_ctx = getattr(request.state, "auth_context", None)
    key_id = auth_ctx.key_id if auth_ctx else None

    result = service.submit(operation=operation, params=params, key_id=key_id)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"job_id": result.job_id, "status": result.status},
        headers={"Location": f"/v1/jobs/{result.job_id}"},
    )

router = APIRouter(dependencies=[Depends(require_auth)])


# ---------------------------------------------------------------------------
# Internal quota helpers
# ---------------------------------------------------------------------------


def _check_quota(memory: Memory, auth_ctx: AuthContext | None, request: Request | None = None) -> None:
    """Raise HTTP 429 if the caller has exceeded their pattern quota.

    Delegates to BillingService when available (DB auth + billing configured).
    Falls back to the legacy max_patterns field on AuthContext for backward
    compatibility with deployments that have not run migration 008.
    """
    current = memory._storage.count_patterns("patterns/")

    # Billing-aware path
    billing_svc = getattr(request.app.state, "billing_service", None) if request else None
    if billing_svc is not None and auth_ctx is not None:
        billing_svc.check_patterns(auth_ctx.tenant_id, current)
        return

    # Legacy fallback: max_patterns on AuthContext
    if auth_ctx is None or auth_ctx.max_patterns is None:
        return
    if current >= auth_ctx.max_patterns:
        log_event(
            AuditEvent.QUOTA_EXCEEDED,
            tenant_id=auth_ctx.tenant_id,
            project_id=auth_ctx.project_id,
            current=current,
            limit=auth_ctx.max_patterns,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "quota_exceeded",
                "current": current,
                "limit": auth_ctx.max_patterns,
                "message": "Pattern quota reached. Delete old patterns or upgrade your plan.",
            },
        )


# ---------------------------------------------------------------------------
# POST /learn
# ---------------------------------------------------------------------------


@router.post(
    "/learn",
    response_model=LearnResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("learn")],
)
def learn(
    body: LearnRequest,
    request: Request,
    memory: Memory = Depends(get_memory),
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> LearnResponse:
    """Record a successful agent run and store it as a reusable pattern."""
    _check_quota(memory, auth_ctx, request)
    result = memory.learn(
        task=body.task,
        code=body.code,
        eval_score=body.eval_score,
        output=body.output,
        run_id=body.run_id,
        classification=body.classification,
        source=body.source,
        author=auth_ctx.key_id if auth_ctx else None,
    )
    return LearnResponse(stored=result.stored, pattern_count=result.pattern_count)


# ---------------------------------------------------------------------------
# POST /recall
# ---------------------------------------------------------------------------


@router.post(
    "/recall",
    response_model=RecallResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("recall")],
)
def recall(body: RecallRequest, memory: Memory = Depends(get_memory)) -> RecallResponse:
    """Find stored patterns most relevant to the given task.

    Supports offset-based pagination via ``offset`` and filters by
    ``classification``, ``source``, and ``min_score``.
    The matcher fetches extra candidates so that post-filtering does not
    reduce the result set below the requested ``limit``.
    """
    # Fetch extra candidates to absorb post-filter losses and satisfy pagination.
    fetch_limit = (body.offset + body.limit) * 4
    matches = memory.recall(
        task=body.task,
        limit=fetch_limit,
        deduplicate=body.deduplicate,
        eval_weighted=body.eval_weighted,
    )

    # Post-filter by classification, source, min_score.
    if body.classification or body.source or body.min_score is not None:
        filtered = []
        for m in matches:
            design = m.pattern.design or {}
            if body.classification and design.get("classification") != body.classification:
                continue
            if body.source and design.get("source") != body.source:
                continue
            if body.min_score is not None and m.pattern.success_score < body.min_score:
                continue
            filtered.append(m)
        matches = filtered

    # Apply pagination offset.
    page = matches[body.offset : body.offset + body.limit]
    has_more = len(matches) > body.offset + body.limit
    next_offset = body.offset + body.limit if has_more else None

    out: list[MatchOut] = []
    for m in page:
        code = m.pattern.design.get("code") if m.pattern.design else None
        out.append(
            MatchOut(
                similarity=m.similarity,
                reuse_tier=m.reuse_tier,
                pattern_key=m.pattern_key,
                pattern=PatternOut(
                    task=m.pattern.task,
                    code=code,
                    success_score=m.pattern.success_score,
                    reuse_count=m.pattern.reuse_count,
                ),
            )
        )
    return RecallResponse(matches=out, has_more=has_more, next_offset=next_offset)


# ---------------------------------------------------------------------------
# POST /compose
# ---------------------------------------------------------------------------


@router.post(
    "/compose",
    response_model=ComposeResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("compose")],
)
def compose(body: ComposeRequest, request: Request, memory: Memory = Depends(get_memory)):
    """Decompose a task into a multi-stage pipeline from stored patterns."""
    async_resp = _try_async(request, "compose", body.model_dump())
    if async_resp is not None:
        return async_resp
    try:
        pipeline = memory.compose(task=body.task)
    except ProviderError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="LLM provider not configured. compose() requires an LLM.",
        ) from None

    stages_out = [
        StageOut(
            name=s.name,
            task=s.task,
            reads=s.reads,
            writes=s.writes,
            reuse_tier=s.reuse_tier,
            similarity=s.similarity,
            code=s.design.get("code") if s.design else None,
        )
        for s in pipeline.stages
    ]
    return ComposeResponse(
        task=pipeline.task,
        stages=stages_out,
        valid=pipeline.valid,
        contract_errors=pipeline.contract_errors,
    )


# ---------------------------------------------------------------------------
# POST /evaluate
# ---------------------------------------------------------------------------


@router.post(
    "/evaluate",
    response_model=EvaluateResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("evaluate")],
)
def evaluate(
    body: EvaluateRequest,
    request: Request,
    memory: Memory = Depends(get_memory),
    auth_ctx: AuthContext | None = Depends(get_auth_context),
):
    """Run multi-evaluator scoring on agent code."""
    # Eval-run quota enforcement (billing-aware; no-op in dev/JSON mode)
    billing_svc = getattr(request.app.state, "billing_service", None)
    tenant_id = auth_ctx.tenant_id if auth_ctx else "default"
    if billing_svc is not None:
        billing_svc.check_eval_runs(tenant_id)

    async_resp = _try_async(request, "evaluate", body.model_dump())
    if async_resp is not None:
        return async_resp

    try:
        result = memory.evaluate(
            task=body.task,
            code=body.code,
            output=body.output,
            num_evals=body.num_evals,
        )
    except ProviderError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="LLM provider not configured. evaluate() requires an LLM.",
        ) from None

    # Increment eval run counter after successful evaluation (fire-and-log)
    if billing_svc is not None:
        try:
            billing_svc.increment_eval_runs(tenant_id)
        except Exception:
            _log.warning("Failed to increment eval_runs counter for tenant=%s", tenant_id, exc_info=True)

    scores_out = [
        EvalScoreOut(
            task_alignment=s.task_alignment,
            code_quality=s.code_quality,
            workspace_usage=s.workspace_usage,
            robustness=s.robustness,
            overall=s.overall,
            feedback=_trunc(s.feedback),
        )
        for s in result.scores
    ]
    return EvaluateResponse(
        median_score=result.median_score,
        variance=result.variance,
        high_variance=result.high_variance,
        feedback=_trunc(result.feedback),
        adversarial_detected=result.adversarial_detected,
        scores=scores_out,
    )


# ---------------------------------------------------------------------------
# GET /feedback
# ---------------------------------------------------------------------------


@router.get(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("feedback:read")],
)
def get_feedback(
    memory: Memory = Depends(get_memory),
    task_type: str | None = Query(default=None, max_length=200, description="Filter by task type keyword."),
    limit: int = Query(default=5, ge=1, le=20),
    offset: int = Query(default=0, ge=0, le=10_000, description="Number of results to skip (for pagination)."),
) -> FeedbackResponse:
    """Return top recurring quality issues for prompt injection."""
    # Fetch one extra item to detect has_more without a separate count query.
    feedback = memory.get_feedback(task_type=task_type, limit=limit + 1, offset=offset)
    has_more = len(feedback) > limit
    if has_more:
        feedback = feedback[:limit]
    next_offset = offset + limit if has_more else None
    return FeedbackResponse(feedback=feedback, has_more=has_more, next_offset=next_offset)


# ---------------------------------------------------------------------------
# GET /metrics
# ---------------------------------------------------------------------------


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("metrics")],
)
def get_metrics(memory: Memory = Depends(get_memory)) -> MetricsResponse:
    """Return aggregate run statistics."""
    m = memory.metrics
    reuse_rate = m.pipeline_reuse / m.runs if m.runs > 0 else 0.0
    return MetricsResponse(
        runs=m.runs,
        success_rate=m.success_rate,
        avg_eval_score=m.avg_eval_score,
        pattern_count=m.pattern_count,
        reuse_rate=reuse_rate,
    )


# ---------------------------------------------------------------------------
# DELETE /patterns/{pattern_key:path}
# ---------------------------------------------------------------------------


def _check_delete_permission(request: Request) -> None:
    """Allow patterns:delete (admin+) or patterns:delete_own (editor, own patterns)."""
    ctx = getattr(request.state, "auth_context", None)
    if ctx is None:
        return  # env-var or dev mode — no RBAC
    role_perms = PERMISSIONS.get(ctx.role, frozenset())
    if "*" in role_perms or "patterns:delete" in role_perms:
        return
    if "patterns:delete_own" in role_perms:
        return  # ownership check done in route handler
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Role '{ctx.role}' does not have permission 'patterns:delete'.",
    )


@router.delete(
    "/patterns/{pattern_key:path}",
    response_model=DeletePatternResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(_check_delete_permission)],
)
def delete_pattern(
    pattern_key: str,
    request: Request,
    memory: Memory = Depends(get_memory),
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> DeletePatternResponse:
    """Permanently delete a stored pattern by its key.

    Admin+ can delete any pattern. Editors can delete only patterns they created
    (matched by ``_author_key_id`` stored in pattern data).
    """
    # Ownership check for editors with patterns:delete_own
    if auth_ctx is not None:
        role_perms = PERMISSIONS.get(auth_ctx.role, frozenset())
        has_full_delete = "*" in role_perms or "patterns:delete" in role_perms
        if not has_full_delete and "patterns:delete_own" in role_perms:
            # Ensure scope is set for the sync handler thread (contextvar may
            # not propagate from the async auth dependency).
            from engramia._context import set_scope
            set_scope(auth_ctx.scope)
            data = memory.storage.load(pattern_key)
            if data is not None and data.get("_author_key_id") != auth_ctx.key_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Editors can only delete patterns they created.",
                )

    try:
        deleted = memory.delete_pattern(pattern_key)
    except Exception as exc:
        _log.warning("delete_pattern failed for key %r: %s", pattern_key, exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid pattern key.",
        ) from None
    if deleted:
        ip = request.client.host if request.client else "unknown"
        log_event(
            AuditEvent.PATTERN_DELETED,
            pattern_key=pattern_key,
            ip=ip,
            tenant_id=auth_ctx.tenant_id if auth_ctx else None,
            key_id=auth_ctx.key_id if auth_ctx else None,
        )
    return DeletePatternResponse(deleted=deleted, pattern_key=pattern_key)


# ---------------------------------------------------------------------------
# POST /aging
# ---------------------------------------------------------------------------


@router.post(
    "/aging",
    response_model=AgingResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("aging")],
)
def run_aging(request: Request, memory: Memory = Depends(get_memory)):
    """Apply time-based decay to all patterns. Prune those below threshold."""
    async_resp = _try_async(request, "aging", {})
    if async_resp is not None:
        return async_resp
    pruned = memory.run_aging()
    return AgingResponse(pruned=pruned)


# ---------------------------------------------------------------------------
# POST /feedback/decay
# ---------------------------------------------------------------------------


@router.post(
    "/feedback/decay",
    response_model=FeedbackDecayResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("feedback:decay")],
)
def run_feedback_decay(request: Request, memory: Memory = Depends(get_memory)):
    """Apply time-based decay to feedback patterns. Prune those below threshold."""
    async_resp = _try_async(request, "feedback_decay", {})
    if async_resp is not None:
        return async_resp
    pruned = memory.run_feedback_decay()
    return FeedbackDecayResponse(pruned=pruned)


# ---------------------------------------------------------------------------
# GET /version  (no auth — public meta endpoint)
# ---------------------------------------------------------------------------

# Separate router so /version is reachable without authentication.
_meta_router = APIRouter()
meta_router = _meta_router  # re-export for app.py


@_meta_router.get("/version", tags=["meta"], include_in_schema=True)
def get_version() -> dict:
    """Return runtime build metadata.

    No authentication required. Intended for post-deploy smoke tests,
    support tooling, and ops dashboards.
    """
    return {
        "app_version": APP_VERSION,
        "api_version": API_VERSION,
        "git_commit": GIT_COMMIT,
        "build_time": BUILD_TIME,
    }


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("health")],
)
def health(memory: Memory = Depends(get_memory)) -> HealthResponse:
    """Health check — returns storage backend type and pattern count."""
    return HealthResponse(
        status="ok",
        storage=memory.storage_type,
        pattern_count=memory.metrics.pattern_count,
    )


# ---------------------------------------------------------------------------
# GET /health/deep  (Phase 5.5)
# ---------------------------------------------------------------------------


@router.get(
    "/health/deep",
    response_model=DeepHealthResponse,
    dependencies=[require_permission("health")],
)
def health_deep(request: Request, memory: Memory = Depends(get_memory)):
    """Deep health check — probes storage, LLM, and embedding connectivity.

    Returns HTTP 200 with status "ok" or "degraded", and HTTP 503 when
    all non-optional backends are unavailable.
    """
    from engramia import __version__
    from engramia.telemetry.health import (
        aggregate_status,
        check_embedding,
        check_llm,
        check_storage,
    )

    checks = {
        "storage": check_storage(memory.storage),
        "llm": check_llm(memory.llm),
        "embedding": check_embedding(memory.embeddings),
    }

    overall = aggregate_status(checks)
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE if overall == "error" else status.HTTP_200_OK

    body = DeepHealthResponse(
        status=overall,
        version=__version__,
        uptime_seconds=round(time.monotonic() - _STARTUP_TIME, 1),
        checks={k: DeepHealthCheckResult(**v) for k, v in checks.items()},
    )
    return JSONResponse(content=body.model_dump(), status_code=http_status)


# ---------------------------------------------------------------------------
# POST /evolve  (Phase 3)
# ---------------------------------------------------------------------------


@router.post(
    "/evolve",
    response_model=EvolveResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("evolve")],
)
def evolve_prompt(body: EvolveRequest, request: Request, memory: Memory = Depends(get_memory)):
    """Generate an improved prompt based on recurring feedback patterns."""
    async_resp = _try_async(request, "evolve", body.model_dump())
    if async_resp is not None:
        return async_resp
    try:
        result = memory.evolve_prompt(
            role=body.role,
            current_prompt=body.current_prompt,
            num_issues=body.num_issues,
        )
    except ProviderError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="LLM provider not configured. evolve_prompt() requires an LLM.",
        ) from None
    return EvolveResponse(
        improved_prompt=_trunc(result.improved_prompt),
        changes=[_trunc(c) for c in result.changes],
        issues_addressed=[_trunc(i) for i in result.issues_addressed],
        accepted=result.accepted,
        reason=_trunc(result.reason),
    )


# ---------------------------------------------------------------------------
# POST /analyze-failures  (Phase 3)
# ---------------------------------------------------------------------------


@router.post(
    "/analyze-failures",
    response_model=AnalyzeFailuresResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("analyze_failures")],
)
def analyze_failures(body: AnalyzeFailuresRequest, memory: Memory = Depends(get_memory)) -> AnalyzeFailuresResponse:
    """Cluster failure patterns to identify systemic issues."""
    clusters = memory.analyze_failures(min_count=body.min_count)
    out = [
        FailureClusterOut(
            representative=c.representative,
            members=c.members,
            total_count=c.total_count,
            avg_score=c.avg_score,
        )
        for c in clusters
    ]
    return AnalyzeFailuresResponse(clusters=out)


# ---------------------------------------------------------------------------
# POST /skills/register  (Phase 3)
# ---------------------------------------------------------------------------


@router.post(
    "/skills/register",
    response_model=RegisterSkillsResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("skills:register")],
)
def register_skills(body: RegisterSkillsRequest, memory: Memory = Depends(get_memory)) -> RegisterSkillsResponse:
    """Associate skill tags with a stored pattern."""
    memory.register_skills(body.pattern_key, body.skills)
    registered = len(memory._skill_registry.get_skills(body.pattern_key))
    return RegisterSkillsResponse(registered=registered)


# ---------------------------------------------------------------------------
# POST /skills/search  (Phase 3)
# ---------------------------------------------------------------------------


@router.post(
    "/skills/search",
    response_model=RecallResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("skills:search")],
)
def skills_search(body: SkillsSearchRequest, memory: Memory = Depends(get_memory)) -> RecallResponse:
    """Find patterns that have the required skills."""
    matches = memory.find_by_skills(required=body.required, match_all=body.match_all)
    out: list[MatchOut] = []
    for m in matches:
        code = m.pattern.design.get("code") if m.pattern.design else None
        out.append(
            MatchOut(
                similarity=m.similarity,
                reuse_tier=m.reuse_tier,
                pattern_key=m.pattern_key,
                pattern=PatternOut(
                    task=m.pattern.task,
                    code=code,
                    success_score=m.pattern.success_score,
                    reuse_count=m.pattern.reuse_count,
                ),
            )
        )
    return RecallResponse(matches=out)


# ---------------------------------------------------------------------------
# POST /import  (bulk restore)
# ---------------------------------------------------------------------------


@router.post(
    "/import",
    response_model=ImportResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("import")],
)
def import_patterns(
    body: ImportRequest,
    request: Request,
    memory: Memory = Depends(get_memory),
    auth_ctx: AuthContext | None = Depends(get_auth_context),
):
    """Bulk-import patterns from a previous export().

    Accepts records in the format produced by GET /export ({"version": 1, "key": ..., "data": ...}).
    Skips malformed records and keys that lack the patterns/ prefix.
    Quota is checked against the number of patterns that would be added.
    """
    async_resp = _try_async(
        request,
        "import",
        {"records": [r.model_dump() for r in body.records], "overwrite": body.overwrite},
    )
    if async_resp is not None:
        return async_resp
    _check_quota(memory, auth_ctx, request)
    raw_records = [r.model_dump() for r in body.records]
    imported = memory.import_data(raw_records, overwrite=body.overwrite)
    ip = request.client.host if request.client else "unknown"
    log_event(
        AuditEvent.BULK_IMPORT,
        ip=ip,
        total=len(body.records),
        imported=imported,
        overwrite=body.overwrite,
        tenant_id=auth_ctx.tenant_id if auth_ctx else None,
        key_id=auth_ctx.key_id if auth_ctx else None,
    )
    return ImportResponse(imported=imported, total=len(body.records))


# ---------------------------------------------------------------------------
# GET /export  (symmetric pair to POST /import)
# ---------------------------------------------------------------------------


@router.get(
    "/export",
    response_model=ExportResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("export")],
)
def export_patterns(
    request: Request,
    memory: Memory = Depends(get_memory),
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> ExportResponse:
    """Export all stored patterns in the current scope.

    Returns records in the same format accepted by POST /v1/import, so the
    full backup/restore cycle is possible without the SDK::

        GET /v1/export  →  POST /v1/import

    The operation is audit-logged with the caller's key_id and tenant_id.
    For large stores, prefer POST /v1/governance/export (streaming NDJSON).
    """
    raw_records = memory.export()
    ip = request.client.host if request.client else "unknown"
    log_event(
        AuditEvent.DATA_EXPORTED,
        ip=ip,
        count=len(raw_records),
        tenant_id=auth_ctx.tenant_id if auth_ctx else None,
        key_id=auth_ctx.key_id if auth_ctx else None,
    )
    from engramia.api.schemas import ImportRecord
    records = [ImportRecord(version=r["version"], key=r["key"], data=r["data"]) for r in raw_records]
    return ExportResponse(records=records, count=len(records))

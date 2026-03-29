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
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from engramia import Memory
from engramia.api.audit import AuditEvent, log_event
from engramia.api.auth import require_auth
from engramia.api.deps import get_auth_context, get_memory
from engramia.api.permissions import require_permission
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

_STARTUP_TIME = time.monotonic()

_log = logging.getLogger(__name__)


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
# Internal quota helper
# ---------------------------------------------------------------------------


def _check_quota(memory: Memory, auth_ctx: AuthContext | None) -> None:
    """Raise HTTP 429 if the caller has exceeded their pattern quota.

    Only enforced in DB auth mode where an AuthContext with a max_patterns
    limit is present. No-op in env-var and dev auth modes.
    """
    if auth_ctx is None or auth_ctx.max_patterns is None:
        return
    current = memory._storage.count_patterns("patterns/")
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
    memory: Memory = Depends(get_memory),
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> LearnResponse:
    """Record a successful agent run and store it as a reusable pattern."""
    _check_quota(memory, auth_ctx)
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
    """Find stored patterns most relevant to the given task."""
    matches = memory.recall(
        task=body.task,
        limit=body.limit,
        deduplicate=body.deduplicate,
        eval_weighted=body.eval_weighted,
    )
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
def evaluate(body: EvaluateRequest, request: Request, memory: Memory = Depends(get_memory)):
    """Run multi-evaluator scoring on agent code."""
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

    scores_out = [
        EvalScoreOut(
            task_alignment=s.task_alignment,
            code_quality=s.code_quality,
            workspace_usage=s.workspace_usage,
            robustness=s.robustness,
            overall=s.overall,
            feedback=s.feedback,
        )
        for s in result.scores
    ]
    return EvaluateResponse(
        median_score=result.median_score,
        variance=result.variance,
        high_variance=result.high_variance,
        feedback=result.feedback,
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
) -> FeedbackResponse:
    """Return top recurring quality issues for prompt injection."""
    feedback = memory.get_feedback(task_type=task_type, limit=limit)
    return FeedbackResponse(feedback=feedback)


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


@router.delete(
    "/patterns/{pattern_key:path}",
    response_model=DeletePatternResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[require_permission("patterns:delete")],
)
def delete_pattern(
    pattern_key: str,
    request: Request,
    memory: Memory = Depends(get_memory),
) -> DeletePatternResponse:
    """Permanently delete a stored pattern by its key."""
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
        log_event(AuditEvent.PATTERN_DELETED, pattern_key=pattern_key, ip=ip)
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
        improved_prompt=result.improved_prompt,
        changes=result.changes,
        issues_addressed=result.issues_addressed,
        accepted=result.accepted,
        reason=result.reason,
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
    _check_quota(memory, auth_ctx)
    raw_records = [r.model_dump() for r in body.records]
    imported = memory.import_data(raw_records, overwrite=body.overwrite)
    ip = request.client.host if request.client else "unknown"
    log_event(
        AuditEvent.BULK_IMPORT,
        ip=ip,
        total=len(body.records),
        imported=imported,
        overwrite=body.overwrite,
    )
    return ImportResponse(imported=imported, total=len(body.records))

"""Remanence API endpoint definitions.

All endpoints use sync FastAPI handlers (FastAPI runs them in a threadpool),
which is correct for the CPU-light, I/O-bound Brain operations.
Async is deferred until a concrete bottleneck is identified.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from remanence import Memory
from remanence.api.audit import AuditEvent, log_event
from remanence.api.auth import require_auth
from remanence.api.deps import get_brain
from remanence.api.schemas import (
    AgingResponse,
    AnalyzeFailuresRequest,
    AnalyzeFailuresResponse,
    ComposeRequest,
    ComposeResponse,
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
from remanence.exceptions import ProviderError

_log = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_auth)])


# ---------------------------------------------------------------------------
# POST /learn
# ---------------------------------------------------------------------------


@router.post("/learn", response_model=LearnResponse, status_code=status.HTTP_200_OK)
def learn(body: LearnRequest, brain: Memory = Depends(get_brain)) -> LearnResponse:
    """Record a successful agent run and store it as a reusable pattern."""
    result = brain.learn(
        task=body.task,
        code=body.code,
        eval_score=body.eval_score,
        output=body.output,
    )
    return LearnResponse(stored=result.stored, pattern_count=result.pattern_count)


# ---------------------------------------------------------------------------
# POST /recall
# ---------------------------------------------------------------------------


@router.post("/recall", response_model=RecallResponse, status_code=status.HTTP_200_OK)
def recall(body: RecallRequest, brain: Memory = Depends(get_brain)) -> RecallResponse:
    """Find stored patterns most relevant to the given task."""
    matches = brain.recall(
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


@router.post("/compose", response_model=ComposeResponse, status_code=status.HTTP_200_OK)
def compose(body: ComposeRequest, brain: Memory = Depends(get_brain)) -> ComposeResponse:
    """Decompose a task into a multi-stage pipeline from stored patterns."""
    try:
        pipeline = brain.compose(task=body.task)
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


@router.post("/evaluate", response_model=EvaluateResponse, status_code=status.HTTP_200_OK)
def evaluate(body: EvaluateRequest, brain: Memory = Depends(get_brain)) -> EvaluateResponse:
    """Run multi-evaluator scoring on agent code."""
    try:
        result = brain.evaluate(
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


@router.get("/feedback", response_model=FeedbackResponse, status_code=status.HTTP_200_OK)
def get_feedback(
    brain: Memory = Depends(get_brain),
    task_type: str | None = Query(default=None, max_length=200, description="Filter by task type keyword."),
    limit: int = Query(default=5, ge=1, le=20),
) -> FeedbackResponse:
    """Return top recurring quality issues for prompt injection."""
    feedback = brain.get_feedback(task_type=task_type, limit=limit)
    return FeedbackResponse(feedback=feedback)


# ---------------------------------------------------------------------------
# GET /metrics
# ---------------------------------------------------------------------------


@router.get("/metrics", response_model=MetricsResponse, status_code=status.HTTP_200_OK)
def get_metrics(brain: Memory = Depends(get_brain)) -> MetricsResponse:
    """Return aggregate run statistics."""
    m = brain.metrics
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
)
def delete_pattern(
    pattern_key: str,
    request: Request,
    brain: Memory = Depends(get_brain),
) -> DeletePatternResponse:
    """Permanently delete a stored pattern by its key."""
    try:
        deleted = brain.delete_pattern(pattern_key)
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


@router.post("/aging", response_model=AgingResponse, status_code=status.HTTP_200_OK)
def run_aging(brain: Memory = Depends(get_brain)) -> AgingResponse:
    """Apply time-based decay to all patterns. Prune those below threshold."""
    pruned = brain.run_aging()
    return AgingResponse(pruned=pruned)


# ---------------------------------------------------------------------------
# POST /feedback/decay
# ---------------------------------------------------------------------------


@router.post("/feedback/decay", response_model=FeedbackDecayResponse, status_code=status.HTTP_200_OK)
def run_feedback_decay(brain: Memory = Depends(get_brain)) -> FeedbackDecayResponse:
    """Apply time-based decay to feedback patterns. Prune those below threshold."""
    pruned = brain.run_feedback_decay()
    return FeedbackDecayResponse(pruned=pruned)


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


@router.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def health(brain: Memory = Depends(get_brain)) -> HealthResponse:
    """Health check — returns storage backend type and pattern count."""
    storage_type = brain.storage_type
    return HealthResponse(
        status="ok",
        storage=storage_type,
        pattern_count=brain.metrics.pattern_count,
    )


# ---------------------------------------------------------------------------
# POST /evolve  (Phase 3)
# ---------------------------------------------------------------------------


@router.post("/evolve", response_model=EvolveResponse, status_code=status.HTTP_200_OK)
def evolve_prompt(body: EvolveRequest, brain: Memory = Depends(get_brain)) -> EvolveResponse:
    """Generate an improved prompt based on recurring feedback patterns."""
    try:
        result = brain.evolve_prompt(
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
)
def analyze_failures(body: AnalyzeFailuresRequest, brain: Memory = Depends(get_brain)) -> AnalyzeFailuresResponse:
    """Cluster failure patterns to identify systemic issues."""
    clusters = brain.analyze_failures(min_count=body.min_count)
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
)
def register_skills(body: RegisterSkillsRequest, brain: Memory = Depends(get_brain)) -> RegisterSkillsResponse:
    """Associate skill tags with a stored pattern."""
    brain.register_skills(body.pattern_key, body.skills)
    registered = len(brain._skill_registry.get_skills(body.pattern_key))
    return RegisterSkillsResponse(registered=registered)


# ---------------------------------------------------------------------------
# POST /skills/search  (Phase 3)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# POST /import  (bulk restore)
# ---------------------------------------------------------------------------


@router.post("/import", response_model=ImportResponse, status_code=status.HTTP_200_OK)
def import_patterns(
    body: ImportRequest,
    request: Request,
    brain: Memory = Depends(get_brain),
) -> ImportResponse:
    """Bulk-import patterns from a previous export().

    Accepts records in the format produced by GET /export ({"version": 1, "key": ..., "data": ...}).
    Skips malformed records and keys that lack the patterns/ prefix.
    """
    raw_records = [r.model_dump() for r in body.records]
    imported = brain.import_data(raw_records, overwrite=body.overwrite)
    ip = request.client.host if request.client else "unknown"
    log_event(
        AuditEvent.BULK_IMPORT,
        ip=ip,
        total=len(body.records),
        imported=imported,
        overwrite=body.overwrite,
    )
    return ImportResponse(imported=imported, total=len(body.records))


@router.post(
    "/skills/search",
    response_model=RecallResponse,
    status_code=status.HTTP_200_OK,
)
def skills_search(body: SkillsSearchRequest, brain: Memory = Depends(get_brain)) -> RecallResponse:
    """Find patterns that have the required skills."""
    matches = brain.find_by_skills(required=body.required, match_all=body.match_all)
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

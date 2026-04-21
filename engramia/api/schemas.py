# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""API request and response schemas.

Separate from internal types (engramia/types.py) to allow the API
surface to evolve independently from the Engramia data models.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

#: Reusable shape for single skill-tag strings — keeps API payloads bounded.
_SkillTag = Annotated[str, Field(max_length=200)]

# ---------------------------------------------------------------------------
# POST /learn
# ---------------------------------------------------------------------------


class LearnRequest(BaseModel):
    task: str = Field(max_length=10_000, description="Natural language description of the task.")
    code: str = Field(max_length=500_000, description="Agent source code (the solution).")
    eval_score: float = Field(ge=0.0, le=10.0, description="Quality score 0-10.")
    output: str | None = Field(default=None, max_length=500_000, description="Optional captured stdout.")
    # Phase 5.6: Data Governance provenance
    run_id: str | None = Field(default=None, max_length=200, description="Caller-supplied run correlation ID.")
    classification: str = Field(
        default="internal", max_length=50, description="Data sensitivity: public|internal|confidential."
    )
    source: str = Field(default="api", max_length=50, description="Pattern origin: api|sdk|cli|import.")


class LearnResponse(BaseModel):
    stored: bool
    pattern_count: int


# ---------------------------------------------------------------------------
# POST /recall
# ---------------------------------------------------------------------------


class RecallRequest(BaseModel):
    task: str = Field(max_length=10_000, description="Task to find relevant patterns for.")
    limit: int = Field(default=5, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=10_000, description="Number of results to skip (for pagination).")
    deduplicate: bool = Field(default=True)
    eval_weighted: bool = Field(default=True)
    recency_weight: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Bias ranking toward recently-stored patterns via exponential "
            "half-life decay. 0.0 = off (default, pre-0.6.7 behaviour), "
            "1.0 = full decay. Multiplies with eval_weighted when both "
            "are active."
        ),
    )
    recency_half_life_days: float = Field(
        default=30.0,
        gt=0.0,
        description=(
            "Half-life of the recency decay in days. Patterns stored this "
            "many days ago get a recency factor of 0.5. Ignored when "
            "recency_weight == 0."
        ),
    )
    classification: str | None = Field(
        default=None, max_length=50, description="Filter by classification: public|internal|confidential."
    )
    source: str | None = Field(default=None, max_length=50, description="Filter by origin: api|sdk|cli|import.")
    min_score: float | None = Field(default=None, ge=0.0, le=10.0, description="Minimum success_score filter.")


class PatternOut(BaseModel):
    task: str
    code: str | None = None
    success_score: float
    reuse_count: int


class MatchOut(BaseModel):
    similarity: float
    reuse_tier: str
    pattern_key: str
    pattern: PatternOut


class RecallResponse(BaseModel):
    matches: list[MatchOut]
    has_more: bool = False
    next_offset: int | None = None


# ---------------------------------------------------------------------------
# POST /compose
# ---------------------------------------------------------------------------


class ComposeRequest(BaseModel):
    task: str = Field(max_length=10_000, description="High-level task to decompose into a pipeline.")


class StageOut(BaseModel):
    name: str
    task: str
    reads: list[str]
    writes: list[str]
    reuse_tier: str
    similarity: float
    code: str | None = None


class ComposeResponse(BaseModel):
    task: str
    stages: list[StageOut]
    valid: bool
    contract_errors: list[str]


# ---------------------------------------------------------------------------
# POST /evaluate
# ---------------------------------------------------------------------------


class EvaluateRequest(BaseModel):
    task: str = Field(max_length=10_000)
    code: str = Field(max_length=500_000)
    output: str | None = Field(default=None, max_length=500_000)
    num_evals: int = Field(default=3, ge=1, le=10)


class EvalScoreOut(BaseModel):
    task_alignment: float
    code_quality: float
    workspace_usage: float
    robustness: float
    overall: float
    feedback: str


class EvaluateResponse(BaseModel):
    median_score: float
    variance: float
    high_variance: bool
    feedback: str
    adversarial_detected: bool
    scores: list[EvalScoreOut]


# ---------------------------------------------------------------------------
# GET /feedback
# ---------------------------------------------------------------------------


class FeedbackResponse(BaseModel):
    feedback: list[str]
    has_more: bool = False
    next_offset: int | None = None


# ---------------------------------------------------------------------------
# GET /metrics
# ---------------------------------------------------------------------------


class MetricsResponse(BaseModel):
    runs: int
    success_rate: float
    avg_eval_score: float | None
    pattern_count: int
    reuse_rate: float


# ---------------------------------------------------------------------------
# DELETE /patterns/{key}
# ---------------------------------------------------------------------------


class DeletePatternResponse(BaseModel):
    deleted: bool
    pattern_key: str


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


class AgingResponse(BaseModel):
    pruned: int


class FeedbackDecayResponse(BaseModel):
    pruned: int


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    storage: str
    pattern_count: int


# ---------------------------------------------------------------------------
# GET /health/deep  (Phase 5.5)
# ---------------------------------------------------------------------------


class DeepHealthCheckResult(BaseModel):
    status: str
    latency_ms: float | None = None
    error: str | None = None
    current_revision: str | None = None
    expected_revision: str | None = None


class DeepHealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    checks: dict[str, DeepHealthCheckResult]


# ---------------------------------------------------------------------------
# POST /evolve
# ---------------------------------------------------------------------------


class EvolveRequest(BaseModel):
    role: str = Field(max_length=100, description="Agent role (e.g. 'coder', 'eval', 'architect').")
    current_prompt: str = Field(max_length=50_000, description="Current system prompt to improve.")
    num_issues: int = Field(default=5, ge=1, le=20)


class EvolveResponse(BaseModel):
    improved_prompt: str
    changes: list[str]
    issues_addressed: list[str]
    accepted: bool
    reason: str


# ---------------------------------------------------------------------------
# POST /analyze-failures
# ---------------------------------------------------------------------------


class AnalyzeFailuresRequest(BaseModel):
    min_count: int = Field(default=1, ge=1)


class FailureClusterOut(BaseModel):
    representative: str
    members: list[str]
    total_count: int
    avg_score: float


class AnalyzeFailuresResponse(BaseModel):
    clusters: list[FailureClusterOut]


# ---------------------------------------------------------------------------
# POST /skills/register
# ---------------------------------------------------------------------------


class RegisterSkillsRequest(BaseModel):
    pattern_key: str = Field(max_length=200, description="Storage key of the pattern to tag.")
    skills: list[_SkillTag] = Field(max_length=50, description="Skill tags to associate (e.g. ['csv_parsing']).")


class RegisterSkillsResponse(BaseModel):
    registered: int = Field(description="Number of unique skills now registered for the pattern.")


# ---------------------------------------------------------------------------
# POST /skills/search
# ---------------------------------------------------------------------------


class SkillsSearchRequest(BaseModel):
    required: list[_SkillTag] = Field(max_length=50, description="Skill tags to search for.")
    match_all: bool = Field(default=True, description="If True, pattern must have ALL skills.")


# ---------------------------------------------------------------------------
# POST /import
# ---------------------------------------------------------------------------


class ImportRecord(BaseModel):
    version: int = Field(default=1, description="Export format version.")
    key: str = Field(max_length=500, description="Storage key (must start with 'patterns/').")
    data: dict[str, Any] = Field(description="Pattern data dict.")


class ImportRequest(BaseModel):
    records: list[ImportRecord] = Field(max_length=10_000, description="Records from Memory.export().")
    overwrite: bool = Field(default=False, description="Overwrite existing patterns if True.")


class ImportResponse(BaseModel):
    imported: int = Field(description="Number of patterns successfully imported.")
    total: int = Field(description="Total records submitted.")


class ExportResponse(BaseModel):
    records: list[ImportRecord] = Field(description="Exported patterns — pass directly to POST /v1/import.")
    count: int = Field(description="Total number of exported patterns.")


# ---------------------------------------------------------------------------
# Async jobs (Phase 5.4)
# ---------------------------------------------------------------------------


class JobResponse(BaseModel):
    id: str
    operation: str
    status: str
    result: dict | None = None
    error: str | None = None
    attempts: int = 0
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None


class JobAcceptedResponse(BaseModel):
    job_id: str
    status: str = "pending"


class JobListResponse(BaseModel):
    jobs: list[JobResponse]


class JobCancelResponse(BaseModel):
    cancelled: bool
    job_id: str


# ---------------------------------------------------------------------------
# Data Governance (Phase 5.6)
# ---------------------------------------------------------------------------


class RetentionPolicyResponse(BaseModel):
    tenant_id: str
    project_id: str
    retention_days: int
    source: str = Field(description="Where the policy comes from: project|tenant|default")


class SetRetentionRequest(BaseModel):
    retention_days: int | None = Field(
        description="Retention in days. Null = inherit from tenant/global default.",
        ge=1,
        le=36500,
        default=None,
    )


class RetentionApplyRequest(BaseModel):
    dry_run: bool = Field(default=False, description="Preview without deleting.")


class RetentionApplyResponse(BaseModel):
    purged_count: int
    dry_run: bool


class ClassifyPatternRequest(BaseModel):
    classification: str = Field(
        max_length=50,
        description="New classification: public|internal|confidential",
    )


class ClassifyPatternResponse(BaseModel):
    pattern_key: str
    classification: str


class ScopedDeleteResponse(BaseModel):
    tenant_id: str
    project_id: str
    patterns_deleted: int
    jobs_deleted: int
    keys_revoked: int
    projects_deleted: int


# ---------------------------------------------------------------------------
# ROI Analytics (Phase 5.7)
# ---------------------------------------------------------------------------


class RecallOutcomeOut(BaseModel):
    total: int
    duplicate_hits: int
    adapt_hits: int
    fresh_misses: int
    reuse_rate: float
    avg_similarity: float


class LearnSummaryOut(BaseModel):
    total: int
    avg_eval_score: float
    p50_eval_score: float
    p90_eval_score: float


class ROIRollupResponse(BaseModel):
    tenant_id: str
    project_id: str
    window: str
    window_start: str
    recall: RecallOutcomeOut
    learn: LearnSummaryOut
    roi_score: float
    computed_at: str


class ROIRollupRequest(BaseModel):
    window: Literal["hourly", "daily", "weekly"] = Field(
        default="daily",
        description="Aggregation window: hourly | daily | weekly",
    )


class ROIRollupListResponse(BaseModel):
    window: str
    rollups: list[ROIRollupResponse]


class ROIEventOut(BaseModel):
    kind: str
    ts: float
    eval_score: float | None = None
    similarity: float | None = None
    reuse_tier: str | None = None
    pattern_key: str


class ROIEventsResponse(BaseModel):
    events: list[ROIEventOut]
    total: int


# ---------------------------------------------------------------------------
# Data Subject Requests (Phase 5.8 — GDPR Art. 15-20 SLA tracking)
# ---------------------------------------------------------------------------


class DSRCreateRequest(BaseModel):
    request_type: str = Field(
        description="Type of DSR: access | erasure | portability | rectification",
        pattern="^(access|erasure|portability|rectification)$",
    )
    subject_email: str = Field(
        max_length=320,
        description="E-mail address of the data subject filing the request.",
    )
    handler_notes: str = Field(
        default="",
        max_length=10_000,
        description="Optional operator notes (e.g. original request text, ticket ID).",
    )


class DSRUpdateRequest(BaseModel):
    status: str = Field(
        description="New status: pending | in_progress | completed | rejected",
        pattern="^(pending|in_progress|completed|rejected)$",
    )
    handler_notes: str = Field(
        default="",
        max_length=10_000,
        description="Operator notes to append to the existing notes.",
    )


class DSRResponse(BaseModel):
    id: str
    tenant_id: str
    request_type: str
    subject_email: str
    status: str
    created_at: str
    due_at: str
    updated_at: str
    completed_at: str | None = None
    handler_notes: str = ""
    overdue: bool = False


class DSRListResponse(BaseModel):
    requests: list[DSRResponse]
    total: int
    pending_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Counts of open requests by status: {pending, in_progress, overdue}.",
    )


# ---------------------------------------------------------------------------
# GET /audit  (Phase 6.0 — audit log viewer for admin dashboard)
# ---------------------------------------------------------------------------


class AuditEventOut(BaseModel):
    """One row from the audit_log table, projected for API clients."""

    timestamp: str = Field(description="ISO-8601 timestamp when the event was recorded.")
    action: str = Field(description="Action name, e.g. 'learn', 'key_created', 'pattern_deleted'.")
    actor: str | None = Field(default=None, description="Key ID of the caller, or null for anonymous events.")
    resource_type: str | None = Field(default=None, description="Type of the affected resource (e.g. 'pattern').")
    resource_id: str | None = Field(default=None, description="Identifier of the affected resource.")
    ip: str | None = Field(default=None, description="Client IP address recorded at the time of the event.")
    detail: dict | None = Field(default=None, description="Structured event context (counts, reason, params).")


class AuditResponse(BaseModel):
    events: list[AuditEventOut] = Field(description="Matching events, newest first, capped at `limit`.")
    total: int = Field(description="Total matching events BEFORE the limit slice — used for pagination.")

"""API request and response schemas.

Separate from internal types (engramia/types.py) to allow the API
surface to evolve independently from the Brain data models.
"""

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# POST /learn
# ---------------------------------------------------------------------------


class LearnRequest(BaseModel):
    task: str = Field(max_length=10_000, description="Natural language description of the task.")
    code: str = Field(max_length=500_000, description="Agent source code (the solution).")
    eval_score: float = Field(ge=0.0, le=10.0, description="Quality score 0-10.")
    output: str | None = Field(default=None, max_length=500_000, description="Optional captured stdout.")


class LearnResponse(BaseModel):
    stored: bool
    pattern_count: int


# ---------------------------------------------------------------------------
# POST /recall
# ---------------------------------------------------------------------------


class RecallRequest(BaseModel):
    task: str = Field(max_length=10_000, description="Task to find relevant patterns for.")
    limit: int = Field(default=5, ge=1, le=50)
    deduplicate: bool = Field(default=True)
    eval_weighted: bool = Field(default=True)


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
    skills: list[str] = Field(max_length=50, description="Skill tags to associate (e.g. ['csv_parsing']).")


class RegisterSkillsResponse(BaseModel):
    registered: int = Field(description="Number of unique skills now registered for the pattern.")


# ---------------------------------------------------------------------------
# POST /skills/search
# ---------------------------------------------------------------------------


class SkillsSearchRequest(BaseModel):
    required: list[str] = Field(max_length=50, description="Skill tags to search for.")
    match_all: bool = Field(default=True, description="If True, pattern must have ALL skills.")


# ---------------------------------------------------------------------------
# POST /import
# ---------------------------------------------------------------------------


class ImportRecord(BaseModel):
    version: int = Field(default=1, description="Export format version.")
    key: str = Field(max_length=500, description="Storage key (must start with 'patterns/').")
    data: dict[str, Any] = Field(description="Pattern data dict.")


class ImportRequest(BaseModel):
    records: list[ImportRecord] = Field(max_length=10_000, description="Records from brain.export().")
    overwrite: bool = Field(default=False, description="Overwrite existing patterns if True.")


class ImportResponse(BaseModel):
    imported: int = Field(description="Number of patterns successfully imported.")
    total: int = Field(description="Total records submitted.")

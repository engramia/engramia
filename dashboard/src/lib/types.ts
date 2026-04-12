// ── Health ──
export interface HealthResponse {
  status: string;
  storage: string;
  pattern_count: number;
}

export interface DeepHealthCheckResult {
  status: "ok" | "error";
  latency_ms: number;
  error: string | null;
}

export interface DeepHealthResponse {
  status: "ok" | "degraded" | "error";
  version: string;
  uptime_seconds: number;
  checks: Record<string, DeepHealthCheckResult>;
}

// ── Metrics ──
export interface MetricsResponse {
  runs: number;
  success_rate: number;
  avg_eval_score: number | null;
  pattern_count: number;
  reuse_rate: number;
}

// ── Patterns / Recall ──
export interface PatternOut {
  task: string;
  code: string | null;
  success_score: number;
  reuse_count: number;
}

export interface MatchOut {
  similarity: number;
  reuse_tier: string;
  pattern_key: string;
  pattern: PatternOut;
}

export interface RecallRequest {
  task: string;
  limit?: number;
  deduplicate?: boolean;
  eval_weighted?: boolean;
}

export interface RecallResponse {
  matches: MatchOut[];
}

// ── Learn ──
export interface LearnRequest {
  task: string;
  code: string;
  eval_score: number;
  output?: string | null;
  run_id?: string | null;
  classification?: string;
  source?: string;
}

export interface LearnResponse {
  stored: boolean;
  pattern_count: number;
}

// ── Evaluate ──
export interface EvalScoreOut {
  task_alignment: number;
  code_quality: number;
  workspace_usage: number;
  robustness: number;
  overall: number;
  feedback: string;
}

export interface EvaluateResponse {
  median_score: number;
  variance: number;
  high_variance: boolean;
  feedback: string;
  adversarial_detected: boolean;
  scores: EvalScoreOut[];
}

// ── Feedback ──
export interface FeedbackResponse {
  feedback: string[];
}

// ── Analytics / ROI ──
export interface RecallOutcomeOut {
  total: number;
  duplicate_hits: number;
  adapt_hits: number;
  fresh_misses: number;
  reuse_rate: number;
  avg_similarity: number;
}

export interface LearnSummaryOut {
  total: number;
  avg_eval_score: number;
  p50_eval_score: number;
  p90_eval_score: number;
}

export interface ROIRollupResponse {
  tenant_id: string;
  project_id: string;
  window: string;
  window_start: string;
  recall: RecallOutcomeOut;
  learn: LearnSummaryOut;
  roi_score: number;
  computed_at: string;
}

export interface ROIRollupListResponse {
  window: string;
  rollups: ROIRollupResponse[];
}

export interface ROIEventOut {
  kind: string;
  ts: number;
  eval_score: number | null;
  similarity: number | null;
  reuse_tier: string | null;
  pattern_key: string;
}

export interface ROIEventsResponse {
  events: ROIEventOut[];
  total: number;
}

// ── Keys ──
export interface KeyInfo {
  id: string;
  name: string;
  key_prefix: string;
  role: string;
  tenant_id: string;
  project_id: string;
  max_patterns: number | null;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  expires_at: string | null;
}

export interface KeyListResponse {
  keys: KeyInfo[];
}

export interface KeyCreateRequest {
  name: string;
  role?: string;
  max_patterns?: number | null;
  expires_at?: string | null;
}

export interface KeyCreateResponse {
  id: string;
  name: string;
  key: string;
  key_prefix: string;
  role: string;
  tenant_id: string;
  project_id: string;
  max_patterns: number | null;
  created_at: string;
}

export interface KeyRevokeResponse {
  id: string;
  revoked: boolean;
}

export interface KeyRotateResponse {
  id: string;
  key: string;
  key_prefix: string;
}

// ── Jobs ──
export interface JobResponse {
  id: string;
  operation: string;
  status: string;
  result: Record<string, unknown> | null;
  error: string | null;
  attempts: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface JobListResponse {
  jobs: JobResponse[];
}

export interface JobCancelResponse {
  cancelled: boolean;
  job_id: string;
}

// ── Governance ──
export interface RetentionPolicyResponse {
  tenant_id: string;
  project_id: string;
  retention_days: number;
  source: string;
}

export interface RetentionApplyResponse {
  purged_count: number;
  dry_run: boolean;
}

export interface ScopedDeleteResponse {
  tenant_id: string;
  project_id: string;
  patterns_deleted: number;
  jobs_deleted: number;
  keys_revoked: number;
  projects_deleted: number;
}

export interface ClassifyPatternResponse {
  pattern_key: string;
  classification: string;
}

export interface DeletePatternResponse {
  deleted: boolean;
  pattern_key: string;
}

// ── Audit ──
export interface AuditEvent {
  timestamp: string;
  action: string;
  actor: string | null;
  resource_type: string | null;
  resource_id: string | null;
  ip: string | null;
  detail: Record<string, unknown> | null;
}

export interface AuditResponse {
  events: AuditEvent[];
  total: number;
}

import type {
  HealthResponse,
  DeepHealthResponse,
  MetricsResponse,
  RecallRequest,
  RecallResponse,
  FeedbackResponse,
  ROIRollupResponse,
  ROIRollupListResponse,
  ROIEventsResponse,
  KeyListResponse,
  KeyCreateRequest,
  KeyCreateResponse,
  KeyRevokeResponse,
  KeyRotateResponse,
  JobListResponse,
  JobResponse,
  JobCancelResponse,
  RetentionPolicyResponse,
  RetentionApplyResponse,
  ScopedDeleteResponse,
  ClassifyPatternResponse,
  DeletePatternResponse,
  AuditResponse,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

export class EngramiaClient {
  constructor(
    private baseUrl: string,
    private token: string,
  ) {}

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${this.token}`,
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new ApiError(res.status, err.detail ?? "Unknown error");
    }
    return res.json();
  }

  // Health
  health() {
    return this.request<HealthResponse>("GET", "/v1/health");
  }
  healthDeep() {
    return this.request<DeepHealthResponse>("GET", "/v1/health/deep");
  }

  // Metrics
  metrics() {
    return this.request<MetricsResponse>("GET", "/v1/metrics");
  }

  // Patterns / Recall
  recall(req: RecallRequest) {
    return this.request<RecallResponse>("POST", "/v1/recall", req);
  }
  deletePattern(key: string) {
    return this.request<DeletePatternResponse>(
      "DELETE",
      `/v1/patterns/${key}`,
    );
  }

  // Feedback
  feedback(limit = 10) {
    return this.request<FeedbackResponse>(
      "GET",
      `/v1/feedback?limit=${limit}`,
    );
  }

  // Analytics
  rollup(window: string) {
    return this.request<ROIRollupResponse>(
      "GET",
      `/v1/analytics/rollup/${window}`,
    );
  }
  triggerRollup(window = "daily") {
    return this.request<ROIRollupListResponse>("POST", "/v1/analytics/rollup", {
      window,
    });
  }
  events(limit = 100, since?: number) {
    let url = `/v1/analytics/events?limit=${limit}`;
    if (since) url += `&since=${since}`;
    return this.request<ROIEventsResponse>("GET", url);
  }

  // Keys
  listKeys() {
    return this.request<KeyListResponse>("GET", "/v1/keys");
  }
  createKey(req: KeyCreateRequest) {
    return this.request<KeyCreateResponse>("POST", "/v1/keys", req);
  }
  revokeKey(id: string) {
    return this.request<KeyRevokeResponse>("DELETE", `/v1/keys/${id}`);
  }
  rotateKey(id: string) {
    return this.request<KeyRotateResponse>("POST", `/v1/keys/${id}/rotate`);
  }

  // Jobs
  listJobs(status?: string, limit = 20) {
    let url = `/v1/jobs?limit=${limit}`;
    if (status) url += `&status=${status}`;
    return this.request<JobListResponse>("GET", url);
  }
  getJob(id: string) {
    return this.request<JobResponse>("GET", `/v1/jobs/${id}`);
  }
  cancelJob(id: string) {
    return this.request<JobCancelResponse>("POST", `/v1/jobs/${id}/cancel`);
  }

  // Governance
  getRetention() {
    return this.request<RetentionPolicyResponse>(
      "GET",
      "/v1/governance/retention",
    );
  }
  setRetention(days: number | null) {
    return this.request<RetentionPolicyResponse>(
      "PUT",
      "/v1/governance/retention",
      { retention_days: days },
    );
  }
  applyRetention(dryRun = false) {
    return this.request<RetentionApplyResponse>(
      "POST",
      "/v1/governance/retention/apply",
      { dry_run: dryRun },
    );
  }
  classifyPattern(key: string, classification: string) {
    return this.request<ClassifyPatternResponse>(
      "PUT",
      `/v1/governance/patterns/${key}/classify`,
      { classification },
    );
  }
  deleteProject(projectId: string) {
    return this.request<ScopedDeleteResponse>(
      "DELETE",
      `/v1/governance/projects/${projectId}`,
    );
  }
  exportData(classification?: string) {
    const params = classification
      ? `?classification=${classification}`
      : "";
    // Returns NDJSON stream — handle differently
    return fetch(`${this.baseUrl}/v1/governance/export${params}`, {
      headers: { Authorization: `Bearer ${this.token}` },
    });
  }

  // Audit
  audit(limit = 50, since?: string, action?: string) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (since) params.set("since", since);
    if (action) params.set("action", action);
    return this.request<AuditResponse>(
      "GET",
      `/v1/audit?${params.toString()}`,
    );
  }
}

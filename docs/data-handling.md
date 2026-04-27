# Data Handling

Engramia v0.6.0 · Classification: Internal

---

## What Data Engramia Stores

Engramia stores **agent execution patterns** — structured records created when an agent successfully completes a task. It does not store end-user personal data by design. The data model:

| Field | Type | Description |
|-------|------|-------------|
| `task` | string | Task description provided by the agent system |
| `code` / `design` | string | Solution produced by the agent (code, plan, or text) |
| `eval_score` | float 0–10 | Quality score from the multi-evaluator |
| `output` | string (optional) | Agent stdout/result |
| `success_score` | float | Decaying quality score (aging applied weekly) |
| `reuse_count` | int | Number of times this pattern was recalled and reused |
| `run_id` | string (optional) | Caller-supplied run identifier for tracing |
| `classification` | enum | Data classification: PUBLIC / INTERNAL / CONFIDENTIAL |
| `source` | string (optional) | System that created this pattern |
| `author` | string (optional) | Agent or user identifier |
| `expires_at` | datetime (optional) | Explicit expiry override |
| `redacted` | bool | Whether PII was detected and redacted before storage |

Additionally stored per-pattern:
- **Embedding vector** (1536 dimensions for text-embedding-3-small) — used for semantic search only; not human-readable
- **Feedback records** — recurring quality issues extracted from eval output (text only, no PII)
- **ROI events** — anonymised recall/learn events for analytics (no task content, only metadata)
- **Audit log entries** — security events (see security-architecture.md)

---

## Where Data Is Stored

### JSON storage (development)

Data is written to the local filesystem under `ENGRAMIA_DATA_PATH` (default: `./engramia_data`) as JSON files. Not suitable for production with sensitive data.

### PostgreSQL + pgvector (production)

Tables created by Alembic migrations:

| Table | Contents |
|-------|----------|
| `memory_data` | Pattern records (all fields above) |
| `memory_embeddings` | pgvector columns for ANN search |
| `tenants` | Tenant registry with retention policies |
| `projects` | Project registry with retention and classification defaults |
| `api_keys` | Hashed API keys with role and quota |
| `audit_log` | Security event log |
| `jobs` | Async job queue |
| `analytics_events` | ROI event stream (rolling 10 000 events per scope) |

All tables include `tenant_id` and `project_id` columns. Queries are always scoped.

---

## Data Lifecycle

### Retention

Default retention: **365 days** from last update. Configurable per-tenant and per-project:

```
PUT /v1/governance/retention
{"retention_days": 90}
```

Pattern `expires_at` (if set) takes precedence over project/tenant retention.

Retention cleanup is a scheduled async job (`retention_cleanup`) that marks expired patterns for deletion. Run via `POST /v1/governance/retention/apply` or automatically via the job queue.

### Aging (quality decay)

Separately from retention, patterns decay in quality over time:
- `success_score *= 0.98^weeks_since_created`
- Patterns with `success_score < 0.1` are pruned automatically by `run_aging()`
- This is a quality control mechanism, not a privacy/compliance mechanism

### Deletion

**Per-pattern**: `DELETE /v1/patterns/{key}` — immediate, hard delete.

**Per-project** (GDPR Art. 17 right to erasure): `DELETE /v1/governance/projects/{id}`
- Cascades: pattern records + embeddings → jobs → audit_log scrub (detail field set to NULL) → API keys revoked
- Returns a `DeletionResult` with per-type counts

**Per-tenant**: `DELETE /v1/governance/tenants/{id}` — same cascade, all projects under tenant

**Self-service (cloud users only)**: `POST /auth/me/deletion-request` → email confirmation → `DELETE /auth/me?token=...`
- Two-step double-opt-in: dashboard request emits a 24h confirmation token; the link in the email is what actually triggers the cascade
- Cancels active Stripe subscription (best-effort), runs the same per-tenant cascade, then anonymises the `cloud_users` row (email rewritten to `deleted-<uuid>@deleted.engramia.dev`)
- 30-day grace window before final hard-delete by the `engramia cleanup deleted-accounts` cron command
- Owner-only as a guard against accidental loss; refuses with `409 deletion_already_pending` while a previous request is unconsumed

---

## Data Portability (GDPR Art. 20)

Export all patterns for the current scope as NDJSON:

```bash
GET /v1/governance/export
# Optional: ?classification=INTERNAL to filter by classification
```

Each record includes all pattern fields plus governance metadata. Records can be re-imported via `POST /import` or `Memory.import_data()`.

---

## PII Detection and Redaction

The `RedactionPipeline` (opt-in) scans pattern content before storage for:
- Email addresses
- IPv4 addresses
- JWT tokens
- OpenAI/Anthropic API keys
- AWS access keys
- GitHub tokens
- Hex secrets ≥ 32 characters
- Keyword-prefixed secrets (`password=`, `token=`, `secret=`, `key=`)

When PII is found:
1. The content is replaced with `[REDACTED]` before storage
2. The `redacted=true` flag is set on the pattern
3. An `PII_REDACTED` audit event is logged
4. The caller receives a `redacted: true` field in the API response

Enable per-instance:

```python
from engramia.governance.redaction import RedactionPipeline
mem = Memory(..., redaction=RedactionPipeline.default())
```

---

## Data Classification

Each pattern can be assigned a classification:

| Level | Meaning | Default |
|-------|---------|---------|
| `PUBLIC` | Safe to share, no restrictions | — |
| `INTERNAL` | Internal use only | Project default |
| `CONFIDENTIAL` | Sensitive, restricted access | — |

Classification is set at learn time or updated via `PUT /v1/governance/patterns/{key}/classify`. The export endpoint can filter by classification.

---

## Sub-processors

| Provider | Data shared | Purpose | Region |
|----------|-------------|---------|--------|
| OpenAI (opt-in) | Task + code content | LLM evaluation and embeddings | US |
| Anthropic (opt-in) | Task + code content | LLM evaluation | US |
| Hetzner Cloud | All data at rest | VM hosting | DE (FSN1) |

Data shared with LLM providers is governed by their respective DPAs. When using the `local` embeddings provider (sentence-transformers), no data is sent externally for embedding generation.

---

## Security Controls for Data

| Control | Implementation |
|---------|----------------|
| Encryption in transit | TLS 1.2+ (Caddy) for all API traffic; HTTPS for LLM API calls |
| Encryption at rest | Host-level (Hetzner disk encryption — see deployment guide) |
| Access control | RBAC (4 roles) + tenant/project scope isolation |
| Audit trail | Structured JSON audit log for all data access/mutation events |
| Data minimisation | Only data explicitly provided by the caller is stored |
| Right to erasure | `DELETE /v1/governance/projects/{id}` (GDPR Art. 17) |
| Data portability | `GET /v1/governance/export` (GDPR Art. 20) |
| Retention limits | Configurable TTL per tenant/project; default 365 days |

---

## Backup and Recovery

See [deployment.md](deployment.md) for pg_dump procedures and RTO/RPO targets.

Short summary:
- **RTO**: 4 hours (VM restore from snapshot + pg_restore)
- **RPO**: 24 hours (daily pg_dump to off-site storage)
- Recommended: configure automated daily `pg_dump` to Hetzner Object Storage (S3-compatible)

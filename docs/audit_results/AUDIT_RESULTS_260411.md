# Engramia Audit Report — 2026-04-11

> **Remediation update (2026-04-11):** 28 findings resolved across commits `71af380`, `ad40b03`, `fa43837`, `cb73e74`, `12a9b47`. All 5 "Top priorities" from the executive summary below are fixed. Full status matrix in [AUDIT_CROSS_REFERENCE_260411.md](AUDIT_CROSS_REFERENCE_260411.md#resolution-status-2026-04-11--post-remediation). Post-fix: 1344 tests pass, coverage 82.42%, ruff clean.

## Executive Summary

```
Overall score: 84/100
Audit date: 2026-04-11
Audited version: v0.6.5 (commit b657876)
Previous audit: 87.9/100 (2026-04-08)
Delta: -3.9 (new regression in health.py; prior P0s still open)

Top 5 priorities:
1. [❌] Observability — EXPECTED_MIGRATION_REVISION="013" but migration 014 exists — false health degradation in production
2. [⚠️] SDK — LangChain EngramiaCallback does not inherit BaseCallbackHandler — integration silently broken
3. [⚠️] Security — /auth/login has no brute-force rate limiting — password attacks limited only by general 60 req/min
4. [⚠️] RBAC — Import quota overshoot: _check_quota() doesn't account for batch size — callers can exceed limits
5. [⚠️] Production — OpenAI embedding provider has no retry logic — transient 5xx fails entire learn/recall
```

## Metrics

```
Test coverage:       80.84%
Number of tests:     1,426 (1,365 passed, 43 failed, 5 skipped, 13 errors)
Number of ❌ findings: 1
Number of ⚠️ findings: 20
Number of ✅ findings: 27
New issues since last audit: 2 (stale health.py:23, events total field bug)
Resolved issues since last audit: 0 of 2 prior P0s
```

---

## Detailed Findings

### 1. SECURITY AUDIT

| # | Section | Rating | Findings | Action Items |
|---|---------|--------|----------|--------------|
| 1.1 | Auth & AuthZ | ✅ OK | `hmac.compare_digest()` used at `auth.py:82`. Dev mode in production triggers `sys.exit(1)` at `app.py:76-84`. No hardcoded keys. Analytics router enforces `require_auth` + `require_permission`. | `/v1/version` exposes `git_commit` unauthenticated (`routes.py:732-744`) — consider adding auth or removing commit hash. |
| 1.2 | Input Validation | ✅ OK | All major string fields have `max_length`. `eval_score` validated [0,10] at both API (`schemas.py:21`) and library (`memory.py:619`) layers. `num_evals` capped at 10 (`schemas.py:109`). | `RegisterSkillsRequest.skills` and `SkillsSearchRequest.required` lack per-item `max_length` on individual strings (`schemas.py:254,268`). |
| 1.3 | Injection Attacks | ✅ OK | SQL: all queries parameterized via SQLAlchemy `text()` in `postgres.py`. LIKE: `_escape_like()` at `postgres.py:318-320` escapes `%` and `_`. Prompt: all LLM prompts use XML delimiters + "disregard" instructions (`composer.py:31-45`, `evaluator.py:49-64`, `prompt_evolver.py:36-50`). Path traversal: blocked at `memory.py:326,513`. CLI: no subprocess/os.system usage. | None. |
| 1.4 | Rate Limiting & DoS | ⚠️ Warning | Rate limiter at `middleware.py:79-191` with GC every 5 min. Expensive endpoints (`/evaluate`, `/compose`, `/evolve`) limited to 10 req/min. `BodySizeLimitMiddleware` checks `Content-Length` and streaming size. Auth cache bounded at 4096 LRU. | **`/auth/login` has no dedicated rate limiter** — enables brute-force attacks at 60 req/min. Add a `_check_login_rate` function similar to `_check_register_rate` at `cloud_auth.py:216`. |
| 1.5 | Security Headers & CORS | ⚠️ Warning | `SecurityHeadersMiddleware` at `middleware.py:67-76` adds `nosniff`, `DENY`, `no-referrer`, `no cross-domain`. CORS disabled by default; requires explicit `ENGRAMIA_CORS_ORIGINS`. Error responses return generic messages, no stack traces. OpenAPI hidden in production. | Missing headers: `Content-Security-Policy: default-src 'none'`, `Strict-Transport-Security`, `Permissions-Policy`, `Cache-Control: no-store`. |
| 1.6 | Audit Logging | ✅ OK | 12 event types in `AuditEvent` (`audit.py:27-41`). DB audit trail via `log_db_event()`. All auth paths, rate limits, pattern deletes, bulk imports logged with IP, tenant, key context. | Minor: consider sub-second timestamps for forensic correlation. |
| 1.7 | Cryptography & Secrets | ✅ OK | SHA-256 throughout (`auth.py:121`, `keys.py:123`, `cloud_auth.py:253`). No MD5/SHA-1 in production. `.gitignore` excludes `.env`, `*.key`, `*.pem`, `credentials*`. No hardcoded secrets found. | None. |
| 1.8 | Docker Security | ⚠️ Warning | Non-root user UID 1001 (`Dockerfile:49-50`). Multi-stage build. `.dockerignore` correct. Prod: `127.0.0.1` port binding, `no-new-privileges`, `read_only`, resource limits. pgvector pinned to `0.7.4-pg16`. | Dashboard image uses `:latest` tag in `docker-compose.prod.yml:40` — pin to specific version. Container user has default shell — add `--shell /sbin/nologin`. |

---

### 2. TEST QUALITY AUDIT

| # | Section | Rating | Findings | Action Items |
|---|---------|--------|----------|--------------|
| 2.1 | Fake Coverage | ✅ OK | Tests verify actual behavior with meaningful assertions (e.g., `pytest.approx` for similarity values). Only 5 weak `assert result is not None` across 1426 tests, all contextually appropriate. Error states tested via custom `ExplodingLLM`, `MalformedLLM`, `TimeoutLLM` in `test_llm_errors.py`. | Complete missing assertion in `test_core/test_service_recall.py:110` — `test_recall_marks_reused` has no verification that `mark_reused` was called. |
| 2.2 | Coverage Gaps | ⚠️ Warning | Overall: 80.84%. Critical gaps: `api/prom_metrics.py` at 28%, `api/cloud_auth.py` at 47%, `cli/main.py` at 52%. Well-tested: `memory.py` at 96%, ROI analytics comprehensive (30+ tests), pipeline contracts at 91%, edge cases thorough. | Add tests for `prom_metrics.py` (production `/metrics` endpoint). Add basic CLI smoke tests. |
| 2.3 | Isolation & Determinism | ⚠️ Warning | Temp files via `tmp_path` ✅. Time-dependent tests mocked ✅. Scope contextvar cleaned up ✅. No shared globals ✅. **However:** 37 Postgres tests + 13 migration errors fail without DB (should auto-skip). 5 concurrent JSONStorage tests fail on Windows. `test_api/test_auth.py:18-31` uses manual `os.environ` instead of `monkeypatch`. | Mark Postgres tests with `pytest.mark.postgres` + `skipif`. Investigate Windows concurrency failures. Refactor auth test env cleanup. |
| 2.4 | Edge Cases & Negatives | ✅ OK | Empty input, whitespace, extreme values (eval_score 11/-1, 500KB boundary), all HTTP error codes (401, 413, 422, 429, 503) tested. Missing LLM provider tested. Delete edge cases (non-existent, double-delete). Unicode roundtrip. Pattern quota enforcement. | None. |
| 2.5 | Integration & E2E | ✅ OK | `test_e2e.py`: 9 tests covering learn→recall cycle + dedup suite. `test_integration.py`: full 5-step pipeline (learn→evaluate→feedback→recall→compose). API tests use `create_app()` with full middleware stack. Recall quality benchmark suite in `tests/recall_quality/`. | Consider adding HTTP-level E2E test chaining all endpoints in sequence. |

---

### 3. FEATURE COMPLETENESS AUDIT

| # | Section | Rating | Findings | Action Items |
|---|---------|--------|----------|--------------|
| 3.1 | Core vs Roadmap | ⚠️ Warning | All completed phases (v0.1.0–v0.6.5) are implemented. Zero TODO/FIXME in codebase. **But:** Versioning Pipeline (Phase 6.5) is entirely unchecked — no annotated tag, CI version-consistency unverified. | Bootstrap hatch-vcs with annotated tag `v0.6.5`. Address Alembic 007 gap. |
| 3.2 | Public API Consistency | ✅ OK | `__init__.py` exports match actual API (10 exports). All Memory public methods have complete docstrings with Args/Returns/Raises. REST API routes correspond 1:1 to Python API (15 core endpoints + governance, analytics, keys, jobs). | None. |
| 3.3 | Provider Implementation | ⚠️ Warning | Both LLM providers implement `call()`. Both embedding providers implement `embed()` + `embed_batch()`. Both storage backends implement all required ABC methods. **But:** ORM model missing `max_execution_seconds` (migration 014). 3 tables from migrations 011-013 have no SQLAlchemy model. PostgresStorage hardcodes `Vector(1536)` — incompatible with LocalEmbeddings (384-dim). | Sync `db/models.py` with migrations 011-014. Document PG/LocalEmbeddings incompatibility. |
| 3.4 | SDK Integration | ⚠️ Warning | **`EngramiaCallback` in `sdk/langchain.py:26` does NOT inherit `BaseCallbackHandler`** — LangChain will silently ignore it. `EngramiaWebhook` is complete (15 methods matching REST API). CrewAI callback works. CLI matches documented commands. | **Fix LangChain callback to inherit `BaseCallbackHandler`** — this is a broken integration. |
| 3.5 | Data Persistence | ⚠️ Warning | Export/import format versioned (`_EXPORT_VERSION = 1`). Migration chain 001→014 complete (007 intentionally skipped). Forward-compatibility guard on import. | ORM/migration drift for 3 tables (011-013) + 1 column (014). |

---

### 4. PRODUCTION READINESS AUDIT

| # | Section | Rating | Findings | Action Items |
|---|---------|--------|----------|--------------|
| 4.1 | Error Handling | ⚠️ Warning | LLM providers have exponential backoff with jitter, 3 retries, skip on 400/401/403. Corrupted JSON handled gracefully. No bare `except:` blocks. Error responses don't expose internals. | **OpenAI embeddings have no retry logic** (`openai.py:113-138`). Add `pool_recycle=1800` to `postgres.py:81`. Remove unused `_NO_RETRY_STATUS` constants. |
| 4.2 | Concurrency | ✅ OK | `threading.Lock` in JSONStorage + rate limiter. Atomic writes via `os.replace()`. Global LLM `BoundedSemaphore(10)`. `ThreadPoolExecutor(max_workers=num_evals)` bounded. | None. |
| 4.3 | Resources | ⚠️ Warning | PG pool: `pool_size=5, max_overflow=10, pool_pre_ping=True` but no `pool_recycle`. JSONStorage loads entire `_embeddings.json` into memory — at 100K patterns could reach ~600 MB (exceeds 512 MB container limit). LLM health probe sends real API call (costs tokens). | Add `pool_recycle=1800`. Document JSONStorage is unsuitable for >5K patterns in production. Cache LLM health probe result. |
| 4.4 | Logging | ✅ OK | All 66+ modules use `logging.getLogger(__name__)`, no `print()`. JSON formatter injects `request_id`, `trace_id`, `tenant_id`. DB URLs redacted. No sensitive data in logs. | **`EXPECTED_MIGRATION_REVISION = "013"` at `health.py:23` but migration 014 exists** — update to `"014"`. |
| 4.5 | Configuration | ✅ OK | All env vars documented in `app.py:6-33`. Sensible defaults. Hard `sys.exit(1)` for dev mode in production. Hard `ValueError` for missing DB URL. | None. |
| 4.6 | Graceful Degradation | ✅ OK | Memory works without LLM (learn/recall OK, compose/evaluate raise `ProviderError`). Works without embeddings (falls back to keyword matching). Optional deps are lazy-imported. pgvector managed at infrastructure level. | None. |

---

### 5. CODE QUALITY AUDIT

| # | Section | Rating | Findings | Action Items |
|---|---------|--------|----------|--------------|
| 5.1 | Architecture & Design | ✅ OK | Clean facade pattern: `Memory` → 4 service classes in `core/services/`. Consistent DI via constructor params + FastAPI `Depends`. No circular imports (deferred imports used where needed). | None. |
| 5.2 | Code Conventions | ⚠️ Warning | `ruff check` and `ruff format --check` pass (116 files). Pydantic models in `types.py` vs `schemas.py` intentionally separated. | Dead method `Memory._require_embeddings()` at `memory.py:584`. Magic number `10000` in `cloud_auth.py:307`. |
| 5.3 | Dependency Health | ⚠️ Warning | Core deps: `pydantic>=2.0`, `numpy>=1.26` (appropriate floor pins). All optional groups properly segmented. No unused deps. | `psycopg2-binary` is in maintenance mode — consider `psycopg` (psycopg3). Run `pip audit` to verify no CVEs. |
| 5.4 | Documentation | ⚠️ Warning | README accurate (v0.6.5, 1200+ tests). CLAUDE.md reflects architecture. SECURITY.md has 10 known limitations with mitigations. | CHANGELOG has `[0.6.6]` entry without `[Unreleased]` marker. Update SECURITY.md with v0.6.5 DB auth hardening. |

---

### 6. DATA INTEGRITY AUDIT

| # | Section | Rating | Findings | Action Items |
|---|---------|--------|----------|--------------|
| 6.1 | Pattern Storage | ⚠️ Warning | Key = `patterns/<sha256(task)[:8]>_<timestamp_ms>` — no dedup-on-write (dedup at recall-time via Jaccard). Corrupted JSON returns `None` with warning. Atomic write via tmp→rename (`os.replace`). | Narrow crash window between two `os.replace` calls at `json_storage.py:157-158`. Add `.bak` recovery on startup. |
| 6.2 | Embedding Consistency | ✅ OK | Model change detected at startup (`memory.py:548-582`), warning logged. Dimension enforced at write time (JSONStorage + PostgresStorage). Zero-vector handled. Cosine similarity clamped to [0,1]. | Consider making model change a blocking error rather than warning. |
| 6.3 | Aging & Decay | ✅ OK | Compound decay: `score * 0.98^elapsed_weeks` — correct. Pruning at `_MIN_SCORE = 0.1` (~4.4 years at score 10). Reuse boost `+0.1` capped at 10.0. `elapsed_weeks` clamped to `max(0.0, ...)`. | None. |
| 6.4 | Eval Feedback | ⚠️ Warning | Feedback decay `0.90^elapsed_weeks` independent from pattern aging. Capped at `_MAX_KEEP = 50` entries per scope. Jaccard threshold 0.4 may be too low for short strings. | **Missing `max(0.0, elapsed_weeks)` clamp at `eval_feedback.py:136`** — negative elapsed_weeks (clock skew) would inflate scores. |

---

### 7. COMPLIANCE AND LEGAL AUDIT

| # | Section | Rating | Findings | Action Items |
|---|---------|--------|----------|--------------|
| 7.1 | License | ⚠️ Warning | BSL 1.1 correctly applied. Change Date: 2030-04-05. All third-party deps are permissive (MIT/BSD/Apache). 115/116 files have SPDX headers. | **`pyproject.toml:26` has misleading classifier** `"License :: Free for non-commercial use"` — BSL 1.1 permits production use. Add SPDX header to `api/errors.py`. |
| 7.2 | Legal Documents | ✅ OK | ToS (2026-03-27), Privacy Policy (2026-04-05), DPA Template (2026-03-23) all current and consistent with actual functionality. GDPR rights, data retention, sub-processors accurately documented. | Verify `https://engramia.dev/legal/subprocessors` is a live page. |

---

### 8. REGRESSION CHECK

| # | Section | Rating | Findings | Action Items |
|---|---------|--------|----------|--------------|
| 8.1 | Since Last Audit | ❌ Problem | Zero TODO/FIXME in codebase ✅. **However:** `EXPECTED_MIGRATION_REVISION = "013"` is a new regression (migration 014 exists). 2 P0 items from 260408 audit remain open: (1) `_vec_to_pg()` f-string in SQL at `postgres.py:323-325`; (2) Apple JWKS signature verification missing in `cloud_auth.py:403-428`. | **Update `health.py:23` to `"014"` immediately.** Resolve prior P0 items. Regenerate `coverage.xml`. |
| 8.2 | Git History | ✅ OK | No revert commits in last 20. Consistent conventional-commit format. Recent commits are non-security-critical (website/docs styling). | None. |

---

### 9. MULTI-TENANCY AND SCOPE ISOLATION AUDIT

| # | Section | Rating | Findings | Action Items |
|---|---------|--------|----------|--------------|
| 9.1 | Boundaries | ✅ OK | `Scope(tenant_id, project_id)` propagated via contextvar. DB enforces `UniqueConstraint("tenant_id", "project_id", "key")`. Export/import respect scope. JSONStorage maps scope to subdirectories with `_sanitize_segment()`. | No `environment` dimension — document that it must be encoded in `project_id`. |
| 9.2 | Data Isolation | ✅ OK | All PostgreSQL queries include `WHERE tenant_id = :tid AND project_id = :pid`. Vector search filtered by scope. Metrics scope-isolated. Audit trail attributed to actor/tenant. `ROICollector.load_events()` requires `admin_override=True` for cross-tenant reads. | Add explicit admin guard in `ROICollector.load_events()` for unscoped reads. |

---

### 10. RBAC AND PERMISSIONS AUDIT

| # | Section | Rating | Findings | Action Items |
|---|---------|--------|----------|--------------|
| 10.1 | Role Model | ✅ OK | 4 roles: `reader < editor < admin < owner`. 32+ permissions enforced at API layer via `require_permission()`. Destructive ops restricted by role. Role escalation prevented (`_MAX_ASSIGNABLE` map). Actor identity in audit logs. | RBAC bypassed in env-var mode (intentional) — consider logging a warning. |
| 10.2 | Key Scoping | ⚠️ Warning | Keys scoped to tenant+project. Rotation (`POST /keys/{id}/rotate`), revocation (`DELETE /keys/{id}`), expiration (`expires_at`) all implemented. Key listing scoped. Bootstrap secured with timing-safe one-time token + advisory lock. Auth cache: LRU+TTL+4096 max with immediate invalidation. | **Import quota overshoot at `routes.py:1029`** — `_check_quota()` checks current count but not `current + batch_size`. |

---

### 11. ASYNC PROCESSING AND JOB MANAGEMENT AUDIT

| # | Section | Rating | Findings | Action Items |
|---|---------|--------|----------|--------------|
| 11.1 | Background Jobs | ✅ OK | PostgreSQL `FOR UPDATE SKIP LOCKED` + in-memory fallback. 11 operation types. Status pollable via `GET /v1/jobs/{id}`. Retry with exponential backoff (3 attempts). Per-job timeout via `max_execution_seconds`. Reap loop every 60s. | None. |
| 11.2 | Backpressure | ⚠️ Warning | LLM concurrency bounded (`BoundedSemaphore(10)`). Eval bounded by `num_evals`. External call timeouts: LLM 30s, embeddings 15s. **But:** No submission backpressure — unlimited pending jobs accepted. Import/export not chunked. No PG statement timeout. Worker `_executor` used only for per-job timeout, not parallel dispatch. | Add job submission cap (HTTP 429 at threshold). Chunk import/export. Add PG `statement_timeout`. |

---

### 12. OBSERVABILITY AND TELEMETRY AUDIT

| # | Section | Rating | Findings | Action Items |
|---|---------|--------|----------|--------------|
| 12.1 | Distributed Tracing | ✅ OK | `RequestIDMiddleware` generates UUID4 or reads `X-Request-ID`. Full OTLP gRPC exporter. `@traced` decorator applied to all core operations (learn, recall, evaluate, compose, evolve, LLM calls, embeddings). | Update `telemetry/CLAUDE.md` — stale claim that `@traced` is not applied. |
| 12.2 | Metrics | ⚠️ Warning | 10 Prometheus metrics defined. Recall hit/miss wired. LLM + embedding latency tracked. ROI events recorded. `set_pattern_count()` wired. | **Job metrics (`JOB_SUBMITTED`, `JOB_COMPLETED`) defined but never called** — always zero. `observe_storage()` missing from PostgresStorage. No eval cost metric. |
| 12.3 | Alerting | ⚠️ Warning | Deep health probes storage, LLM, embedding, Redis, Stripe, migration version. JSON structured logs with request/trace/tenant IDs. 12 runbooks in `docs/runbooks/`. | **`EXPECTED_MIGRATION_REVISION = "013"` causes false degradation** (should be `"014"`). LLM health probe sends real API call — consider caching or using cheaper check. |

---

### 13. DATA GOVERNANCE AND PRIVACY AUDIT

| # | Section | Rating | Findings | Action Items |
|---|---------|--------|----------|--------------|
| 13.1 | Data Lifecycle | ✅ OK | `RetentionManager` with cascading TTL resolution (pattern → project → tenant → global 365d). Lifecycle jobs: expired cleanup, audit compaction (90d), old job cleanup (30d). Embedding reindex documented + CLI support. Export versioned. | None. |
| 13.2 | Privacy & Redaction | ✅ OK | Comprehensive regex pipeline (email, IPv4, JWT, API keys, AWS keys, GitHub tokens, phones, credit cards, hex secrets). Active by default. `DataClassification` enum (PUBLIC/INTERNAL/CONFIDENTIAL). Scoped cascade deletion. DSR workflows for GDPR Art. 15-20 with SLA tracking. | None. |
| 13.3 | Data Provenance | ✅ OK | `memory_data` stores `source`, `run_id`, `author`, `updated_at`, `classification`, `redacted`. Pattern lineage via task hash + timestamp. Audit log tracks all writes with `key_id`. | Minor: `_author_key_id` duplicated in JSON blob and DB column — consider single source of truth. |

---

### 14. PRODUCT AND POSITIONING AUDIT

| # | Section | Rating | Findings | Action Items |
|---|---------|--------|----------|--------------|
| 14.1 | Docs vs Reality | ✅ OK | README accurately reflects v0.6.5 capabilities. Feature maturity table: 21 Stable, 3 Experimental. Clear value proposition. ICP explicitly defined (AI platform teams, agent builders). | None. |
| 14.2 | Commercial Readiness | ✅ OK | Next.js dashboard at `/dashboard` in production. ROI analytics with composite score formula documented. Stripe billing integrated with plan tiers. Pricing docs exist. | None. |
| 14.3 | API Maturity | ✅ OK | Pagination with `limit`/`offset`/`has_more`/`next_offset`. Filtering by classification, source, min_score. Clear resource hierarchy. Consistent error format with machine-readable error codes. API versioning strategy documented with deprecation policy. | Minor: `docs/api-versioning.md` uses `error_message` but implementation uses `detail` — update docs. |

---

### 15. DEPLOYMENT AND OPERATIONAL MATURITY AUDIT

| # | Section | Rating | Findings | Action Items |
|---|---------|--------|----------|--------------|
| 15.1 | Production Deployment | ✅ OK | Comprehensive `docs/deployment.md`. Backup/restore with `scripts/backup.sh`, weekly verification, automated restore CI test. Disaster recovery plan for 5 scenarios. Kubernetes manifests with HPA. | None. |
| 15.2 | Zero-Downtime | ✅ OK | Expand-contract migrations (all additive). `scripts/rollback.sh` with maintenance mode + snapshot. `MaintenanceModeMiddleware` returns 503, health endpoints stay up. K8s RollingUpdate: `maxSurge: 1`, `maxUnavailable: 0`. | None. |
| 15.3 | Secrets Management | ⚠️ Warning | `.env` on production VM, root-only access. API keys hashed with SHA-256. Bootstrap token one-time. Key rotation via API. | No vault integration (acknowledged as roadmap). No automated rotation for DB/LLM/Stripe credentials. `POSTGRES_PASSWORD` appears in two places during rotation. |

---

### 16. ROI ANALYTICS AUDIT

| # | Section | Rating | Findings | Action Items |
|---|---------|--------|----------|--------------|
| 16.1 | Event Collection | ✅ OK | `record_learn()` fires on every `Memory.learn()` with `pattern_key` + `eval_score`. `record_recall()` fires on every `Memory.recall()` with similarity/tier/key. Fire-and-ignore via `except Exception` + warning. Rolling window `_MAX_EVENTS=10_000` with correct tail retention. | None. |
| 16.2 | Scope Isolation | ✅ OK | Events tagged with `scope_tenant`/`scope_project` from contextvar. `load_events()` filters by tenant+project. `admin_override` required for cross-tenant reads. Rollups stored per-scope: `analytics/rollup/{window}/{tenant}/{project}`. | None. |
| 16.3 | Rollup Correctness | ⚠️ Warning | ROI formula correct: `0.6 * reuse_rate * 10 + 0.4 * avg_eval`, clamped [0,10]. Zero events, all-learn, all-recall edge cases handled. p50 uses `statistics.median()` (correct). | **p90 underestimates for n<=3** at `aggregator.py:198` (n=2 returns index 0 = smallest value). **`total` field in `GET /events` response** at `analytics.py:177-180` is post-limit count, not total matching events — breaks pagination. |
| 16.4 | API Endpoints | ✅ OK | `POST /rollup` supports `Prefer: respond-async`. `GET /rollup/{window}` returns 404 when no data. `GET /events` respects `limit` (1-1000) and `since`. Invalid window values rejected with 422. | None. |

---

## All Action Items (sorted by priority)

### P0 — Fix immediately

| # | Area | Issue | Location |
|---|------|-------|----------|
| 1 | Observability | `EXPECTED_MIGRATION_REVISION = "013"` but migration 014 exists — production false alarm | `engramia/telemetry/health.py:23` |
| 2 | Regression | Prior P0: verify `_vec_to_pg()` f-string SQL safety (psycopg2 parameter cast to `::vector`) | `engramia/providers/postgres.py:323-325` |
| 3 | Regression | Prior P0: Apple JWKS signature verification missing | `engramia/api/cloud_auth.py:403-428` |

### P1 — Fix before next release

| # | Area | Issue | Location |
|---|------|-------|----------|
| 4 | SDK | `EngramiaCallback` doesn't inherit `BaseCallbackHandler` — LangChain integration broken | `engramia/sdk/langchain.py:26` |
| 5 | Security | `/auth/login` lacks brute-force rate limiting | `engramia/api/cloud_auth.py:549` |
| 6 | RBAC | Import quota overshoot — `_check_quota()` doesn't account for batch size | `engramia/api/routes.py:1029` |
| 7 | Production | OpenAI embeddings have no retry logic — transient failures break learn/recall | `engramia/providers/openai.py:113-138` |
| 8 | Data Integrity | Missing `max(0.0, elapsed_weeks)` clamp — clock skew inflates feedback scores | `engramia/core/eval_feedback.py:136` |
| 9 | Tests | Regenerate committed `coverage.xml` to match actual state | `coverage.xml` |

### P2 — Fix before next audit

| # | Area | Issue | Location |
|---|------|-------|----------|
| 10 | Security | Add `Content-Security-Policy: default-src 'none'` + `Strict-Transport-Security` headers | `engramia/api/middleware.py:76` |
| 11 | Docker | Pin dashboard image to specific version instead of `:latest` | `docker-compose.prod.yml:40` |
| 12 | ORM | Sync `db/models.py` with migrations 011-014 (3 missing tables + 1 missing column) | `engramia/db/models.py` |
| 13 | Production | Add `pool_recycle=1800` to PostgresStorage engine | `engramia/providers/postgres.py:81` |
| 14 | Metrics | Wire `inc_job_submitted()` and `inc_job_completed()` in job service | `engramia/jobs/service.py` |
| 15 | Metrics | Add `observe_storage()` to PostgresStorage (JSON has it, PG doesn't) | `engramia/providers/postgres.py` |
| 16 | Tests | Mark Postgres tests with `pytest.mark.postgres` + auto-skip without DB | `tests/postgres/`, `tests/test_db/` |
| 17 | Tests | Investigate concurrent JSONStorage test failures on Windows | `tests/test_json_storage_concurrent.py` |
| 18 | Compliance | Remove misleading `"License :: Free for non-commercial use"` PyPI classifier | `pyproject.toml:26` |
| 19 | Backpressure | Add job submission cap (HTTP 429 at threshold per tenant) | `engramia/jobs/service.py:58` |
| 20 | Secrets | Document secret rotation procedures for DB/LLM/Stripe credentials | `docs/` |

### P3 — Monitor / low priority

| # | Area | Issue | Location |
|---|------|-------|----------|
| 21 | Input | Add per-item `max_length` to skill tag list fields | `engramia/api/schemas.py:254,268` |
| 22 | Docker | Set `--shell /sbin/nologin` on container user | `Dockerfile:50` |
| 23 | Code Quality | Remove dead method `Memory._require_embeddings()` | `engramia/memory.py:584` |
| 24 | Code Quality | Extract magic `10000` to named constant | `engramia/api/cloud_auth.py:307` |
| 25 | Code Quality | Remove unused `_NO_RETRY_STATUS` constants | `engramia/providers/openai.py:27`, `anthropic.py:28` |
| 26 | Docs | Mark CHANGELOG `[0.6.6]` as `[Unreleased]` | `CHANGELOG.md` |
| 27 | Docs | Update `telemetry/CLAUDE.md` — `@traced` IS applied (stale known-issues) | `engramia/telemetry/CLAUDE.md` |
| 28 | Docs | Fix `error_message` vs `detail` inconsistency in API versioning docs | `docs/api-versioning.md` |
| 29 | Analytics | Fix p90 nearest-rank formula for small samples (n=2 returns wrong value) | `engramia/analytics/aggregator.py:198` |
| 30 | Analytics | Report `total` before `[:limit]` slice in events response | `engramia/api/analytics.py:177-180` |
| 31 | Dependencies | Consider migrating `psycopg2-binary` to `psycopg` (psycopg3) | `pyproject.toml` |
| 32 | Compliance | Add SPDX header to `api/errors.py` | `engramia/api/errors.py` |

---

## Comparison with Previous Audit (2026-04-08, score 87.9)

| Area | 260408 | 260411 | Delta | Notes |
|------|--------|--------|-------|-------|
| Security | Strong | Strong | = | /auth/login rate limit still missing |
| Tests | 79.84% | 80.84% | +1.0% | Coverage improved, but 50 tests still fail without DB |
| ORM Drift | Flagged | Open | = | Migrations 011-014 still not synced to models |
| Health Check | OK | ❌ Regressed | -1 | `health.py:23` not updated for migration 014 |
| SDK | Not checked | ⚠️ Found | New | LangChain callback broken (new finding) |
| Prior P0s | 2 open | 2 open | = | `_vec_to_pg()` SQL + Apple JWKS still unresolved |

**Score delta: 87.9 → 84.0 (-3.9)** — driven by new regression (stale health check), newly discovered broken LangChain integration, and 2 unresolved P0 items carried over from prior audit.

---

*Audited by Claude Opus 4.6 (1M context) on 2026-04-11. 10 parallel audit agents, 16 sections, ~48 subsections examined.*

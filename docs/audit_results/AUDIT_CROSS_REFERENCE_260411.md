# Audit Cross-Reference: Claude vs OpenAI — 2026-04-11

## Scores

| | Claude (Opus 4.6) | OpenAI |
|---|---|---|
| Overall score | 84/100 | 82/100 |
| Tests collected | 1,426 | 1,426 |
| Coverage | 80.84% | 80.68% |
| Failures/errors | 43 + 13 | 60 errors |
| Findings (problem) | 1 | 4 |
| Findings (warning) | 20 | 28 |

Both audits converge on the same major issues. OpenAI was stricter (more warnings, lower score) partly because it flagged response-model `max_length` and serial job execution as critical, and it ran a live `pip audit` catching real CVEs.

---

## Double-Checked Findings — Verdicts

Each finding was verified against the actual source code.

| # | Finding | Claude | OpenAI | Verdict | Notes |
|---|---------|--------|--------|---------|-------|
| F-01 | `_vec_to_pg()` SQL injection | P0 (carry-over) | Not present | **SAFE** — f-string at `postgres.py:323-325` uses `:.8f` (float-only output) and the result is passed as a named bind parameter (`:vec`), never interpolated into SQL. Embedding values come from providers, not user input. **Downgrade to closed.** |
| F-02 | LangChain `EngramiaCallback` broken | P1 (broken) | ✅ OK (tested) | **CONFIRMED BROKEN** — class does NOT inherit `BaseCallbackHandler`. Tests call methods directly, masking the bug. LangChain would silently ignore this callback. |
| F-03 | `max_length` on response models | Not flagged | P1 | **NOT A SECURITY ISSUE** — `max_length` on outgoing response models is irrelevant; the server controls its own output. Only request/input validation matters. **Dismiss.** |
| F-04 | Apple OAuth `NotImplementedError` | Not checked | P1 | **CONFIRMED (UX issue, not exploitable)** — `cloud_auth.py:403-412` raises `NotImplementedError`, which surfaces as 500 instead of clean 501. Not a security hole but a poor API experience. |
| F-05 | `EXPECTED_MIGRATION_REVISION` stale | P0 | P0 | **CONFIRMED** — both audits agree. `health.py:23` says "013", migration 014 exists. False degradation in production. |
| F-06 | Import quota overshoot | P1 | P0 | **CONFIRMED** — both audits agree. `routes.py:1029` checks current count but not `current + batch_size`. |
| F-07 | JobWorker serial execution | Not found | P0 | **CONFIRMED** — `ThreadPoolExecutor` at `worker.py:40` is created but **never used for dispatch**. Jobs execute serially despite `max_concurrent` parameter. Misleading API. |
| F-08 | `/auth/login` no rate limit | P1 | Not found | **CONFIRMED** — no dedicated limiter exists. General 60 req/min is too generous for auth. |
| F-09 | OpenAI embeddings no retry | P1 | Not found | **CONFIRMED** — `openai.py:113-138` has zero retry logic, unlike the LLM provider which has 3 retries with backoff. |
| F-10 | `eval_feedback.py` missing clamp | P1 | Not found | **CONFIRMED** — line 136 lacks `max(0.0, elapsed_weeks)`. Clock skew → negative weeks → score inflation via `0.90^(-N)`. |
| F-11 | Dashboard `:latest` tag in prod | P2 | P1 | **CONFIRMED** — both agree. `docker-compose.prod.yml:40`. |
| F-12 | K8s manifest wrong secret key | Not checked | P1 | **CONFIRMED** — `deploy/k8s/engramia.yaml:152-155` maps `POSTGRES_PASSWORD` from `ENGRAMIA_DATABASE_URL` (a full connection string, not a password). |
| F-13 | `cryptography` CVE | Not checked | P1 | **REAL for OIDC users** — direct dep in `oidc` extra (`pyproject.toml:65`). Upgrade to `>=46.0.7`. |
| F-14 | `pygments` CVE | Not checked | P1 | **LOW RISK** — transitive dep via `rich`. Engramia doesn't render untrusted markup. Upgrade anyway. |
| F-15 | ORM/migration drift (011-014) | P2 | Not found | **CONFIRMED** — 3 tables + 1 column missing from `db/models.py`. |
| F-16 | Missing security headers (CSP, HSTS) | P2 | P2 | **CONFIRMED** — both agree. HSTS is already on roadmap (Enterprise Hardening). |
| F-17 | PyPI classifier misleading | P2 | Not found | **CONFIRMED** — `"License :: Free for non-commercial use"` misrepresents BSL 1.1. |
| F-18 | Postgres tests don't auto-skip | P2 | P1 | **CONFIRMED** — both agree. 50+ failures when Docker unavailable. |
| F-19 | Job metrics never wired | P2 | Not found | **CONFIRMED** — `JOB_SUBMITTED`/`JOB_COMPLETED` defined but never called. |
| F-20 | `observe_storage()` missing from PG | P2 | Not found | **CONFIRMED** — JSON storage has it, Postgres doesn't. Blind spot for prod metrics. |
| F-21 | Dashboard audit page backend gap | Not checked | P1 | **CONFIRMED** — `audit/page.tsx:24-29` explicitly says endpoint may not exist. Speculative UI. |
| F-22 | Pattern list endpoint missing | Not found | P1 | **CONFIRMED** — no `GET /v1/patterns` endpoint despite dashboard expecting it. |
| F-23 | Secrets vault integration | P2 | P2 | **CONFIRMED** — both agree. Already on roadmap (Enterprise Hardening). |
| F-24 | p90 percentile wrong for small n | P3 | P2 | **CONFIRMED** — both agree. n=2 returns index 0 (smallest) instead of index 1 (largest). |
| F-25 | Analytics events `total` field bug | P3 | Not found | **CONFIRMED** — `analytics.py:177-180` reports post-limit count, not total. |

---

## Unified Prioritized Remediation Plan

### TIER 1 — Fix now (this session or next)

These are production bugs, broken integrations, or security gaps that are actively causing harm or misleading users.

| # | Issue | Both audits? | On roadmap? | Effort | Action |
|---|-------|-------------|-------------|--------|--------|
| **T1-01** | `health.py:23` — stale `EXPECTED_MIGRATION_REVISION = "013"` | Both P0 | No | 1 min | Change `"013"` → `"014"`. One-line fix. |
| **T1-02** | `sdk/langchain.py:26` — `EngramiaCallback` doesn't inherit `BaseCallbackHandler` | Claude P1 only | Roadmap: "Deep framework integrations" (Phase 6) | 15 min | Add inheritance. Fix tests to use LangChain dispatch, not direct calls. |
| **T1-03** | `cloud_auth.py:403-412` — Apple OAuth returns 500 instead of 501 | OpenAI P1 | No | 5 min | Catch `NotImplementedError` in the `/oauth` handler and return `HTTPException(501, "Apple OAuth not yet implemented")`. |
| **T1-04** | `routes.py:1029` — import quota overshoot | Both (Claude P1, OpenAI P0) | No | 15 min | Pre-compute `current_count + len(valid_records)` and reject if over limit. |
| **T1-05** | `eval_feedback.py:136` — missing `max(0.0, ...)` clamp | Claude P1 only | No | 1 min | Add `elapsed_weeks = max(0.0, elapsed_weeks)`. One-line fix. |
| **T1-06** | `deploy/k8s/engramia.yaml:152-155` — wrong secret key for POSTGRES_PASSWORD | OpenAI P1 | Roadmap: "K8s production manifests" (Enterprise) | 5 min | Change `secretKeyRef.key` from `ENGRAMIA_DATABASE_URL` to `POSTGRES_PASSWORD`. |

### TIER 2 — Fix before next release (v0.6.6)

Production resilience, metrics gaps, and test reliability.

| # | Issue | Both audits? | On roadmap? | Effort | Action |
|---|-------|-------------|-------------|--------|--------|
| **T2-01** | `openai.py:113-138` — embedding provider no retry | Claude P1 only | No | 30 min | Add retry loop matching LLM provider pattern (3 attempts, exp backoff). |
| **T2-02** | `cloud_auth.py:549` — `/auth/login` no rate limit | Claude P1 only | No | 20 min | Add `_check_login_rate` (5-10/min per IP), same pattern as `_check_register_rate`. |
| **T2-03** | `worker.py:40` / `service.py:440-453` — jobs serial despite `max_concurrent` | OpenAI P0 | No | 1-2h | Either dispatch claimed jobs to the `ThreadPoolExecutor`, or rename/remove `max_concurrent` to match reality. |
| **T2-04** | `docker-compose.prod.yml:40` — dashboard `:latest` | Both | No | 5 min | Pin to `engramia/dashboard:${IMAGE_TAG}`. |
| **T2-05** | `pyproject.toml` — `cryptography` CVE | OpenAI P1 | No | 5 min | Add `cryptography>=46.0.7` floor pin. |
| **T2-06** | `db/models.py` — ORM drift (011-014) | Claude P2 | No | 1h | Add SQLAlchemy models for `processed_webhook_events`, `dunning_events`, `cloud_users` + `max_execution_seconds` on `Job`. |
| **T2-07** | `postgres.py:81` — missing `pool_recycle` | Claude P2 | No | 5 min | Add `pool_recycle=1800` to `create_engine()`. |
| **T2-08** | `jobs/service.py` + `telemetry/metrics.py` — job metrics never wired | Claude P2 | No | 20 min | Call `inc_job_submitted()` / `inc_job_completed()` in submit/execute paths. |
| **T2-09** | `providers/postgres.py` — missing `observe_storage()` | Claude P2 | No | 20 min | Add timing wrapper matching JSONStorage pattern. |
| **T2-10** | Postgres tests don't auto-skip | Both | No | 30 min | Add `pytest.mark.postgres` + `skipif` when `ENGRAMIA_DATABASE_URL` unset. |

### TIER 3 — Fix before next audit / low priority

Documentation, cosmetics, and hardening items.

| # | Issue | On roadmap? | Effort | Action |
|---|-------|-------------|--------|--------|
| **T3-01** | HSTS header | **Yes** — Enterprise Hardening | 5 min | Add to `SecurityHeadersMiddleware`. Could do now or leave on roadmap. |
| **T3-02** | External secret management | **Yes** — Enterprise Hardening | Days | Leave on roadmap. |
| **T3-03** | Secrets rotation documentation | **Yes** — Enterprise Hardening | Hours | Leave on roadmap. |
| **T3-04** | `CSP: default-src 'none'` header | No | 5 min | Add to middleware alongside HSTS. |
| **T3-05** | `pyproject.toml:26` — misleading PyPI classifier | No | 1 min | Remove `"License :: Free for non-commercial use"`. |
| **T3-06** | `api/errors.py` — missing SPDX header | No | 1 min | Add `# SPDX-License-Identifier: BUSL-1.1`. |
| **T3-07** | Dead code: `_require_embeddings()`, `_NO_RETRY_STATUS` | No | 5 min | Remove. |
| **T3-08** | `cloud_auth.py:307` — magic `10000` | No | 5 min | Extract to named constant. |
| **T3-09** | CHANGELOG `[0.6.6]` not marked `[Unreleased]` | No | 1 min | Rename header. |
| **T3-10** | `aggregator.py:198` — p90 wrong for small n | No | 10 min | Use `math.ceil` nearest-rank. |
| **T3-11** | `analytics.py:177-180` — `total` field post-limit | No | 5 min | Compute total before slice. |
| **T3-12** | `Dockerfile:50` — no `/sbin/nologin` shell | No | 5 min | Add `--shell /sbin/nologin`. |
| **T3-13** | `telemetry/CLAUDE.md` — stale `@traced` known-issues | No | 5 min | Remove stale claim. |
| **T3-14** | `schemas.py:254,268` — skill tag per-item max_length | No | 10 min | Add `Annotated[str, Field(max_length=200)]`. |
| **T3-15** | Dashboard audit/pattern list backend gap | No | Hours | Add `GET /v1/audit` + `GET /v1/patterns` endpoints, or remove from dashboard. |
| **T3-16** | `pygments` CVE (transitive, low risk) | No | 5 min | Pin `pygments>=2.20.0` in dev extras. |

### Items already on roadmap — RECOMMENDATION

| Roadmap item | Audit finding | Recommendation |
|---|---|---|
| Deep framework integrations (Phase 6) | LangChain callback broken (T1-02) | **Fix now** — the integration is silently broken, not "planned." |
| K8s production manifests (Enterprise) | Wrong secret key (T1-06) | **Fix now** — 5-minute fix, prevents broken reference deployments. |
| HSTS header (Enterprise) | Missing security header (T3-01) | Can stay on roadmap, but it's a 5-min fix — consider bundling with T3-04. |
| External secret management (Enterprise) | No vault (T3-02) | **Leave on roadmap** — multi-day effort, not urgent for current deployment. |
| Secrets rotation docs (Enterprise) | No rotation runbook (T3-03) | **Leave on roadmap** — not blocking anything today. |
| Block `save_embedding()` on model mismatch (Deferred) | Embedding model change = warning only | **Leave on roadmap** — current warning is adequate for now. |
| Fix Alembic 007 gap (Deferred) | Migration gap documented | **Leave on roadmap** — cosmetic, chain works correctly. |

---

## Findings dismissed after double-check

| Finding | Source | Reason for dismissal |
|---|---|---|
| `_vec_to_pg()` SQL injection (prior P0) | 260408 audit | Safe: `:.8f` format guarantees float output, value passed as named bind parameter, input comes from embedding providers not users. **Close this P0.** |
| `max_length` on response models | OpenAI | Not a security issue. Response models are outgoing; the server controls its own output. |
| LangChain "exists and is tested" | OpenAI | Tests are misleading — they call methods directly, not through LangChain dispatch. The integration is broken. |

---

## Summary

**Total actionable items: 32**
- Tier 1 (fix now): **6 items**, ~45 min total effort
- Tier 2 (before v0.6.6): **10 items**, ~5h total effort
- Tier 3 (before next audit): **16 items**, mixed effort
- Already on roadmap (leave): **4 items** (vault, secrets rotation, save_embedding block, Alembic 007)
- Already on roadmap (fix now anyway): **2 items** (LangChain callback, K8s manifest)
- Dismissed after verification: **3 findings**

**Net change from prior audit:** The `_vec_to_pg()` P0 from 260408 can be **closed** (confirmed safe). The Apple JWKS P0 from 260408 remains open but is low-exploitability (returns 500 not bypass). The real urgent fixes are T1-01 through T1-06.

---

## Resolution Status (2026-04-11 — post-remediation)

Addendum recording which items from the plan above were implemented. Updated after each remediation batch; the original findings table and priorities above are preserved as the audit baseline.

### ✅ Resolved (28 items across 5 commits)

| Finding | Commit | Notes |
|---|---|---|
| F-05 / T1-01 | `71af380` | `health.py:23` `"013"` → `"014"`; false degradation eliminated |
| F-02 / T1-02 | `71af380` | `EngramiaCallback` now dynamically injects `BaseCallbackHandler` into MRO at `__init__` time so the import stays lazy but the LangChain isinstance dispatch works |
| F-06 / T1-04 | `71af380` | `_check_quota(…, additional=N)`; import endpoint passes `len(raw_records)` |
| F-10 / T1-05 | `71af380` | `max(0.0, elapsed_weeks)` clamp in `eval_feedback.py:136` |
| F-12 / T1-06 | `71af380` | K8s `secretKeyRef.key` fixed to `POSTGRES_PASSWORD` |
| F-09 / T2-01 | `ad40b03` | `OpenAIEmbeddings._call_with_retry` mirrors LLM provider (3 attempts, exp backoff, skip on auth/bad-request) |
| F-08 / T2-02 | `ad40b03` | `_check_login_rate` (10/min per IP) added to `/auth/login` |
| T2-07 | `ad40b03` | `pool_recycle=1800` on PostgresStorage engine |
| F-11 / T2-04 | `ad40b03` | Dashboard image pinned to `${IMAGE_TAG:?…}` |
| F-13 / T2-05 | `ad40b03` | `cryptography>=46.0.7` floor pin (CVE-2026-39892) |
| F-19 / T2-08 | `ad40b03` | `inc_job_submitted()` / `inc_job_completed()` wired in both in-memory + DB execution paths |
| F-20 / T2-09 | `ad40b03` | `observe_storage("postgres", …)` on PG load/save |
| F-18 / T2-10 | `ad40b03` | `tests/postgres/conftest.py` + `tests/test_db/conftest.py` auto-skip when Docker daemon or container startup fails |
| F-16 / T3-01 + T3-04 | `fa43837` | `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, `Strict-Transport-Security: max-age=63072000; includeSubDomains`, `Permissions-Policy: interest-cohort=()` |
| T3-05 | `fa43837` | Misleading `"License :: Free for non-commercial use"` classifier removed |
| T3-06 | `fa43837` | SPDX header added to `engramia/api/errors.py` |
| T3-07 | `fa43837` | Dead `Memory._require_embeddings()` removed; `_NO_RETRY_STATUS` dropped from both providers |
| T3-08 | `fa43837` | Magic `10000` extracted to `_DEFAULT_PROJECT_PATTERN_LIMIT` |
| T3-09 | `fa43837` | CHANGELOG `[0.6.6]` renamed to `[Unreleased] — targeting 0.6.6` |
| F-24 / T3-10 | `fa43837` | p90 switched to `math.ceil` nearest-rank (n=2 now returns larger value) |
| F-25 / T3-11 | `fa43837` | `GET /events` `total` captured before `[:limit]` slice |
| T3-12 | `fa43837` | Container user given `/usr/sbin/nologin` shell |
| T3-13 | `fa43837` | `engramia/telemetry/CLAUDE.md` stale "Known issues" rewritten to "Instrumentation status" |
| T3-14 | `fa43837` | Per-item `max_length=200` on skill tag strings (`_SkillTag`) |
| T3-16 | `fa43837` | `pygments>=2.20.0` pinned in dev extras (CVE-2026-4539) |
| F-07 / T2-03 | `cb73e74` | `JobService.poll_and_execute(executor=…)` dispatches each claimed job with `contextvars.copy_context()`; 3 new regression tests prove concurrency + scope isolation |
| F-15 / T2-06 | `cb73e74` | `db/models.py` gains `ProcessedWebhookEvent`, `CloudUser`, `Job.max_execution_seconds`, `BillingSubscription.past_due_since` + 7 smoke tests |
| F-21 / T3-15 | `12a9b47` | New `GET /v1/audit` endpoint (admin-only `audit:read`, cursor pagination, scope isolation, filters, 503 on non-DB, defensive `_parse_detail`) + 17 tests + dashboard types/page rewritten |

### 🗑 Dismissed after verification

| Finding | Reason |
|---|---|
| F-01 | `_vec_to_pg()` f-string passes through named bind parameter; `:.8f` format guarantees float output; embedding input comes from providers, not users. Not exploitable. |
| F-03 | `max_length` on response models is not a security control — the server governs its own output. |

### ⏸ Deferred by owner decision

| Finding | Owner note |
|---|---|
| F-04 | Apple OAuth `NotImplementedError` (500 → 501) — explicitly paused; will land when full Apple Sign-In is scoped. |

### 🕑 Remaining — still tracked

| Finding | Location | Status |
|---|---|---|
| F-22 | `GET /v1/patterns` list endpoint | Not started — separate design needed (filters, pagination, field projection). |
| F-23 | Vault / external secret management | Already on **roadmap → Enterprise Hardening**. |
| Prior-P0 | Apple JWKS signature verification | Pending Apple OAuth decision above. |
| — | LLM health probe sends real API call on every deep health check | Follow-up idea: cache 60s or swap for lighter endpoint. |
| — | `psycopg2-binary` in maintenance mode → `psycopg` (psycopg3) | Follow-up dependency modernization. |
| — | No `environment` dimension on `Scope` | Design question: encode in `project_id` (current) vs add new axis. |
| — | Import/export not chunked; no job submission backpressure | Scale gap — relevant when pattern counts grow. |

**Post-remediation test status:** 1344 passed, 5 skipped, 0 failures. Coverage 82.42% (up from 80.84% at audit time). Ruff clean.

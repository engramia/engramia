# Changelog

All notable changes to Engramia are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — targeting 0.6.6

### Added — Cloud Auth, Backup/DR, Status Page, GDPR & GTM (Phase 6.0)

- **DB migrace `013_cloud_users`** — `cloud_users` tabulka s UUID PK, bcrypt password hash, OAuth `provider_id`, tenant FK, `email_verified` flag; kompatibilní s existující API key auth bez kolize.
- **`engramia/api/cloud_auth.py`** — cloud auth REST API: `POST /auth/register` (email + bcrypt hash, welcome audit event), `POST /auth/login` (JWT access token + RT cookie), `GET /auth/me`, `POST /auth/oauth` (Google + GitHub), `POST /auth/refresh`, `POST /auth/logout`.
- **Dashboard Auth.js v5** — Credentials + Google + GitHub OAuth providers; JWT session strategy; `NEXTAUTH_SECRET` rotovatelné bez výpadku; refresh token rotace.
- **Dashboard Register page** — registrační formulář (email/password + OAuth SSO); validace na klientu i serveru.
- **Dashboard Login page (redesign)** — přepracováno z API-key-only na email/password + OAuth buttons; zpětně kompatibilní API key flow zachován.
- **Setup wizard** (3 kroky) — Welcome → výběr plánu (Sandbox/Pro/Team s feature srovnáním) → API klíč + quick-start snippet. Viditelný jen po první registraci.
- **Dashboard Dockerfile** — multi-stage build (Node 20 alpine): `deps → builder → runner`; non-root uživatel; production-only deps v runtime image.
- **`nginx/status.engramia.dev.conf`** — nginx reverse proxy pro Uptime Kuma na `status.engramia.dev` s TLS.
- **`scripts/setup-status-page.sh`** — automatizace certbot + nginx pro veřejnou status stránku.
- **`docs/ROPA.md`** — Records of Processing Activities (GDPR Art. 30): 6 aktivit zpracování (API usage, auth & access, billing, email notifications, analytics, security logging), sub-processor tabulka s transferovými mechanismy.
- **`docs/admin-guide.md`** — GitHub/Google OAuth setup, `NEXTAUTH_SECRET` generování, Stripe payment links, DB migrace postup, cloud_users správa.

### Changed

- **`website/layout.tsx`** — OG tagy (`og:title`, `og:description`, `og:image`, `og:url`) + Twitter Card metadata; "Sign up free" odkaz → `app.engramia.dev/register`.
- **`website/robots.txt`** — nový statický `robots.txt`.
- **`website/sitemap.ts`** — dynamický sitemap generátor (Next.js 15 Metadata API).
- **`website/layout.tsx` (header + footer)** — přidán support link `support@engramia.dev`.
- **`docker-compose.prod.yml` — dashboard service** — Next.js dashboard kontejner s health check, `NEXTAUTH_URL`, `NEXTAUTH_SECRET`; napojený na API service.
- **`docs/legal/PRIVACY_POLICY.md`** — sekce *Encryption*: upřesněno Hetzner CX bez HW šifrování, TLS in-transit; sekce *International Data Transfers*: SCCs pro OpenAI, Anthropic, Stripe (EU-US DPF + SCCs).

### Security

- **Backup/DR skripty** (`scripts/backup.sh`, `scripts/restore.sh`, `scripts/install-backup-cron.sh`) — automatizované `pg_dump` zálohy na Hetzner Object Storage, cron instalace, ověřený restore postup; commit `598bbdd`. *(Remediace F7 — automatizace záloh)*
- **CI security scanning** (`.github/workflows/security.yml`) — `pip-audit` (dependency audit), `bandit` (Python SAST), `Trivy` (container image scanning); spouštěno na každém PR i push. *(Remediace F8 — SAST v CI)*
- **Docker hardening** (`docker-compose.prod.yml`) — `security_opt: no-new-privileges:true`, `read_only: true` filesystem s `tmpfs` pro `/tmp` a `/run`, CPU + memory `deploy.resources.limits` pro API, DB a dashboard kontejnery. *(Remediace F14 — Docker resource limits)*
- **Swagger/OpenAPI docs zakázány v produkci** — `/docs` a `/redoc` dostupné pouze při `ENGRAMIA_ENV=dev`; v prod vrací 404. *(Snížení attack surface)*

---

## [0.6.5] — 2026-04-04

### Fixed — Security Audit P0–P2 (2026-04-04 audit)

- **Role escalation (P0)** — `POST /v1/keys` now enforces a role hierarchy: admins may create at most `editor` keys; creating `admin` or `owner` keys requires the `owner` role. `_ROLE_RANK` + `_MAX_ASSIGNABLE` enforced at the API layer; returns HTTP 403 on violation.
- **Bootstrap takeover (P0)** — `/v1/keys/bootstrap` is **disabled by default**. Set `ENGRAMIA_BOOTSTRAP_TOKEN` in the server environment to enable it. The supplied token is validated with `hmac.compare_digest`. All operations (count check + tenant/project/key insert) execute inside a single transaction protected by `pg_advisory_xact_lock` to eliminate the race condition.
- **Cross-project delete (P0)** — `DELETE /v1/governance/projects/{project_id}` now verifies that non-owner roles can only delete their own project. Cross-project deletion requires the `owner` role; admins receive HTTP 403.
- **`ALLOW_NO_AUTH` boolean parsing (P0)** — Dev mode now uses the same boolean parser as the rest of `auth.py` (`"true"/"1"/"yes"`). Strings like `"false"` or `"0"` no longer unlock unauthenticated access. Startup emits an audit-level warning when dev mode is active.
- **Job traceback leak (P0)** — `JobService` now logs full tracebacks server-side only. The `error` field stored in DB and returned by the jobs API contains only the sanitized `ExcType: message` string.
- **Redaction not wired (P1)** — `RedactionPipeline.default()` is now injected into `Memory` in the app factory by default. Disable with `ENGRAMIA_REDACTION=false` (dev/local only; logs a security warning).
- **Unprotected `/metrics` (P1)** — When `ENGRAMIA_METRICS=true`, the endpoint now requires a Bearer token if `ENGRAMIA_METRICS_TOKEN` is set. Without a token configured, startup logs a security warning.
- **Postgres scope isolation (P1)** — `memory_data` and `memory_embeddings` now have composite `UNIQUE(tenant_id, project_id, key)` constraints. `ON CONFLICT` in `postgres.py` updated to target the scope-aware constraint, preventing cross-tenant/project row collisions. Migration `009_scope_key_uniqueness`.
- **OIDC algorithm confusion (P2)** — Explicit allowlist: only `RS256/384/512`, `ES256/384/512`, `PS256/384/512` are accepted. `"none"`, HMAC, and unknown algorithms are rejected with HTTP 401. Missing tenant/project claims log a warning instead of silently falling back to `"default"`.
- **Prompt injection in evolver (P2)** — `{issues}` in `PromptEvolver` is now wrapped in `<recurring_issues>` XML delimiters, matching the delimiter style already used in `composer.py` and `evaluator.py`.

---

## [0.6.4] — 2026-04-03

### Added — Benchmark Suite (Phase 4.6)

- **`benchmarks/` package** — reproducible benchmark suite validating the 93% task success rate claim from Agent Factory V2 (254 runs). No API keys required; runs locally with `all-MiniLM-L6-v2` embeddings.
- **12 realistic agent domains** (`benchmarks/snippets/a01–a12`) — code generation, bug diagnosis, test generation, refactoring, data pipeline/ETL, API integration, infrastructure/IaC, database migration, security hardening, documentation, performance optimization, CI/CD deployment. Each domain has 3 code quality tiers (good/medium/bad) with realistic agent-generated code.
- **254-task dataset** (`benchmarks/dataset.py`) — 210 in-domain tasks (5 variants + paraphrases per domain), 30 boundary tasks (cross-domain), 14 noise tasks (completely unrelated). Ground truth labels with `expected_domains` per task.
- **Auto-calibration** (`BenchmarkRunner.calibrate()`) — computes intra-domain vs cross-domain similarity distributions at startup to derive model-appropriate thresholds. Works correctly with both local MiniLM-L6-v2 (384-dim) and OpenAI `text-embedding-3-small` (1536-dim) without manual tuning.
- **Three benchmark scenarios** — `cold_start` (no memory, baseline), `warm_up` (12 patterns, 1 per domain), `full_library` (36 patterns, 3 per domain). Full library validates the 93% claim.
- **CLI** (`python -m benchmarks`) — `--scenario {all,cold,warm,full}`, `--clean` (purge previous results), `--keep` (preserve temp storage), `--output DIR`, `--validate` (dataset integrity check). Exit code 1 if success rate < 90%.
- **Timestamped JSON results** (`benchmarks/results/`) — per-run metrics including precision@1, recall hits, quality rank, boundary matching, noise rejection, git metadata, calibration parameters.
- **`benchmarks/README.md`** — public methodology documentation for external audit.

**Benchmark results (all-MiniLM-L6-v2, 2026-04-03):**

| Scenario | Patterns | Success rate | Precision@1 |
|----------|----------|-------------|-------------|
| Cold start | 0 | 5.5% | 0% |
| Warm-up | 12 | 94.0% | 94.6% |
| Full library | 36 | **98.8%** | **98.8%** |

Agent Factory V2 claim (93%) **VALIDATED**.

---

## [0.6.3] — 2026-04-03

### Fixed — Audit Findings P2 (2026-04-02 audit)

- **PostgreSQL coverage** — `tests/test_postgres_storage_unit.py` (22 tests), `tests/test_jobs_service.py` (36 tests) — `postgres.py` and `jobs/service.py` coverage brought to acceptable levels.
- **Zero-coverage modules** — `tests/test_prom_metrics.py`, `tests/test_telemetry_logging.py` added; `oidc.py` and `mcp/server.py` marked experimental (no coverage requirement).
- **Async job durability** — `JobService._recover_orphaned_jobs()` called on startup in DB mode; in-memory mode logs a best-effort warning.
- **Embedding metadata** — `Memory._check_embedding_config()` validates dimension consistency on startup; `engramia reindex` CLI command added to support model migration.
- **RBAC in env/dev mode** — `ENGRAMIA_ENV_AUTH_ROLE` env var (default: `owner`, backward compatible); `auth_context` populated in env mode so RBAC checks are enforced consistently.
- **`.gitignore`** — added `*.pem`, `*.key`, `*.crt`, `*.p12`, `credentials*`, `secrets*`.

---

## [0.6.2] — 2026-04-03

### Fixed — Audit Findings P1 (2026-04-02 audit)

- **Auth** — unauthenticated fallback disabled when `ENGRAMIA_API_KEYS` is empty in env auth mode (`auth.py:82-85, 223-232`); empty key list now returns 401.
- **Multi-tenancy** — cross-tenant feedback leak in `EvalFeedbackStore` resolved; storage keys now always scoped to `tenant_id/project_id`.
- **Analytics** — `ROICollector._append()` race condition fixed with `threading.Lock`; concurrent writes no longer silently drop events.
- **Tests** — `pytest.importorskip` guards added to `recall_quality/conftest.py` and `test_features/conftest.py` for `sentence-transformers`; `local_embeddings` pytest marker registered. Test suite runs cleanly without optional deps.

---

## [0.6.1] — 2026-04-02

### Added — Enterprise Trust Pack (Phase 5.9)

- **`engramia/api/oidc.py`** — OIDC JWT authentication mode (`ENGRAMIA_AUTH_MODE=oidc`). Validates RS256/ECDSA Bearer tokens against any standards-compliant IdP (Okta, Auth0, Azure AD, Keycloak). JWKS keys fetched from `{issuer}/.well-known/jwks.json` and cached 1 hour. Role mapped from configurable JWT claim (`ENGRAMIA_OIDC_ROLE_CLAIM`); tenant/project optionally from JWT claims. Requires `pip install "engramia[oidc]"` (`PyJWT>=2.8` + `cryptography>=42.0`).
- **`auth.py`** — extended `require_auth` with `oidc` branch; `_use_db_auth()` skips DB for `oidc` mode.
- **`pyproject.toml`** — `[oidc]` optional extra added.
- **`docs/security-architecture.md`** — system boundary diagram, trust model, auth mode table, RBAC, token security, multi-tenancy isolation, transport security, input validation, data at rest/transit, audit events, rate limiting, secrets management, known limitations.
- **`docs/data-handling.md`** — complete data model (what is stored, where, how), data lifecycle (retention, aging, deletion), GDPR portability, PII redaction, data classification, sub-processor list, RTO/RPO summary.
- **`docs/production-hardening.md`** — pre-deployment checklist, network hardening (Caddy, firewall, PostgreSQL), Docker security options, resource limits, log rotation, monitoring (healthcheck, Prometheus, OTel), periodic maintenance schedule, secret rotation procedures, disk management.
- **`docs/backup-restore.md`** — manual + automated daily `pg_dump` to Hetzner Object Storage, cron script, weekly integrity verification, full restore procedure (maintenance mode → pg_restore → migrations), JSON storage backup, RTO/RPO targets (4h / 24h), pre-migration backup mandatory step.
- **`docs/runbooks/incident-response.md`** — severity levels (P0–P3), contact points, P0 response playbooks (API down, data breach/key compromise, DB corruption), P1 response (high latency, backup failure), GDPR 72-hour notification reminder, blameless post-mortem template, SOC 2 incident classification.
- **`docs/soc2-controls.md`** — SOC 2 Type II control mapping for CC1–CC9, A1, PI1, C1; gap summary (P1: no formal audit, P1: no SIEM; P2: pen test, vendor questionnaires); reviewer summary (EU data residency, GDPR implemented, 80.29% test coverage).

---

## [0.6.0] — 2026-04-02

### Added — Architecture Cleanup + Test Coverage (Phase 5.8)

- **Service layer** (`engramia/core/services/`) — four single-responsibility services extracted from the `Memory` god object: `LearningService` (pattern storage, embeddings, governance meta, ROI recording), `RecallService` (semantic search, deduplication, eval-weighted matching, ROI recording), `EvaluationService` (multi-evaluator LLM scoring, eval store + feedback recording), `CompositionService` (LLM task decomposition, pipeline assembly). `Memory` is now a thin facade (~165 LOC) that wires shared stores and delegates each public method.
- **PostgreSQL integration tests** (`tests/test_postgres_storage.py`) — 30 tests across 6 classes using `testcontainers[postgres]` (`pgvector/pgvector:pg16`): save/load round-trips, list_keys with prefix + sort + LIKE escape, delete (data + embedding), embedding save + ANN search, dimension mismatch errors, overwrite, `count_patterns`, scope isolation (tenant A cannot read/search/list tenant B's data), `delete_scope` bulk removal, `save_pattern_meta` governance columns. New `postgres` pytest marker; `testcontainers[postgres]>=4.0` added to dev dependencies.
- **Analytics unit tests** (`tests/test_analytics.py`) — 34 tests covering `ROICollector` (fire-and-ignore learn/recall recording, scope-aware storage, window eviction), `ROIAggregator` (rollup persistence, window types, empty-store no-op), and `_compute_rollup` formula correctness (`roi = 0.6 × reuse_rate × 10 + 0.4 × avg_eval`).
- **LLM error path tests** (extended `tests/test_llm_errors.py`) — `ConnectionError`, `TimeoutError`, malformed JSON, all-concurrent-failures (no hang), partial flaky success, `ProviderError` propagation through the multi-evaluator.
- **Concurrent JSONStorage tests** (extended `tests/test_json_storage_concurrent.py`) — `list_keys` during concurrent writes (50 writers + 20 readers, no exceptions), eventual-consistency count check, high-concurrency stress test (30 workers via `threading.Barrier`, 20 writers + 10 readers with `search_similar` + `list_keys`).

### Fixed — Exception Handling (Phase 5.8)

- **`engramia/evolution/prompt_evolver.py`** — narrowed three `except Exception` blocks to `(ValueError, RuntimeError, OSError, ConnectionError, TimeoutError)` (LLM call path) and `RuntimeError` (evaluator sub-calls). Rationale: sequential code paths should not silently swallow unexpected exceptions.
- **`engramia/reuse/composer.py`** — narrowed decomposition fallback to `(ValueError, RuntimeError, OSError, ConnectionError, TimeoutError)`.
- **`engramia/reuse/matcher.py`** — narrowed pattern deserialization skip to `(ValueError, KeyError)`.
- **`engramia/eval/evaluator.py`** — retained broad `except Exception` in `_single_eval` with explicit `# noqa: BLE001` justification: the evaluator is a concurrent retry aggregation pattern; any SDK-level exception in one attempt must return `None`, not abort all N parallel evaluations. `KeyboardInterrupt`/`SystemExit` are still excluded.

### Fixed — Dev Mode Safety (Phase 5.8)

- **`engramia/api/app.py`** — added `ENGRAMIA_ENVIRONMENT` startup guard in `_log_security_config()`: if `AUTH_MODE=dev` is set and `ENGRAMIA_ENVIRONMENT` is not one of `""`, `local`, `test`, `development`, the application calls `sys.exit(1)` with a `CRITICAL` log explaining why. This prevents accidentally running unauthenticated in staging/production.

726 tests, 0 failures, 80.29% coverage (+1.34 pp vs Phase 5.7).

---

## [0.5.9] — 2026-04-02

### Added — Admin Dashboard (Phase 5.3)

- **`dashboard/` project** — Next.js 15 (App Router) with static export (`output: "export"`), React 19, TypeScript 5, Tailwind CSS 4, Recharts 2, TanStack Query v5, Lucide React icons.
- **10 pages** — Login (API key auth), Overview (KPIs + health + ROI chart + activity), Patterns (semantic search + table), Pattern Detail (code view + classify + delete), Analytics (ROI trend + recall breakdown + eval distribution + top patterns + event stream), Evaluations (score timeline + variance alerts + feedback), Keys (CRUD + one-time secret display + rotate/revoke), Governance (retention policy + NDJSON export + scoped delete), Jobs (status table + auto-refresh + cancel + detail modal), Audit (event viewer).
- **Typed API client** (`lib/api.ts`) — `EngramiaClient` class wrapping all `/v1/*` endpoints with Bearer auth, typed request/response, `ApiError` class.
- **Auth system** (`lib/auth.ts`) — `AuthProvider` React context with localStorage persistence, role detection via `GET /v1/keys`, login/logout flow validated via `GET /v1/health`.
- **RBAC sidebar** (`lib/permissions.ts`) — mirrors backend `ROLE_PERMISSIONS` (reader/editor/admin/owner); nav items hidden when permission missing; action buttons conditionally rendered.
- **8 data hooks** — `useHealth` (30s poll), `useMetrics` (30s poll), `useAnalytics` (rollup + events + trigger), `usePatterns` (recall + delete + classify), `useKeys` (CRUD + rotate), `useJobs` (auto-refresh 5s when running), `useGovernance` (retention + apply + export + delete).
- **4 chart components** — `ROIScoreChart` (line), `RecallBreakdown` (horizontal bar), `EvalScoreTrend` (line), `ReuseTierPie` (donut). All use Recharts with dark theme styling.
- **6 UI primitives** — `Button` (4 variants), `Card` (header/title/value), `Badge` (7 colors), `Table` (sortable), `Modal` (dialog-based), `Input`/`Select`.
- **Layout components** — `Shell` (auth gate + sidebar + topbar + content), `Sidebar` (role-gated nav, active state), `Topbar` (health dot + version + role badge + logout).
- **Dark theme** — Engramia brand tokens (indigo accent, slate backgrounds), Inter + JetBrains Mono fonts.
- **FastAPI static mount** — `app.mount("/dashboard", StaticFiles(directory=dashboard/out, html=True))` serves built dashboard at `/dashboard` path. Added `PUT` to CORS allowed methods for governance endpoints.
- **Build output** — 14 static pages, ~102 KB shared JS (gzipped), zero Node.js runtime in production.

---

## [0.5.8] — 2026-03-30

### Added — ROI Analytics + Evidence Layer (Phase 5.7)

- **`engramia/analytics/` package** — standalone ROI analytics layer; four modules: `models`, `collector`, `aggregator`, `__init__`.
- **`ROIEvent` model** — captures learn and recall events with `kind`, `ts`, `eval_score`, `similarity`, `reuse_tier`, `pattern_key`, `scope_tenant`, `scope_project`.
- **`ROICollector`** — fire-and-ignore event recorder; appends to `analytics/events` key in existing storage backend (rolling window 10 000 events). Wired into `Memory.learn()` and `Memory.recall()` — never raises into callers. Supports scope filtering in `load_events()`.
- **`ROIAggregator`** — computes per-scope hourly/daily/weekly `ROIRollup` snapshots. Composite ROI score 0–10 = `0.6 × reuse_rate × 10 + 0.4 × avg_eval_score`. Persists results to `analytics/rollup/{window}/{tenant}/{project}`; O(1) reads by API.
- **`ROIRollup` model** — aggregated snapshot with `RecallOutcome` (total, duplicate_hits, adapt_hits, fresh_misses, reuse_rate, avg_similarity) and `LearnSummary` (total, avg/p50/p90 eval_score).
- **`ROI_ROLLUP` job operation** — added to `JobOperation` enum and `DISPATCHERS`; supports `Prefer: respond-async` for background execution.
- **Analytics REST API** (`/v1/analytics`) — three endpoints: `POST /rollup` (trigger/async rollup), `GET /rollup/{window}` (fetch latest snapshot for current scope), `GET /events` (raw events, newest-first, filterable by `since` + `limit`).
- **Analytics permissions** — `analytics:read` (reader+) for read endpoints, `analytics:rollup` (editor+) for rollup trigger; added to RBAC permission sets.
- **Roadmap update** — Analytics API + Dashboard integration moved from Phase 5.7 to Phase 5.3 (UI blocker); Phase 5.7 scoped to backend data collection only.
- 629 tests, 77.18% coverage (no new tests — analytics hot-path is fire-and-ignore; unit tests planned in Phase 5.8).

---

## [0.5.7] — 2026-03-30

### Added — Data Governance + Privacy (Phase 5.6)

- **`engramia/governance/` package** — standalone data governance layer; six modules: `redaction`, `retention`, `deletion`, `export`, `lifecycle`, `__init__`.
- **PII/secrets redaction pipeline** (`RedactionPipeline`) — regex-based hooks for email, IPv4, JWT, OpenAI key, AWS access key, GitHub token, hex secrets; keyword-prefix hook for `password=`, `token=`, `secret=`, `key=` etc. Zero LLM calls. Plug into `Memory.__init__(redaction=RedactionPipeline.default())`. Returns `(clean_dict, findings)` with per-field `Finding` records.
- **Data classification** (`DataClassification` StrEnum) — `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`. Stored in `memory_data.classification`; passed per `learn()` call.
- **Retention policies** (`RetentionManager`) — per-project and per-tenant configurable TTL; cascade: `pattern.expires_at > project.retention_days > tenant.retention_days > global default (365 d)`. `apply(dry_run=True)` for preview. Two code paths: fast `expires_at` SQL query for Postgres, timestamp-scan fallback for JSON storage.
- **Scoped deletion** (`ScopedDeletion`) — GDPR Art. 17 right to erasure. `delete_project()` / `delete_tenant()` cascade: storage records + embeddings → jobs → audit_log scrub (detail=NULL) → api_keys revoke → soft-delete in DB. Returns `DeletionResult` with per-type counts.
- **Scoped NDJSON export** (`DataExporter`) — GDPR Art. 20 data portability. Streams all patterns for current scope with governance metadata (`classification`, `redacted`, `source`, `run_id`). Optional `classification_filter` for partial exports. Each record is stable for re-import via `Memory.import_data()`.
- **Lifecycle jobs** — three new async job operations: `retention_cleanup`, `compact_audit_log`, `cleanup_old_jobs`. Wired into existing `JobOperation` enum and `DISPATCHERS` table. All support `dry_run` param.
- **Data provenance metadata** — `Memory.learn()` extended with `run_id`, `classification`, `source`, `author` kwargs. Stored in `memory_data` columns via `StorageBackend.save_pattern_meta()`.
- **Governance REST API** (`/v1/governance`) — seven endpoints: `GET /retention`, `PUT /retention`, `POST /retention/apply`, `GET /export` (StreamingResponse NDJSON), `PUT /patterns/{key}/classify`, `DELETE /projects/{project_id}`, `DELETE /tenants/{tenant_id}`. Guarded by `governance:read/write/admin/delete` permissions.
- **Governance permissions** — `governance:read`, `governance:write`, `governance:admin`, `governance:delete` added to admin role.
- **Audit events** — `SCOPE_DELETED`, `SCOPE_EXPORTED`, `RETENTION_APPLIED`, `PII_REDACTED` added to `AuditEvent`.
- **StorageBackend ABC extensions** — optional `save_pattern_meta()` and `delete_scope()` methods with no-op defaults; `PostgresStorage` provides efficient bulk-delete implementations.
- **Alembic migration 006** — governance columns: `tenants.retention_days`, `tenants.deleted_at`, `projects.retention_days`, `projects.default_classification`, `projects.redaction_enabled`, `projects.deleted_at`, `memory_data.classification`, `memory_data.source`, `memory_data.run_id`, `memory_data.author`, `memory_data.redacted`, `memory_data.expires_at`, `audit_log.detail`; partial index on `expires_at`, classification index.
- **CLI governance commands** — `engramia governance retention`, `engramia governance export`, `engramia governance purge-project`.
- **`LearnRequest` schema extensions** — `run_id`, `classification`, `source` fields.
- **16 new tests** (lifecycle mock-engine, retention mock-engine, export mock-engine) + prior 80 governance tests. 656 tests total, 78.70% coverage.

---

## [0.5.6] — 2026-03-29

### Added — Observability + Telemetry (Phase 5.5)

- **`engramia/telemetry/` package** — standalone observability layer; all features opt-in via env vars, zero overhead when disabled.
- **Request ID propagation** — `RequestIDMiddleware` generates UUID4 per request (or echoes caller-supplied `X-Request-ID`); stored in `engramia_request_id` contextvar; echoed in response `X-Request-ID` header.
- **Timing middleware** — `TimingMiddleware` measures per-request latency, logs at DEBUG/WARNING, feeds Prometheus histograms.
- **OpenTelemetry tracing** — `init_tracing()` with OTLP gRPC exporter; `@traced("span.name")` decorator on `LLMProvider.call()`, `EmbeddingProvider.embed/embed_batch()`, core `Memory` operations. No-op passthrough when `opentelemetry-sdk` not installed. Activate: `ENGRAMIA_TELEMETRY=true`, `ENGRAMIA_OTEL_ENDPOINT`.
- **Prometheus metrics** — histograms for request latency, LLM call duration, embedding duration, storage op duration; counters for recall hits/misses, jobs submitted/completed; gauge for pattern count. Mounted at `/metrics`. Activate: `ENGRAMIA_METRICS=true`.
- **JSON structured logging** — `python-json-logger` formatter injects `request_id`, `trace_id`, `span_id`, `tenant_id`, `project_id` into every log record. Activate: `ENGRAMIA_JSON_LOGS=true`.
- **`GET /v1/health/deep`** — probes storage (SELECT 1 / list_keys), LLM (`call("ping")`), and embedding (`embed("health check")`) with individual latency readings; aggregate status `ok` / `degraded` / `error`; HTTP 503 when all backends are unavailable.
- **`DeepHealthResponse` schema** — `status`, `version`, `uptime_seconds`, `checks` dict with per-component `status` + `latency_ms`.
- **`request_id` in async jobs** — captured at `JobService.submit()`, stored in jobs table, restored in `_execute_job()` / `_db_execute_one()` so background worker logs are correlated to the originating request.
- **Alembic migration 005** — adds nullable `request_id TEXT` column to `jobs` table.
- **`Memory.storage` / `.llm` / `.embeddings` properties** — read-only accessors used by deep health probes and provider instrumentation.
- **`[telemetry]` optional dep group** — `opentelemetry-api/sdk>=1.20`, `opentelemetry-exporter-otlp-proto-grpc`, `opentelemetry-instrumentation-fastapi`, `prometheus-client>=0.20`, `python-json-logger>=2.0`; included in `[all]`.
- **23 new tests** — request_id contextvar, middleware (UUID generation, caller-supplied ID), health probes (storage/LLM/embedding), aggregate status logic, deep health endpoint, tracing decorator, metrics no-ops. 560 tests total, 77.76% coverage.

---

## [0.5.5] — 2026-03-29

### Added — Async Job Layer (Phase 5.4)

- **DB-backed async job queue** — `engramia/jobs/` package using PostgreSQL `SELECT … FOR UPDATE SKIP LOCKED`; in-memory fallback for JSON storage mode. No Redis or Celery required.
- **`JobService`** — submit, get, list, cancel, poll-and-execute, reap-expired. Tenant/project scoped. Exponential backoff (2^attempt seconds) on failure; dead-letter after `max_attempts` (default 3).
- **`JobWorker`** — in-process background daemon thread with bounded `ThreadPoolExecutor(max_workers=3)` for backpressure. Configurable poll interval (`ENGRAMIA_JOB_POLL_INTERVAL`, default 2 s) and concurrency (`ENGRAMIA_JOB_MAX_CONCURRENT`, default 3). Integrated into FastAPI lifespan.
- **Job dispatcher** (`engramia/jobs/dispatch.py`) — maps `evaluate`, `compose`, `evolve`, `aging`, `feedback_decay`, `import`, `export` operations to Memory methods.
- **Alembic migration 004** — creates `jobs` table with `status`, `params` (JSONB), `result` (JSONB), `attempts`, `scheduled_at`, `expires_at`; polling index + tenant index.
- **`Job` SQLAlchemy model** added to `engramia/db/models.py`.
- **Dual-mode endpoints** — `/evaluate`, `/compose`, `/evolve`, `/aging`, `/feedback/decay`, `/import` return `202 Accepted` + `Location` header when `Prefer: respond-async` is present; sync path unchanged (backward compatible).
- **Job management API** — `GET /v1/jobs`, `GET /v1/jobs/{id}`, `POST /v1/jobs/{id}/cancel`.
- **RBAC permissions** — `jobs:list` + `jobs:read` (reader+), `jobs:cancel` (editor+).
- **Provider timeouts** — OpenAI LLM client: 30 s; OpenAI embeddings: 15 s; Anthropic: 30 s. Previously no timeout configured.
- **48 new tests** — job lifecycle, scope isolation, retry/backoff, worker start/stop, dual-mode API, endpoint coverage. 537 tests total, 77.81% coverage.

---

## [0.5.4] — 2026-03-29

### Added — Multi-tenancy + RBAC (Phase 5.1 + 5.2)

- **Tenant + scope isolation** — `tenant_id`/`project_id` columns added to `memory_data` and `memory_embeddings` (server default `'default'`, backward-compatible). All storage reads/writes now filter by scope.
- **Python `contextvars` scope propagation** — `engramia/_context.py` with `get_scope()`, `set_scope()`, `reset_scope()`. Scope flows automatically through FastAPI async → sync threadpool without touching call signatures.
- **JSONStorage scope-aware paths** — default scope uses `{root}` directly (backward compat); non-default scopes write to `{root}/{tenant}/{project}/`. Cross-tenant reads return `None`. `list_keys()`, `delete()`, `search_similar()`, `count_patterns()` all scope-filtered.
- **PostgresStorage scope-aware queries** — all SELECT/INSERT/UPDATE/DELETE include `AND tenant_id = :tid AND project_id = :pid` WHERE clauses via `_scope_params()`.
- **RBAC permission model** — `engramia/api/permissions.py`: four roles (owner > admin > editor > reader) with explicit permission sets; `require_permission("perm")` FastAPI dependency; owner carries wildcard `"*"`.
- **DB API key management** — `engramia/api/keys.py` router (`/v1/keys`): bootstrap, create, list, revoke, rotate endpoints. Keys stored as SHA-256 hashes with `engramia_sk_<43 base64url>` format. Full secret shown once.
- **Flexible auth mode** — `ENGRAMIA_AUTH_MODE` env var (`auto`/`env`/`db`/`dev`). `auto` (default) uses DB auth when `ENGRAMIA_DATABASE_URL` is set, falls back to env-var. Empty `ENGRAMIA_API_KEYS` continues to allow unauthenticated dev mode.
- **Auth key cache** — 60-second in-process TTL cache for DB key lookups; `invalidate_key_cache()` called immediately on revoke/rotate.
- **Pattern count quota** — `max_patterns` per key; `/learn` and `/import` return HTTP 429 with `quota_exceeded` detail when limit reached.
- **Alembic migration 003** — adds scope columns + B-tree indexes, creates `tenants`, `projects`, `api_keys`, `audit_log` tables, seeds default tenant + project.
- **Audit events** — `KEY_CREATED`, `KEY_REVOKED`, `KEY_ROTATED`, `QUOTA_EXCEEDED` added to `AuditEvent`; `log_db_event()` for DB-backed audit trail.
- **CLI key management** — `engramia keys bootstrap/create/list/revoke` commands.
- **`AuthContext` + `Scope` types** — new Pydantic models in `engramia/types.py`.
- **`StorageBackend.count_patterns()`** — new abstract method; implemented in JSONStorage and PostgresStorage.
- **`QuotaExceededError` + `AuthorizationError`** — added to exception hierarchy.
- **New test suites** — `test_scope_rbac.py` (scope contextvar, JSONStorage isolation, RBAC, quota), `test_auth_db.py` (hash, TTL cache, DB auth integration), `test_keys.py` (key generation, all CRUD endpoints); 462 tests total, coverage 78.51%.

---

## [0.5.3] — 2026-03-28

### Added — Production validation (Phase 4.6.10–4.6.12)
- Agent Factory V2 integration — local + production test on Hetzner VM; cross-run memory recall validated (sim=0.715, eval 8.6→8.8)
- `EngramiaBridge` SDK (`engramia/sdk/bridge.py`) — drop-in bridge for any agent factory with `recall_context()`, `learn_run()`, `before_run()`/`after_run()` hooks, and `@bridge.wrap` decorator; dual-mode REST/direct
- Recall quality test suite — 27 quality tests (D1 precision, D2 cross-cluster, D3 noise rejection, boundary) + 32 feature tests; `QualityTracker` with longitudinal JSON results and `report.py` trend analysis
- First quality baseline recorded: D1 avg=0.740, D2 max=0.283, D3 max=0.330, boundary 8/8

### Fixed
- `postgres.py` — `:param::type` cast conflict: vector embedded via sanitised f-string, `CAST(:data AS jsonb)` replaces `::jsonb`
- `postgres.py` — `load()` crashed on list data (eval_store): `dict(row[0])` → `return row[0]` directly
- Deploy pipeline — SCP compose files to VM instead of git pull; `--no-deps` removed so pgvector is included

---

## [0.5.2] — 2026-03-26

### Added — Framework integrations (Phase 4.6.8–4.6.9)
- CrewAI integration (`engramia/sdk/crewai.py`) — `EngramiaCrewCallback` with auto-learn on task completion, auto-recall before task start, inject_recall + kickoff wrapper
- MCP server (`engramia/mcp/server.py`) — Brain API exposed as MCP tools (learn, recall, evaluate, compose, feedback, metrics, aging); stdio transport; compatible with Claude Desktop, Cursor, Windsurf, VS Code Copilot
- MCP setup guide + example configuration in docs

### Fixed — Quick fixes (Phase 4.6.7)
- API version DRY — `app.py` imports `__version__` instead of hardcoded `"0.5.0"`
- Missing `__init__.py` in `engramia/db/migrations/` and `engramia/db/migrations/versions/`
- Explicit `rich>=13.0` dependency added to `[cli]` extra
- `[project.urls]` updated to `https://github.com/engramia/engramia`

---

## [0.5.1] — 2026-03-24

### Added — Pre-launch infrastructure (Phase 4.6.0–4.6.5)
- Branding: final name "engramia", domain `engramia.dev`, GitHub org `engramia`, PyPI Trusted Publisher (OIDC)
- Hetzner VPS (CX23, DE) with Caddy + Let's Encrypt TLS for `api.engramia.dev`
- PostgreSQL + pgvector production deploy (`pgvector/pgvector:pg16`), schema migrated
- GitHub Actions CI/CD — `ci.yml` (pytest + ruff + mypy), `publish.yml` (TestPyPI + PyPI via OIDC), `docker.yml` (GHCR + SSH deploy)
- Legal foundation: BSL 1.1 license, Terms of Service, Privacy Policy, Cookie Policy, DPA template, EU AI Act analysis
- Code quality: ruff + mypy config, pre-commit hooks, `py.typed` PEP 561 marker
- Documentation: MkDocs + Material site, ReadTheDocs integration, 8 docs pages + 3 integration guides
- Examples: 4 runnable examples (basic, REST API, LangChain, PostgreSQL, local embeddings)
- `.dockerignore` for leaner Docker builds, `CHANGELOG.md` (Keep a Changelog format)

---

## [0.5.0] — 2026-03-22

### Added — Security hardening (Phase 4.5)
- OWASP ASVS Level 2/3 compliance: timing-safe auth, rate limiting, security headers, body size limit, audit logging
- Prompt injection mitigation with XML delimiters in all LLM prompt templates
- API versioning — all endpoints under `/v1/` prefix
- Docker non-root user (`brain:1001`)
- `SECURITY.md` with 10 documented limitations and production deployment checklist

### Changed
- CORS disabled by default (was `*`); must be explicitly set via `ENGRAMIA_CORS_ORIGINS`
- SHA-256 replaces MD5 for all internal key generation
- HTTP error responses no longer expose internal exception details
- Audit logging uses structured JSON format

### Fixed
- Path traversal via `patterns/../...` keys now rejected
- PostgreSQL LIKE queries escape `%` and `_` wildcards
- API key count no longer leaked in startup log

---

## [0.4.0] — 2026-03-22

### Added — CLI, exceptions, export/import (Phase 4)
- CLI tool (`engramia init/serve/status/recall/aging`) via Typer + Rich
- Custom exception hierarchy: `EngramiaError`, `ProviderError`, `ValidationError`, `StorageError`
- `brain.export()` / `brain.import_data()` for JSONL-compatible backup and migration
- REST endpoints for Phase 3 features: `/evolve`, `/analyze-failures`, `/skills/register`, `/skills/search`

### Fixed
- `mark_reused()` now correctly updates pattern data
- Aging threshold comparison fixed
- Feedback length validation
- ISO timestamp parsing edge cases
- `ProviderError` mapped to HTTP 501

---

## [0.3.0] — 2026-03-22

### Added — SDK plugins, prompt evolution, skill registry (Phase 3)
- LangChain `EngramiaCallback` — auto-learn from chain runs, auto-recall context
- Webhook SDK client (`EngramiaWebhook`) — lightweight HTTP client (stdlib only)
- Anthropic/Claude LLM provider with retry and lazy import
- Local embeddings provider (sentence-transformers, no API key required)
- Prompt evolution — LLM-based prompt improvement with optional A/B testing
- Failure clustering — Jaccard-based grouping of recurring errors
- Skill registry — capability-based pattern tagging and search

### Changed
- Auth middleware reads env vars per-request (not at import time)
- Shared utilities extracted to `_util.py` (Jaccard, reuse_tier, PATTERNS_PREFIX)

### Fixed
- Duplicate import in routes.py
- `Brain.storage_type` property for health endpoint
- Generic error message in `_require_llm()`
- `.bak`/`.tmp` cleanup in `JSONStorage.delete()`

---

## [0.2.0] — 2026-03-22

### Added — REST API, PostgreSQL, Docker (Phase 2)
- FastAPI REST API with 14 endpoints (learn, recall, compose, evaluate, feedback, metrics, health, delete, aging, feedback/decay)
- Bearer token authentication via `ENGRAMIA_API_KEYS` env var
- PostgreSQL + pgvector storage backend with HNSW index
- Alembic migrations for database schema
- Docker multi-stage build + docker-compose
- OpenAPI/Swagger documentation at `/docs`

### Changed
- Input validation on Brain API boundary (task/code lengths, limit bounds)
- Thread safety in JSONStorage via `threading.Lock`

### Fixed
- Evaluator `num_evals` parameter handling
- Future timestamp edge cases
- Malformed ISO date parsing
- Circular pipeline detection in contract validation
- Embedding dimension mismatch error handling

---

## [0.1.0] — 2026-03-22

### Added — Core Brain library (Phase 0 + Phase 1)
- `Brain` class — central facade for self-learning agent memory
- `brain.learn()` — record successful agent runs as reusable patterns
- `brain.recall()` — semantic search with deduplication and eval-weighted matching
- `brain.evaluate()` — multi-evaluator scoring (N concurrent LLM runs, median, variance detection)
- `brain.compose()` — multi-agent pipeline composition with contract validation
- `brain.get_feedback()` — recurring quality issue surfacing for prompt injection
- `brain.run_aging()` — time-based pattern decay (2%/week) with auto-pruning
- Provider abstraction: `LLMProvider`, `EmbeddingProvider`, `StorageBackend` ABCs
- OpenAI LLM provider with retry
- OpenAI embeddings provider with native batch encoding
- JSON file storage with atomic writes and cosine similarity search
- Success pattern store with aging and reuse tracking
- Eval store with quality-weighted multiplier
- Feedback clustering (Jaccard > 0.4) with decay
- Metrics store (runs, success rate, avg score, reuse rate)

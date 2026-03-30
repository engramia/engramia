# Changelog

All notable changes to Engramia are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — Phase 5.7

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

## [Unreleased] — Phase 5.6

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

## [Unreleased] — Phase 5.4 + 5.5

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

### Added — Async job layer (Phase 5.4)

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

# Changelog

All notable changes to Engramia are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — targeting 0.6.7

### Added — Pilot Program waitlist branch + founder-signed ack template

Public-facing Pilot Program (GTM Phase B' B'7) routes its applications
through the existing `/v1/waitlist/request` endpoint; this commit adds
the segment-aware acknowledgement template and the `Reply-To` plumbing
so applicants reach the founder, not the support queue. Zero schema
changes — pilot leads piggy-back on the existing waitlist queue with a
single SQL filter (`referral_source LIKE 'pilot-%'`).

- **`engramia/email/templates.py`** — new `waitlist_pilot_ack_email()`
  template with founder-signed copy, 3-step process explainer
  ("never silence"), 5-business-day SLA. Per-segment cross-link in the
  body: `pilot-eu-compliance` → `/eu-compliance` brief,
  `pilot-openai-migration` → `/migrate/openai-assistants`,
  `pilot-custom-memory` → `/benchmarks` (LongMemEval 97.8% with
  per-dimension breakdown vs. custom-memory baselines). `pilot-other`
  and unknown segments fall back to two default links (EU + Migration).
- **`engramia/email/sender.py`** — `send_email()` gains optional
  `reply_to: str | None = None` keyword argument. Adds the `Reply-To`
  SMTP header when set, leaves the From sender untouched. Backward
  compatible — all 9 existing callers (cloud_auth, cli, waitlist) keep
  working without changes.
- **`engramia/api/waitlist.py`** — `submit_waitlist_request` branches
  on `referral_source.startswith("pilot-")`. Pilot applications get
  the new template + `Reply-To: pilot@engramia.dev`; standard waitlist
  flow is untouched. `WaitlistRequestBody.use_case` `max_length` bumped
  `1000 → 5000` to fit pilot applications, which prefix structured
  metadata (segment, current memory, traffic, region, LLM providers)
  before the free-text use case and may legitimately run long.
- **`tests/test_api/test_waitlist.py`** — new `TestWaitlistPilotPath`
  class with 7 tests covering subject match, `reply_to` header, all
  three known segments + the `pilot-other` fallback, and a regression
  test that non-pilot referrals (e.g. `Hacker News`) still hit the
  standard ack with no `reply_to`. Existing
  `test_excessive_use_case_length_rejected` updated to the new 5001
  boundary; new `test_pilot_long_use_case_accepted` exercises the
  4000-char structured payload.
- **Companion website**: https://engramia.dev/pilot — landing page
  shipping in Website repo (separate commit), POSTs to this endpoint
  with `referral_source: pilot-{segment}`.

26/26 waitlist tests green, 96/96 email + cloud_auth tests green.

### Documentation — OpenAI Assistants migration guide + ReadTheDocs hosting

7-part migration guide for teams moving off the OpenAI Assistants API
(sunsets 2026-08-26) to Engramia + the OpenAI Agents SDK. Split into
small focused units per the project's docs convention.

- **`docs/migrations/`** — new top-level docs section with `index.md`
  overview. First migration: `openai-assistants/` (8 files split into
  focused units, ~80-150 lines each): `index.md` (overview + reading
  order) + `01-concepts.md` (Threads/Messages/Files/Runs/Tools mapped
  to Engramia primitives) + `02-cutover.md` (replace
  `client.beta.assistants` with `Agent + EngramiaRunHooks +
  engramia_instructions`) + `03-export-threads.md` (enumerate Threads
  + dump to NDJSON via OpenAI API) + `04-import.md` (group
  user/assistant pairs into `Memory.learn()` calls with scope
  mapping, dedup, eval_score strategy) + `05-tools-files.md`
  (function calling carries over, `file_search` becomes pgvector
  embeddings, `code_interpreter` stays in Agents SDK) +
  `06-dual-write.md` (shadow-write → shadow-read → flagged ramp →
  retire) + `07-verification.md` (pre/post smoke checklist + rollback
  path).
- **`mkdocs.yml`** — adds `Migrations` nav block between
  `Integrations` and `Administration`.
- **`.gitignore`** — excludes `engramia_data_test/` (pytest residue).
- **ReadTheDocs hosting** — project registered at
  https://readthedocs.org/projects/engramia/. First build succeeded on
  the existing `.readthedocs.yml` config (Python 3.12 +
  mkdocs-material + docs/requirements.txt). Single Version mode
  enabled — URLs without the `/en/latest/` prefix. Docs available at
  https://engramia.readthedocs.io/. Custom domain `docs.engramia.dev`
  swap pending (Cloudflare DNS A→CNAME + Caddyfile route removal).
- **Companion landing page**: https://engramia.dev/migrate/openai-assistants
  (cross-links to the RTD guide and the example repo).
- **Companion example repo**: https://github.com/engramia/examples
  (new combined hub repo, MIT license) with
  `openai-assistants-migration/` subfolder containing runnable
  `before/`, `after/`, and `backfill/` apps pinned to
  `engramia==0.6.6`.

### Added — Phase 6.6 #6 HashiCorp Vault Transit credential backend

Alternative to the local AES-256-GCM credential backend for Enterprise
deployments where compliance auditors require master-key separation
(SOC2 / HIPAA / regulated finance). Master key never leaves Vault;
every encrypt and decrypt is logged in Vault's audit backend; rotation
is a single Vault operation with no Engramia-side data migration.

- **`engramia/credentials/backend.py`** — new module with the
  `CredentialBackend` Protocol and `EncryptedBlob` dataclass. The
  Protocol takes `tenant_id`/`provider`/`purpose` plus plaintext or
  blob; AAD-equivalent shape (row-substitution defence) is the
  responsibility of each implementation.
- **`engramia/credentials/backends/`** — new package: `local.py`
  (`LocalAESGCMBackend`, identity-preserving wrapper around the
  existing `AESGCMCipher`), `vault.py` (`VaultTransitBackend` using
  Vault Transit `derived: true` keys with per-row `context` for the
  same row-substitution defence), `vault_client.py` (hvac wrapper
  with AppRole login at startup, half-TTL token renewal, auto
  re-login on 403), and `__init__.py` (`make_backend_from_env`
  factory dispatching on `ENGRAMIA_CREDENTIALS_BACKEND`).
- **`engramia/credentials/store.py`** — `StoredCredential` gains a
  `backend` field (default `'local'`) and renames `encrypted_key` to
  `ciphertext_blob`. Back-compat preserved: the constructor accepts
  either name, and a `.encrypted_key` property still reads the bytes.
  `upsert()` accepts a new `backend=` kw arg.
- **`engramia/credentials/resolver.py`** — per-row backend dispatch
  via `_backends[row.backend]`. Handles `VaultBackendError` by
  returning `None` without marking the row invalid (the credential
  is fine; the infrastructure isn't), so a Vault recovery does not
  require any operator action. `DecryptionError` still marks rows
  invalid (real tampering signal).
- **`engramia/api/app.py`** — `_setup_byok` now uses the backend
  factory; sets `app.state.credential_backend`. `app.state.credential_cipher`
  remains populated for the local backend (back-compat for callers
  that still read it directly).
- **`engramia/api/credentials.py`** — POST and revalidation handlers
  encrypt/decrypt via the backend (no longer call `cipher.encrypt`
  / `cipher.decrypt` directly). New `_byok_backend(request)` helper
  returns 503 fast when the backend isn't wired.
- **`engramia/cli/main.py`** — new Typer subcommand
  `engramia credentials migrate-to-vault` for the bulk re-encryption
  migration. Supports `--dry-run`, `--continue-from <id>` (resume
  after crash), `--reverse` (vault → local rollback), `--tenant <id>`
  (one-tenant migration), and `--batch-size`.
- **`engramia/exceptions.py`** — new `VaultBackendError` distinct
  from `DecryptionError` so audit logs can tell "Vault is down" from
  "row is corrupt".
- **Migration `028_credential_backend`** — renames `encrypted_key →
  ciphertext_blob` and adds `backend TEXT NOT NULL DEFAULT 'local'`.
  Both operations are metadata-only on PostgreSQL ≥11 (no row
  rewrite, no downtime).
- **`pyproject.toml`** — new optional extra `vault = ["hvac>=2.3,<3"]`.
  Self-hosters under BSL do not need to install hvac unless they
  switch to the Vault backend.
- **Docs**: `Core/docs/byok/vault.md` (operator setup runbook with
  Vault commands, troubleshooting matrix, migration walk-through);
  `Core/docs/byok/index.md` updated with a link.
- **Architecture spec**: `Ops/internal/vault-credential-backend-architecture.md`
  (private — 13 sections, 6 ADRs, 6 risks, sequence diagrams).

Tests: +23 new (`tests/test_credentials_backends.py` 13,
`tests/test_credentials_vault_backend.py` 10 with mocked Vault client).
Existing 3× sibling test fixtures (`test_credentials_role_models`,
`test_credentials_failover_chain`, `test_credentials_role_cost_limits`)
updated to inject `app.state.credential_backend`. Full suite: 766
passed, 1 skipped.

Env vars (all optional with sane defaults):
- `ENGRAMIA_CREDENTIALS_BACKEND` (default `local`; `vault` opts in)
- `ENGRAMIA_VAULT_ADDR` / `_ROLE_ID` / `_SECRET_ID` (required for vault)
- `ENGRAMIA_VAULT_NAMESPACE` (Vault Enterprise; optional)
- `ENGRAMIA_VAULT_TRANSIT_PATH` / `_TRANSIT_KEY` (default `transit` / `engramia`)
- `ENGRAMIA_VAULT_TLS_VERIFY` / `_CA_CERT` / `_REQUEST_TIMEOUT`

Operator migration path: `engramia credentials migrate-to-vault
--dry-run` then real run. Online by default; pre-customer phase has
zero rows to migrate, so the script is also the regression test for
the full encryption round-trip.

### Added — Phase 6.6 #1 Hosted MCP server (Streamable HTTP transport)

Engramia Cloud now exposes its MCP tools over HTTP at `/v1/mcp` so MCP
clients (Claude Desktop, Cursor, Windsurf, custom agents) can connect
without installing the `engramia-mcp` stdio binary. Mounted behind
the `ENGRAMIA_MCP_HOSTED_ENABLED` feature flag (default off); paywalled
to Team tier and above per the pricing matrix.

- **`engramia/mcp/`** — new modules: `tools.py` (shared 9-tool catalog
  with `ToolEntry` carrying RBAC permission, minimum tier, and quota
  kind per tool), `dispatch.py` (transport-neutral sync dispatch shared
  with the stdio server), `errors.py` (`MCPError` taxonomy:
  `TierGateError`, `ConnectionLimitExceeded`, `ToolNotFoundError`,
  `ToolPermissionError`), `tier_gate.py` (`ConnectionLimiter` Protocol
  with `InMemoryConnectionLimiter` default; per-tier session caps
  5/25/100 for Team/Business/Enterprise, fail-fast HTTP 429 when full),
  `session.py` (per-MCP-session metadata via contextvar handshake into
  the SDK lifespan callback), `http_server.py` (Starlette sub-app
  mounted at `/v1/mcp` with auth + tier-gate + connection-limit ASGI
  handler delegating to `mcp.server.streamable_http_manager`),
  `metrics.py` (Prometheus collectors: active sessions, tool calls,
  evictions, rejections, durations).
- **`engramia/mcp/server.py`** — refactored to source the tool catalog
  and dispatch logic from the new shared modules. Module-level
  `_dispatch`, `_ALL_TOOLS`, `_TOOL_*` exports preserved for
  backward compatibility with tests and any external imports. Stdio
  now exposes the full 9-tool catalog (was 7) — the two new tools
  (`engramia_evolve`, `engramia_analyze_failures`) wrap the existing
  `Memory.evolve_prompt` and `Memory.analyze_failures` methods that
  the REST API already exposed at `/v1/evolve` and
  `/v1/analyze-failures`.
- **`engramia/api/app.py`** — mounts the hosted MCP sub-app from
  `_register_routers` when `ENGRAMIA_MCP_HOSTED_ENABLED=true`. Reuses
  existing `Depends(require_auth)` for Bearer / cloud JWT auth and
  `app.state.memory` for tenant-scoped Memory access via the scope
  contextvar (BYOK credentials resolve automatically through the
  existing `TenantScopedLLMProvider` wrapper from `_factory.py`).
- **`Caddyfile`** — adds an `@mcp` matcher for `/v1/mcp` with
  `flush_interval -1` (disable response buffering) and
  `response_header_timeout 30m` for long-lived SSE legs. Other
  `/v1/*` routes remain on default short timeouts.
- **`pyproject.toml`** — bumps the `mcp` extra to `mcp>=1.20,<2` so
  `mcp.server.streamable_http_manager.StreamableHTTPSessionManager`
  is available (the SDK's session lifecycle and idle-timeout
  manager).
- **`docs/integrations/mcp.md`** — documents both transports
  side-by-side: stdio for self-host single-tenant, hosted Streamable
  HTTP for cloud Team+ tenants. Adds tier×tool matrix and self-host
  Caddy snippet.
- **Architecture spec** — full pre-implementation design lives in the
  `engramia-ops` repo at `internal/hosted-mcp-architecture.md`
  (private; 13 sections including 9 components, 4 sequence diagrams,
  8 ADRs, 7 risks, OQ-001 and OQ-002 resolved).

Tests: +45 new (`tests/test_mcp_tier_gate.py`,
`tests/test_mcp_tools_catalog.py`, `tests/test_mcp_dispatch.py`,
`tests/test_mcp_http_server.py`); existing stdio suite updated for the
9-tool catalog and refactored sys.modules import-isolation between
test files.

Env vars (all optional with sane defaults):
- `ENGRAMIA_MCP_HOSTED_ENABLED` (default `false`)
- `ENGRAMIA_MCP_SESSION_IDLE_SECONDS` (default `1800`)
- `ENGRAMIA_MCP_LIMITER_BACKEND` (default `inmemory`; `redis` reserved)
- `ENGRAMIA_MCP_LIMITS_TEAM` / `_BUSINESS` / `_ENTERPRISE` (default 5/25/100)

### Fixed

- **License audit drift after `mcp` dep bump** — regenerated
  `docs/legal/DEPENDENCY_LICENSES.md` so the audit script's drift
  check passes (commit `3893168`).
- **Preexisting ruff lint warnings cleared** —
  `engramia/providers/tenant_scoped.py` and
  `engramia/telemetry/metrics.py` had U+00D7 MULTIPLICATION SIGN in
  comments (RUF002, RUF003); replaced with ASCII `x`.
  `engramia/billing/entitlements.py` and
  `engramia/credentials/store.py` had annotation-only imports outside
  the `TYPE_CHECKING` block (TC001, TC003); moved them in. CI lint
  step now passes (commit `3893168`).

### Added — Phase 6.6 Bring-Your-Own-Key (BYOK) credential subsystem

Engramia Cloud now requires tenants to supply their own LLM provider
API keys (OpenAI, Anthropic, Google Gemini, Ollama, OpenAI-compatible
endpoints) instead of running on a shared server-side key. The change
moves LLM cost from Engramia to the tenant — Engramia stops being an
LLM reseller and the eval-runs limit becomes a fair-use rate cap
rather than an LLM cost recovery.

- **`engramia/credentials/`** — new package: AES-256-GCM cipher with
  per-record nonces and AAD bound to `(tenant_id, provider, purpose)`,
  Pydantic models, store (raw SQL via SQLAlchemy text), per-tenant
  resolver with bounded TTL cache (1 h hard TTL + event-driven
  invalidation, capacity 512), and provider-side validator with
  5-second timeout.
- **`engramia/providers/`** — new providers: `gemini.py`
  (`GeminiProvider`, `GeminiEmbeddings`), `ollama.py`
  (`OllamaProvider`, `OllamaEmbeddings` — use-at-own-risk for v0.7),
  `demo.py` (`DemoProvider` + `DemoMeter` with 50 calls/month/tenant
  cap), `tenant_scoped.py` (`TenantScopedLLMProvider`,
  `TenantScopedEmbeddingProvider` — request-scoped wrappers that
  resolve credentials per tenant via `_context.get_scope()`).
  `OpenAIProvider`, `OpenAIEmbeddings`, `AnthropicProvider` gained
  optional `api_key` + `base_url` constructor kwargs that pass through
  to the SDK; env-var fallback path is unchanged for self-hosters.
- **`engramia/api/credentials.py`** — REST endpoints
  `POST/GET/PATCH/DELETE/{id}/validate` at `/v1/credentials/*`,
  admin+ only (`credentials:read` / `credentials:write` permissions).
  Plaintext `api_key` is write-only — no GET ever returns the key,
  only the last-4-char fingerprint (`sk-...abcd`).
- **`engramia/api/app.py`** — `_setup_byok` runs before Memory
  initialisation and threads the resolver into
  `make_llm` / `make_embeddings`. Gated by `ENGRAMIA_BYOK_ENABLED`
  (default `false` — self-hosters keep the env-var path; cloud flips
  it to `true`).
- **Migrations 023 + 024** — `tenant_credentials` table (BYTEA
  ciphertext + nonce + auth_tag, JSONB `role_models`, FK to
  `tenants` ON DELETE CASCADE, UNIQUE `(tenant_id, provider, purpose)`)
  and `sandbox` → `developer` plan tier rename (with `business`
  added between Team and Enterprise).
- **`engramia/billing/models.py`** — five-tier pricing: Developer
  (free, 5,000 evals), Pro ($19/mo, 50k evals), Team ($59/mo,
  250k evals), Business ($199/mo, 1M evals — new), Enterprise
  (unlimited). Yearly discount bumped from -20 % to -25 %.
  `STRIPE_PRICE_BUSINESS_{MONTHLY,YEARLY}` env vars added.
- **`docs/architecture/credentials.md`** — full architecture spec
  (threat model, data model, encryption design, per-request
  resolution flow, demo mode, migration plan, future Vault/KMS
  extensions).
- **`docs/byok/{openai,anthropic,gemini,ollama}.md`** — provider-
  specific setup guides.

### Fixed — MultiEvaluator lost the request scope in worker threads

- `MultiEvaluator.evaluate()` now wraps each `executor.submit` with
  `contextvars.copy_context().run(...)` so the scope contextvar set
  by the auth dependency propagates into the parallel eval workers.
  Without the copy, `ThreadPoolExecutor` workers started in a fresh
  default context — single-tenant deployments never noticed (the
  default context already matched the only tenant), but the BYOK
  refactor exposed it: `TenantScopedLLMProvider` saw `tenant_id="default"`
  in workers, the resolver found no credential, and every evaluation
  silently fell through to `DemoProvider`. Detected during the
  staging smoke test on 2026-04-29.

### Added — AgentTaskBench (end-to-end agent pass-rate benchmark)

- **`benchmarks/agent_task_bench/`** — new benchmark layer that
  measures agent pass-rate on HumanEval+ (164 Python coding
  problems) over N iterations. Two configurations per session:
  `baseline-no-memory` vs `engramia`. Primary metric is the pass-
  rate improvement slope — baseline stays flat, Engramia ramps as
  the pattern pool grows and `refine_pattern` keeps the best
  completions at the top of recall.
- **Agent**: `gpt-4o-mini` at `temperature=0`, one generation per
  task per iteration. Token counts tracked per call.
- **Scoring**: subprocess-isolated execution of the agent's
  completion plus the task's `check(...)` test harness with a
  30-second timeout. Non-zero exit = fail.
- **Not in CI** per decision D6 of the scope doc — full runs cost
  roughly $1.35 and take 45–60 minutes on `gpt-4o-mini`. Operators
  trigger per release candidate; results go to
  `benchmarks/results/task_bench_<engramia_version>_<date>.json`
  so cross-release comparison is a git diff of committed JSON.
- **`benchmarks/TASK_BENCH.md`** — full methodology, expected
  result shapes, reproduction commands, honesty notes on
  determinism and workload-shape dependence.

### Added — AgentLifecycleBench (closed-loop benchmark + adapter protocol)

- **`benchmarks/lifecycle.py`** — five closed-loop scenarios
  (improvement curve, deprecation speed, conflict resolution,
  concept drift, signal-to-noise floor) at three difficulty levels
  each (easy / medium / hard). Every scenario publishes a curve
  (convergence over iterations, precision@K, recency sharpness,
  classification F1) alongside the binary pass-rule score.
- **`benchmarks/adapters/base.py`** — `MemoryAdapter` +
  `LifecycleAdapter` protocols. `supports_refine` / capability
  probing lets the harness distinguish "backend failed the test"
  from "backend's API cannot attempt the test" (`capability_missing`).
- **`benchmarks/adapters/engramia_adapter.py`** — canonical adapter
  implementing both protocols; supports refine + timestamp patch.
- **Mem0 / Hindsight adapter updates** — both declare
  `supports_refine=False` with module docstrings explaining which
  upstream API is missing. First lifecycle runs show all 15
  scenario-difficulty combinations come back `capability_missing`
  for both — the honest framing the audit-rev drive required.
- **`benchmarks/LIFECYCLE.md`** — full methodology, scenario-level
  curves, and cross-backend comparison.
- **Updated `benchmarks/README.md`** — index with pointers to both
  LongMemEval and AgentLifecycleBench; flags the legacy "93 %"
  claim as pre-audit.
- **Marketing-defensible headline**: Engramia 86.7 % on the
  medium-difficulty mean (five lifecycle scenarios, 2026-04-23,
  local MiniLM embeddings). Mem0 and Hindsight cannot produce a
  comparable number because their public APIs cannot exercise
  the scenarios.

### Added — Closed-loop quality signal (survival vs ranking split)

- **`Memory.refine_pattern(pattern_key, eval_score, *, task=None, feedback="")`** —
  record a fresh quality observation against an existing pattern
  without running an LLM evaluation. Appends to the eval store so
  `eval_weighted` recall picks up the new evidence on the next call.
  Intended for feedback loops where the caller judged pattern
  usefulness externally (downstream task success, user rating, offline
  eval pipeline). Does not mutate `Pattern.success_score`;
  survival and ranking signals stay intentionally orthogonal.
- **`Memory.evaluate(..., pattern_key=...)`** — optional keyword that
  routes the evaluation result into the eval store under the caller-
  supplied pattern key, so `eval_weighted` recall for that pattern
  sees the updated median. Without the kwarg, the result is keyed by
  `sha256(code)[:12]` — the pre-0.6.8 behaviour, preserved so
  free-floating code can still be graded. Raises `ValidationError`
  when `pattern_key` is set but the pattern does not exist.
- **Agent Lifecycle Bench** — new `benchmarks/lifecycle.py` exercising
  five closed-loop scenarios (improvement curve, deprecation speed,
  conflict resolution, concept drift, signal-to-noise floor). Runs on
  local sentence-transformer embeddings by default; `--real-l5`
  opts the noise-rejection scenario into real `mem.evaluate()` calls.
- **Survival vs ranking documentation** — `docs/concepts.md` and
  `docs/api-reference.md` now explicitly split the two signal families
  so readers don't conflate `mark_reused` / `run_aging` (survival)
  with `eval_weighted` / `refine_pattern` / `recency_weight`
  (ranking). A regression test (`tests/test_ranking_feedback.py`)
  pins the decoupling so a future refactor can't accidentally merge
  them.

### Added — Recency-aware recall + honest benchmark methodology

- **`Memory.recall(recency_weight=..., recency_half_life_days=...)`** —
  new kwargs blend an exponential half-life decay on
  `Pattern.timestamp` into the ranking signal at query time.
  `recency_weight=0.0` (default) is a strict no-op preserving
  pre-0.6.7 output byte-for-byte; `1.0` applies full decay; values in
  between scale via `recency_factor ** recency_weight`.
  Composes multiplicatively with `eval_weighted`. `Match.effective_score`
  is now populated whenever any non-similarity signal is active (not
  only on the `eval_weighted=True` path). Future-dated timestamps
  (clock skew) are clamped to `age=0` — matches `run_aging` behaviour.
- **REST API `POST /v1/recall`** — new `recency_weight` and
  `recency_half_life_days` body fields with the same defaults; request
  model validates `recency_weight ∈ [0, 1]` and `recency_half_life_days > 0`.
- **SDK `EngramiaWebhook.recall`, MCP `engramia_recall` tool, CLI
  `engramia recall`** — all surfaces now accept the recency kwargs with
  matching defaults; backward-compatible with pre-0.6.7 callers.
- **LongMemEval temporal dimension** — now tests Engramia's recency-aware
  recall directly. Patterns are back-dated at seed time (v1 90 days old,
  v2 45 days old, v3 now) so the 30-day half-life discriminates them
  well above the similarity noise floor, and `_run_temporal` calls
  `recall(recency_weight=1.0, eval_weighted=False)`. OpenAI
  `text-embedding-3-small` score: 100 / 100 (was 0 / 100 under the
  pre-audit embedder-lottery protocol). Overall OpenAI:
  **97.8 % (489 / 500)**, random baseline 19.0 %, discrimination 5.1×.

### Changed

- **`Match.effective_score` docstring** updated to reflect the new
  population policy (`None` only on the plain similarity-only path).
- **Benchmark methodology** fully documented in `benchmarks/LONGMEMEVAL.md`:
  pre-registered thresholds, held-out noise calibration pool,
  recency-aware temporal check, seeded random-recall baseline.

### Added — Cloud Auth, Backup/DR, GDPR (Phase 6.0)

- **DB migration `013_cloud_users`** — `cloud_users` table with UUID PK, bcrypt password hash, OAuth `provider_id`, tenant FK, `email_verified` flag; compatible with existing API key auth without collision.
- **`engramia/api/cloud_auth.py`** — cloud auth REST API: `POST /auth/register` (email + bcrypt hash, welcome audit event), `POST /auth/login` (JWT access token + refresh-token cookie), `GET /auth/me`, `POST /auth/oauth` (Google + GitHub), `POST /auth/refresh`, `POST /auth/logout`.
- **Dashboard Auth.js v5** — Credentials + Google + GitHub OAuth providers; JWT session strategy; `NEXTAUTH_SECRET` rotatable without downtime; refresh-token rotation.
- **Dashboard Register page** — registration form (email/password + OAuth SSO); client-side and server-side validation.
- **Dashboard Login page (redesign)** — reworked from API-key-only to email/password + OAuth buttons; backwards-compatible API key flow preserved.
- **Setup wizard** (3 steps) — Welcome → plan selection (Sandbox/Pro/Team with feature comparison) → API key + quick-start snippet. Shown only after first registration.
- **Dashboard Dockerfile** — multi-stage build (Node 20 alpine): `deps → builder → runner`; non-root user; production-only dependencies in runtime image.
- **`docs/ROPA.md`** — Records of Processing Activities (GDPR Art. 30): six processing activities (API usage, auth & access, billing, email notifications, analytics, security logging) with sub-processor table and transfer mechanisms.
- **`docs/admin-guide.md`** — GitHub/Google OAuth setup, `NEXTAUTH_SECRET` generation, Stripe payment links, DB migration procedure, cloud_users management.

### Changed

- **Marketing site (`website/`)** — OpenGraph + Twitter Card metadata on layout; static `robots.txt`; dynamic sitemap generator (Next.js 15 Metadata API); `support@engramia.dev` support link in header and footer.
- **`docker-compose.prod.yml` — dashboard service** — Next.js dashboard container with health check, `NEXTAUTH_URL`, `NEXTAUTH_SECRET`; wired to the API service.
- **`docs/legal/PRIVACY_POLICY.md`** — *Encryption* section: clarified Hetzner CX without hardware encryption, TLS in-transit; *International Data Transfers* section: SCCs for OpenAI, Anthropic, Stripe (EU-US DPF + SCCs).

### Security

- **Backup/DR scripts** (`scripts/backup.sh`, `scripts/restore.sh`, `scripts/install-backup-cron.sh`) — automated `pg_dump` backups to Hetzner Object Storage, cron installation, verified restore procedure. *(Remediation F7 — backup automation)*
- **CI security scanning** (`.github/workflows/security.yml`) — `pip-audit` (dependency audit), `bandit` (Python SAST), `Trivy` (container image scanning); runs on every PR and push. *(Remediation F8 — SAST in CI)*
- **Docker hardening** (`docker-compose.prod.yml`) — `security_opt: no-new-privileges:true`, `read_only: true` filesystem with `tmpfs` for `/tmp` and `/run`, CPU + memory `deploy.resources.limits` for API, DB, and dashboard containers. *(Remediation F14 — Docker resource limits)*
- **Swagger/OpenAPI docs disabled in production** — `/docs` and `/redoc` available only when `ENGRAMIA_ENV=dev`; return 404 in production. *(Attack surface reduction)*

---

## [0.7.0] — 2026-05-01

### Added — Cloud onboarding Variant A (manual admin + waitlist + force-change-password)

Public-launch onboarding flow. Customers submit access requests through
the marketing site form; the request lands in a Core DB waitlist table
and pings the admin. The admin reviews each entry and provisions the
account via the `engramia waitlist approve` CLI, which also flips a
`must_change_password` flag on the new user. The credentials email
contains a one-time plaintext password the customer must change on first
login. Self-service `/auth/register` is feature-flagged off; switching
to fully self-serve later is a single env-var flip.

Architecture: `Ops/internal/cloud-onboarding-architecture.md` (10
components, 8 ADRs, 5 sequence diagrams).

- **`engramia/api/waitlist.py`** — new module. `POST /v1/waitlist/request`
  is a public, rate-limited (5/min/IP) endpoint that validates the
  submission via Pydantic (email regex, ISO-3166-1 alpha-2 country code,
  `plan_interest` enum, `use_case` conditionally required for paid
  plans), persists to `waitlist_requests`, and best-effort dispatches an
  acknowledgement email to the requester + a notification to the admin
  at `support@engramia.dev` (override via `ENGRAMIA_WAITLIST_ADMIN_EMAIL`).
- **`engramia/api/cloud_auth.py`** — `POST /auth/register` gated by the
  new `ENGRAMIA_REGISTRATION_ENABLED` env var (default `false`). When
  closed, returns `503` with structured `{error_code: "REGISTRATION_CLOSED",
  detail: "…request access at engramia.dev/request-access…"}`. Existing
  self-serve registration logic is preserved unchanged behind the gate;
  switching to self-serve later is a SOPS env-flip + redeploy.
- **`engramia/api/cloud_auth.py`** — `LoginResponse` extended with
  `must_change_password: bool`. New `POST /auth/change-password`
  Bearer-authed endpoint validates the current password, applies the new
  one (same complexity rules as registration), clears the flag, and
  returns a fresh JWT.
- **`engramia/cli/main.py`** — new `engramia waitlist {list,approve,reject,export}`
  Typer subcommands. `approve` reuses `_create_registration`, sets
  `must_change_password=true`, emails one-time credentials. `reject
  --reason "<text>"` interpolates an admin-supplied message into the
  rejection template. `export [--since <date>]` produces CSV. Existing
  `engramia cloud create-account` extended to set
  `must_change_password=true` for consistency.
- **`engramia/billing/service.py`** — `create_portal_url()` lazy-creates
  the Stripe customer record on first `/billing/portal` visit when no
  `stripe_customer_id` exists yet (manually-onboarded tenants don't go
  through Checkout).
- **`engramia/email/templates.py`** — four new templates:
  `waitlist_ack_email` (2-business-day promise),
  `waitlist_admin_notify_email` (full submission detail + CLI command
  hints), `credentials_email` (one-time password + force-change
  instruction), `waitlist_rejection_email` (admin-drafted reason
  interpolated into a polite frame).
- **`engramia/api/cloud_auth.py`** — `DELETE /me` (GDPR Art.17) extended
  to wipe matching `waitlist_requests` rows by email + tenant_id match,
  so customer-requested deletion truly purges all PII.
- **`engramia/api/audit.py`** — `AuditEvent` enum gains
  `WAITLIST_SUBMITTED`, `WAITLIST_APPROVED`, `WAITLIST_REJECTED`,
  `FIRST_PASSWORD_CHANGED`, `AUTH_SUCCESS` for the new audit trail.
- **Migration `029_waitlist_and_force_password_change`** — new
  `waitlist_requests` table (id, email, name, plan_interest, country,
  use_case, company_name, referral_source, status, rejection_reason,
  tenant_id FK, timestamps) + new boolean
  `cloud_users.must_change_password` column (`NOT NULL DEFAULT FALSE`).
  Non-destructive: existing self-registered users keep `false`. Indexes
  on `(status, created_at)` for admin queue queries and `(email)` for
  the GDPR Art.17 cleanup.

Tests: `tests/test_api/test_waitlist.py` (24 cases) +
`tests/test_cloud_auth_force_change_password.py` (16 cases). Pre-existing
`tests/test_cloud_auth.py` adapted: autouse fixture sets
`ENGRAMIA_REGISTRATION_ENABLED=true` so legacy register/login tests
exercise the open flow; login mock tuples extended for the new column.

### Added — Audit-driven test additions (2026-04-30 audit gaps)

A test audit identified high-leverage gaps in production-critical paths.
This release closes the most important ones — 145 new test cases across
seven test files:

- **`tests/test_cli/test_cleanup.py`** (18 cases, testcontainers Postgres) —
  `cleanup unverified-users` (reminder + delete windows, dry-run no-op,
  OAuth/verified guards, idempotent re-run) + `cleanup deleted-accounts`
  (grace-period hard-delete, custom flag, idempotent).
- **`tests/test_cloud_auth_oauth.py`** (23 cases) — Google tokeninfo
  audience validation (5 cases), Apple `NotImplementedError`,
  `/auth/oauth` route (first-time login, returning user, email
  lowercasing), `/auth/logout` JWT blocklist (8 cases incl. idempotent
  double-call, garbage token, blocklist internals).
- **`tests/test_governance_backup.py`** (24 cases) — `BackupExporter`
  class-level guarantees: excluded tables (`tenant_credentials`,
  `audit_log`, `billing_subscriptions`, `api_keys`, `cloud_users`)
  NEVER appear in any SELECT; every query binds `:tid`; envelope is
  header → rows → footer; NDJSON terminators; error envelope on
  per-table failure; datetime/Decimal serialised via `default=str`.
- **`tests/test_api/test_dsr_routes.py`** (31 cases) — POST/GET/PATCH
  `/v1/governance/dsr` integration via FastAPI TestClient: RBAC matrix,
  tenant isolation (cross-tenant 403 not 404 to prevent enumeration),
  Pydantic validation, status state machine.
- **`tests/test_billing/test_webhook_sequence.py`** (8 cases,
  testcontainers Postgres) — drives `BillingService` through the ordered
  Stripe sequence (checkout → subscription.created → invoice.paid →
  payment_failed → recovery → subscription.deleted) against real
  Postgres + alembic head. Covers out-of-order delivery + idempotent
  replay.
- **`tests/test_email_sender.py`** (15 cases) — STARTTLS / SMTPS /
  plaintext branching, recipient-rejected propagation, EmailMessage
  envelope.
- **`tests/test_email_templates.py`** — 27 new cases covering all seven
  templates' HTML escaping (XSS guard for `recipient_name`,
  `verify_url`, `confirm_url`), interpolation, and template-specific
  structure.

CI Test (Python 3.12 + 3.13) and Full Test Suite (Postgres + alembic
head) both green after this release.

### Fixed — Pre-existing CI breakage on `main` (8+ commits red)

The Core CI workflow had been red on `main` for at least eight commits
prior to this release, blocking validation of incoming work. Fixed:

- **`engramia/credentials/crypto.py:102`** — `base64.binascii.Error` is
  not a real attribute. Switched to `import binascii` + `except
  binascii.Error`. Mypy + runtime were both broken on Python 3.13.
- **`engramia/mcp/tier_gate.py:60`** — `await cb()` on `object`-typed
  attribute. Added `# type: ignore[misc,operator]` (runtime invariant
  enforced by the limiter).
- **`engramia/credentials/store.py:146`** — `bytes | None` assignment to
  a `bytes` field after a non-None check. Extracted to a narrowed local
  variable.
- **`engramia/credentials/resolver.py:97`** — `object → CredentialBackend`
  assignment after a `hasattr` check. Added `# type: ignore[index,assignment]`.
- **`engramia/billing/service.py:91-103`** — `_stripe_lib: Any = None`
  followed by `import stripe as _stripe_lib` triggered a mypy
  redefinition error. Rewrote: import as `_stripe_module`, then assign
  `_stripe_lib: Any = _stripe_module`; the ImportError branch sets
  `_stripe_lib = None`.
- **`engramia/credentials/store.py.patch`** — JSONB columns
  (`role_models`, `failover_chain`, `role_cost_limits`) sent as raw
  Python dict/list to psycopg2 raised `can't adapt type 'dict'`.
  Switched to `json.dumps()` + `CAST(:param AS jsonb)` (the
  `:param::jsonb` shorthand collides with SQLAlchemy's `:param`
  placeholder parsing).
- **`engramia/providers/_ollama_native.py:180`** — SIM103 ruff lint:
  `if X: return True; return False` → `return X`.
- **16 files reformatted** by `ruff format` — pure formatting, no
  behaviour change.
- **`.github/workflows/ci.yml`** — `Test (Python 3.x)` and `Full Test
  Suite` jobs now install `cloud-auth + billing + mcp` extras so ~20
  test modules don't fail collection with `ModuleNotFoundError` before
  pytest runs anything.
- **`engramia/api/audit.py`** — added `AUTH_SUCCESS` to the `AuditEvent`
  enum (referenced by the new change-password handler and existing
  call sites).

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

# Engramia — Roadmap

## Vision

Standalone Python library + REST API for **reusable agent execution memory, evaluation, and improvement**.
Gives any agent framework the ability to learn from every run — remember what works, forget what does not,
reuse proven solutions, and improve over time through quality-weighted recall.

---

## Competitive Advantage (summary)

| Area | Engramia | LangChain/LangSmith | CrewAI |
|------|----------|---------------------|--------|
| Closed-loop learning | ✅ aging, feedback, evolution | ❌ tracing only | ❌ |
| Agent reuse | ✅ semantic + eval-weighted + contracts | ❌ manual | ❌ manual |
| Multi-evaluator scoring | ✅ N runs, median, variance | ❌ | ❌ |
| Framework-agnostic | ✅ library + REST + SDK plugins | ❌ LangChain-only | ❌ CrewAI-only |

Not targeting: orchestration, sandboxing, marketplace (until PMF).

---

## Monetization Model

| Tier | Contents | Price |
|------|----------|-------|
| Free (non-commercial) | Core library, JSON storage, CLI | Free |
| Cloud | Hosted API, PostgreSQL + pgvector, dashboard, team sharing | $49–199/month |
| Enterprise (on-prem) | Self-hosted license, SSO, audit log, SLA | Custom |

---

## Completed Phases

See [CHANGELOG.md](CHANGELOG.md) for detailed release notes per phase.

| Phase | Version | Summary |
|-------|---------|---------|
| 0–1 | v0.1.0 | Core library — learn, recall, evaluate, compose, feedback, aging, metrics |
| 2 | v0.2.0 | REST API (14 endpoints), PostgreSQL + pgvector, Docker |
| 3 | v0.3.0 | LangChain + webhook SDK, Anthropic + local embeddings, prompt evolution, failure clustering, skill registry |
| 4 | v0.4.0 | CLI (Typer), custom exceptions, export/import |
| 4.5 | v0.5.0 | OWASP ASVS Level 2/3 security hardening |
| 4.6 | v0.5.1–0.5.3 | Branding, CI/CD, docs, Hetzner deploy, CrewAI + MCP, Agent Factory V2, EngramiaBridge SDK, recall quality suite |
| 5.0 | v0.5.3+ | Positioning reset — README, feature labels, ICP, naming cleanup |
| 5.1 + 5.2 | v0.5.4 | Multi-tenancy (scope isolation via contextvars), RBAC (4 roles), DB API key management, quota enforcement, migration 003 — 462 tests / 78.51% |
| 5.4 | v0.5.5 | Async job queue (`SKIP LOCKED`), `JobWorker`, dual-mode `Prefer: respond-async`, provider timeouts, migration 004 — 537 tests / 77.81% |
| 5.5 | v0.5.6 | Observability — `engramia/telemetry/`, OTel `@traced`, Prometheus `/metrics`, JSON logging, `GET /v1/health/deep`, request_id propagation, migration 005 — 560 tests / 77.76% |
| 5.6 | v0.5.7 | Data governance — `engramia/governance/`, PII redaction, retention policies, scoped delete/export (GDPR Art. 17/20), provenance metadata, lifecycle jobs, migration 006 — 656 tests / 78.70% |
| 5.7 | v0.5.8 | ROI analytics — `engramia/analytics/`, `ROICollector` (fire-and-ignore in learn/recall), `ROIAggregator` (hourly/daily/weekly rollups, composite ROI score), Analytics REST API (`/v1/analytics/rollup`, `/v1/analytics/events`), `analytics:read/rollup` permissions — 629 tests / 77.18% |
| 5.3 | v0.5.9 | Admin dashboard — Next.js 15 static export (10 pages), typed API client, RBAC sidebar, TanStack Query, Recharts charts, Tailwind dark theme; FastAPI `/dashboard` static mount |
| 5.8 | v0.6.0 | Architecture cleanup + test coverage — service decomposition (`Memory` → thin facade, 4 service classes), PostgreSQL integration tests (30 tests, `testcontainers`), LLM error path tests, concurrent JSONStorage tests, analytics unit tests (34 tests), narrowed `except Exception`, `ENGRAMIA_ENVIRONMENT` dev-mode guard — 726 tests / 80.29% |
| 5.9 | v0.6.1 | Enterprise Trust Pack — OIDC SSO (`engramia[oidc]`, PyJWT + JWKS), security architecture doc, data handling doc, production hardening guide, backup/restore playbook (RTO 4h/RPO 24h), incident response runbook, SOC 2 control mapping |
| audit fixes | v0.6.2–0.6.3 | Resolved all P1–P2 findings from 2026-04-02 audit (auth fallback, cross-tenant feedback leak, analytics race, test coverage, job durability, embedding metadata, RBAC in env mode) |
| 4.6 | v0.6.4 | Benchmark suite — reproducible recall quality validation; 12 realistic agent domains, 254 tasks, auto-calibrated thresholds; full_library 98.8% success rate validates Agent Factory V2 93% claim |

---

## Audit Findings (2026-03-28, score 78/100) — all resolved

| P | Area | Finding | Status |
|---|------|---------|--------|
| ~~P0~~ | ~~Architecture~~ | ~~No tenant/scope isolation~~ | ✅ 5.1 |
| ~~P0~~ | ~~Security~~ | ~~No RBAC~~ | ✅ 5.2 |
| ~~P0~~ | ~~Security~~ | ~~No quota — DoS via unlimited patterns~~ | ✅ 5.2 |
| ~~P0~~ | ~~Product~~ | ~~No admin UI — remains "just a library"~~ | ✅ 5.3 |
| ~~P1~~ | ~~Reliability~~ | ~~No async jobs — long ops block API~~ | ✅ 5.4 |
| ~~P1~~ | ~~Observability~~ | ~~No telemetry — blind in production~~ | ✅ 5.5 |
| ~~P1~~ | ~~Positioning~~ | ~~README overclaims~~ | ✅ 5.0 |
| ~~P1~~ | ~~Privacy~~ | ~~No data governance / retention~~ | ✅ 5.6 |
| ~~P1~~ | ~~Commercial~~ | ~~No ROI proof layer~~ | ✅ 5.7 (data) + ✅ 5.3 (UI) |
| ~~P1~~ | ~~Tests~~ | ~~PostgreSQL 0% coverage; LLM error paths untested~~ | ✅ 5.8 |
| ~~P1~~ | ~~Production~~ | ~~Bare `except Exception` in memory.py, eval_feedback.py~~ | ✅ 5.8 |
| ~~P2~~ | ~~Backend~~ | ~~`Memory` class → god object~~ | ✅ 5.8 |
| ~~P2~~ | ~~Security~~ | ~~Dev mode dangerous if misconfigured~~ | ✅ 5.8 |
| ~~P2~~ | ~~DB~~ | ~~No data lifecycle~~ | ✅ 5.6 |
| ~~P3~~ | ~~Branding~~ | ~~Naming drift~~ | ✅ 5.0 |

---

## Audit Findings (2026-04-02, score 83/100)

| P | Area | Finding | Status |
|---|------|---------|--------|
| ~~P1~~ | ~~Security~~ | ~~Unauthenticated fallback still active when `ENGRAMIA_API_KEYS` empty in env auth mode — `auth.py:82-85, 223-232`~~ | ✅ v0.6.2 |
| ~~P1~~ | ~~Multi-tenancy~~ | ~~`test_feedback_not_visible_across_tenants` fails — cross-tenant feedback leak in `EvalFeedbackStore`~~ | ✅ v0.6.2 |
| ~~P1~~ | ~~Analytics~~ | ~~ROI `_append()` is read-modify-write race — concurrent writes silently lose events (`collector.py:131-135`)~~ | ✅ v0.6.2 |
| ~~P1~~ | ~~Tests~~ | ~~43 failures + 60 errors in snapshot; optional deps (`sentence-transformers`) not gated with pytest markers~~ | ✅ v0.6.2 — `pytest.importorskip` in recall_quality + test_features conftest |
| ~~P2~~ | ~~Tests~~ | ~~`postgres.py` 21% coverage; `api/keys.py` 63%; `jobs/service.py` 64%; `api/analytics.py` 35%~~ | ✅ v0.6.3 — `test_postgres_storage_unit.py` (22 tests), `test_jobs_service.py` (36 tests) |
| ~~P2~~ | ~~Tests~~ | ~~`oidc.py`, `prom_metrics.py`, `mcp/server.py`, `telemetry/logging.py` all at 0%~~ | ✅ v0.6.2 — tests for prom_metrics + telemetry/logging; oidc + mcp marked experimental |
| ~~P2~~ | ~~Security~~ | ~~`.gitignore` missing `*.pem`, `*.key`, `*.crt`, `*.p12`, `credentials*`~~ | ✅ v0.6.2 |
| ~~P2~~ | ~~Async~~ | ~~Async job layer is not durable (no crash recovery, no backpressure) — `jobs/service.py`~~ | ✅ v0.6.3 — `_recover_orphaned_jobs()` při startu (DB mód); in-memory best-effort warning |
| ~~P2~~ | ~~Embedding~~ | ~~No embedding model/provider/version metadata stored — breaks reindex after model change~~ | ✅ v0.6.3 — `Memory._check_embedding_config()` + `engramia reindex` CLI |
| ~~P2~~ | ~~RBAC~~ | ~~In env/dev mode RBAC is a no-op — dangerous for any serious deployment~~ | ✅ v0.6.3 — `ENGRAMIA_ENV_AUTH_ROLE` (default: owner, backward compat), `auth_context` nastaven v env módu |

---

## Open Work

### Pre-launch (Phase 4.6 — ongoing)

#### Legal

- [ ] `LICENSE.txt` structural fix — reorder per BSL 1.1 boilerplate (mariadb.com/bsl11)
- [ ] Czech attorney review: ToS (B2C/GDPR), Privacy Policy, Cookie Policy, DPA (Art. 28)
- [ ] EUIPO trademark registration (class 42)
- [ ] Fill placeholders — pricing URL in ToS/Privacy/Cookie/DPA
- [ ] Privacy Policy: add encryption at rest (§7), anonymization (§4.3)
- [ ] DPA: add sub-processor list (§4.4) + public `/legal/subprocessors` page
- [ ] Verify trade license active for invoicing

#### Launch

- [ ] Anthropic API key on VM (for Anthropic provider in production)
- [ ] Final README review
- [ ] Switch repo to public
- [ ] PyPI environment protection → release trigger in `publish.yml`
- [ ] PyPI release (`pip install engramia`)
- [ ] Docker image public (`ghcr.io/engramia/engramia:latest`)
- [ ] Launch blog post — "How self-learning agents achieve a 93% success rate"

#### Agent Factory V2 — Phase 3

- [ ] Inject Engramia context into architect prompt (`agents/architect.py`)
- [ ] Inject Engramia feedback into coder prompt
- [ ] Benchmark: success rate before/after Brain integration (baseline: 8.6→8.8)

#### Deferred

- [ ] **Model routing** module — data-driven model selection per role/task-type

---

### Phase 6 — Commercial Platform

- [ ] Hosted SKU definition: OSS Core / Managed API / Team Plan / Enterprise Self-Hosted
- [ ] Stripe billing integration (Team/Cloud tier)
- [ ] Commercial licensing page — "Can I use this for X?" matrix
- [ ] CLA / contributor policy (before accepting external PRs)
- [ ] Dependency license inventory (transitive audit)
- [ ] Webhook notifications — Slack/Discord for events
- [ ] YAML/TOML config file as optional override
- [ ] Deep framework integrations — LangChain, CrewAI, OpenAI Agents SDK adapters

### Phase 7 — Memory Architecture

- [ ] Knowledge Graph — entity/relationship layer on top of patterns
- [ ] Memory taxonomy — explicit episodic / semantic / procedural separation
- [ ] Memory compression — summarize old patterns instead of only decaying
- [ ] Multi-agent memory sharing — shared pattern pools with access control

### Phase 8 — Multimodal + Providers

- [ ] Multimodal memory — store references to images/audio/video with text descriptions
- [ ] Voyage AI + Cohere embedding providers
- [ ] Dedicated vector DB (Qdrant/Milvus) as `StorageBackend` for 100k+ patterns

### Phase 9 — Marketplace

- [ ] Community patterns — share success patterns between users
- [ ] Monetization: premium patterns, verified integrations

### Phase 10 — Advanced Learning

- [ ] Reinforcement learning from eval scores
- [ ] Auto-tuning eval prompts (meta-learning)
- [ ] Cross-project knowledge transfer

---

## Success Metrics

| Phase | KPI | Target |
|-------|-----|--------|
| 4.6 | PyPI weekly downloads | tracking starts at launch |
| ~~4.6~~ | ~~Benchmark: success rate improvement~~ | ✅ +93.3 pp vs cold start (5.5% → 98.8%) |
| ~~5.1~~ | ~~Tenant isolation~~ | ✅ Cross-tenant leak = 0 |
| ~~5.2~~ | ~~RBAC~~ | ✅ Role-based tests PASS |
| ~~5.3~~ | ~~Admin UI~~ | ✅ 10 pages, 35 files, static export builds |
| ~~5.4~~ | ~~Async jobs~~ | ✅ Long ops return job_id, no timeout |
| ~~5.5~~ | ~~Observability~~ | ✅ OTel traces; /v1/health/deep; /metrics |
| ~~5.6~~ | ~~Data governance~~ | ✅ Retention + scoped delete + PII redaction + NDJSON export |
| ~~5.7~~ | ~~ROI analytics~~ | ✅ ROI events collected; rollup API live |
| ~~5.8~~ | ~~Architecture cleanup~~ | ✅ Service decomposition + 726 tests / 80.29% coverage |
| ~~5.9~~ | ~~Enterprise trust~~ | ✅ Security architecture + data handling + IR playbook + SOC 2 mapping + OIDC SSO |
| 7 | Memory architecture | Knowledge graph + taxonomy |
| 8 | Multimodal | ≥1 non-text modality supported |

# Engramia — Roadmap

## Vision

Build a standalone Python library + REST API for **reusable agent execution memory, evaluation, and improvement**.
A product that gives any agent framework (LangChain, CrewAI, AutoGPT, custom)
the ability to learn from every run — remember what works, forget what does not,
reuse proven solutions, and improve over time through quality-weighted recall.

---

## Competitive Analysis

### Where We Have an Advantage

| Area | Us (Engramia) | LangChain/LangSmith | CrewAI | AutoGPT |
|--------|-------------------|---------------------|--------|---------|
| **Closed-loop learning** | ✅ Pattern aging, feedback injection, prompt evolution | ❌ Tracing only (observability, not learning) | ❌ None | ❌ None |
| **Agent reuse** | ✅ Semantic search + eval-weighted matching + contract validation | ❌ Manual | ❌ Manual | ❌ None |
| **Pipeline composition** | ✅ Automatic with contract validation (reads/writes) | ⚠️ LCEL chains (manual) | ⚠️ Crew config (manual) | ❌ |
| **Multi-evaluator scoring** | ✅ N runs, median, variance detection, adversarial check | ❌ | ❌ | ❌ |
| **Model routing** | ✅ Empirical — data-driven, per-role, per-task-type | ❌ | ❌ | ❌ |
| **Pattern aging** | ✅ Time-decay, old patterns naturally fade out | ❌ | ❌ | ❌ |
| **Framework-agnostic** | ✅ Library, REST API, SDK plugins | ❌ LangChain-only | ❌ CrewAI-only | ❌ |

### Where We Do Not Have an Advantage (and are not trying to)

- **Agent orchestration** — that is what LangChain/CrewAI do, we are the memory layer beneath them
- **Sandboxing** — remains in Agent Factory (or another host)
- **UI/Dashboard** — required for commercial readiness (Phase 5)
- **Marketplace** — only after PMF is validated

---

## Monetization

### Model: Open-core + SaaS

| Tier | Contents | Price |
|------|-------|------|
| **Free (non-commercial)** | Core library (patterns, eval, reuse, aging). JSON storage. CLI. Evaluation, research, personal projects. | Free |
| **Cloud** | Hosted REST API, PostgreSQL + pgvector backend, dashboard, team sharing. Commercial usage. | $49–199/month |
| **Enterprise (on-prem)** | Self-hosted license, SSO, audit log, SLA, custom integrations, dedicated support | Custom |

### Revenue Drivers

1. **Storage & compute** — Embeddings, multi-eval LLM calls, pgvector search
2. **Team features** — Shared brain instance, RBAC, audit trail
3. **Framework plugins** — Premium integrations (LangChain, CrewAI, Autogen)
4. **Model routing savings** — Brain reduces LLM costs → upsell as "pay less for LLMs, pay us"

### Go-to-Market

1. **Dev-first** — High-quality open-source library, good documentation, pip install
2. **Content** — Blog posts: "How we achieved a 93% success rate with self-learning agents"
3. **Integration** — LangChain/CrewAI plugins as the entry point
4. **Community** — Discord, GitHub Discussions
5. **Enterprise** — Outbound only after PMF is validated on the Cloud tier

---

## Completed Phases (v0.1.0–v0.5.3)

See [CHANGELOG.md](CHANGELOG.md) for detailed release notes.

- **Phase 0–1** (v0.1.0): Core Brain library — learn, recall, evaluate, compose, feedback, aging, metrics
- **Phase 2** (v0.2.0): REST API (FastAPI, 14 endpoints), PostgreSQL + pgvector, Docker
- **Phase 3** (v0.3.0): LangChain + webhook SDK, Anthropic + local embeddings providers, prompt evolution, failure clustering, skill registry
- **Phase 4** (v0.4.0): CLI (Typer), custom exceptions, export/import
- **Phase 4.5** (v0.5.0): OWASP ASVS Level 2/3 security hardening (24 items)
- **Phase 4.6.0–4.6.5** (v0.5.1): Branding, legal, CI/CD, docs, MkDocs, examples, Hetzner deploy
- **Phase 4.6.7–4.6.9** (v0.5.2): CrewAI integration, MCP server, quick fixes
- **Phase 4.6.10–4.6.12** (v0.5.3): Agent Factory V2 integration, EngramiaBridge SDK, recall quality test suite, Postgres bugfixes
- **Phase 5.0** (v0.5.3+): Positioning reset — README rewrite, feature maturity labels, ICP, naming drift cleanup (Brain/agent-brain → Engramia), compose/evolve labeled Experimental
- **Phase 5.1 + 5.2** (v0.5.4): Multi-tenancy (scope isolation via contextvars, JSONStorage + PostgresStorage scope-aware), RBAC (owner/admin/editor/reader roles, permission deps), DB API key management (bootstrap/create/rotate/revoke), auth mode selector (`ENGRAMIA_AUTH_MODE`), TTL key cache, quota enforcement (429), migration 003, 462 tests / 78.51% coverage
- **Phase 5.4** (unreleased): Async job layer — PostgreSQL `SKIP LOCKED` queue, in-process `JobWorker`, dual-mode `Prefer: respond-async` on 6 endpoints, job API (`GET/POST /v1/jobs`), provider timeouts (LLM 30 s, embed 15 s), migration 004, 537 tests / 77.81% coverage
- **Phase 5.5** (unreleased): Observability — `engramia/telemetry/` package, `RequestIDMiddleware` + `TimingMiddleware`, OpenTelemetry `@traced` decorator, Prometheus metrics (`/metrics`), JSON structured logging, `GET /v1/health/deep`, `request_id` propagation through async jobs, migration 005, 560 tests / 77.76% coverage

---

## Audit-Driven Priorities (2026-03-28)

Based on independent commercial audit + technical audit (2026-03-26, score 78/100).
Project status: **Early Commercial Candidate** — usable for pilots, not yet enterprise-ready.

### Open findings

| Priority | Area | Issue | Target |
|----------|------|-------|--------|
| ~~P0~~ | ~~Architecture~~ | ~~No tenant/project/scope isolation — cannot safely sell as shared service~~ | ✅ Phase 5.1 done |
| ~~P0~~ | ~~Security~~ | ~~No RBAC/permission model — no governance, no team use~~ | ✅ Phase 5.2 done |
| P0 | Product | No admin/product UI — remains "just a library" | Phase 5.3 |
| ~~P0~~ | ~~Security~~ | ~~No pattern count quota — DoS via unlimited creation~~ | ✅ Phase 5.2 done |
| ~~P1~~ | ~~Reliability~~ | ~~No async/job processing — long ops block API~~ | ✅ Phase 5.4 done |
| ~~P1~~ | ~~Observability~~ | ~~No telemetry/tracing — blind in production~~ | ✅ Phase 5.5 done |
| ~~P1~~ | ~~Positioning~~ | ~~README overclaims vs reality — trust erosion~~ | ✅ Phase 5.0 done |
| ~~P1~~ | ~~Privacy~~ | ~~No data governance/retention/redaction~~ | ✅ Phase 5.6 done |
| P1 | Commercial | No ROI proof layer — hard to sell vs "build in-house" | Phase 5.7 (data) + 5.3 (API/UI) |
| P1 | Tests | PostgreSQL 0% coverage; LLM error paths untested | Phase 5.8 |
| P1 | Production | Bare `except Exception` in brain.py, eval_feedback.py | Phase 5.8 |
| P2 | Backend | Memory class growing toward god object | Phase 5.8 |
| ~~P2~~ | ~~DB~~ | ~~No schema/data lifecycle (retention, compaction, reindex)~~ | ✅ Phase 5.6 done |
| P2 | Security | Dev mode without auth dangerous if misconfigured | Phase 5.8 |
| ~~P3~~ | ~~Branding~~ | ~~Naming drift (Brain/Engramia/agent-brain)~~ | ✅ Phase 5.0 done |
| ~~P3~~ | ~~Features~~ | ~~compose/evolve position as demo, not mission-critical~~ | ✅ Phase 5.0 done |

---

## Open Work

### Pre-launch remaining (Phase 4.6)

#### Legal Review (Phase 4.6.2.1)

- [ ] **LICENSE.txt structural fix** — reorder parameters (Licensor → Licensed Work → Additional Use Grant → Change Date → Change License); replace custom Terms/Disclaimer sections with official BSL 1.1 boilerplate from mariadb.com/bsl11 (Covenant #4 forbids modification)
- [ ] **Legal review of ToS** — Czech attorney: B2C consumer clauses, GDPR compliance, arbitration clause
- [ ] **Legal review of Privacy Policy** — GDPR compliance, retention, international transfers
- [ ] **Legal review of Cookie Policy** — ePrivacy compliance, consent mechanism
- [ ] **Legal review of DPA template** — GDPR Art. 28 compliance, sub-processor flow
- [ ] **Legal review of LICENSE.txt** — verify BSL 1.1 parameters, enforceability
- [ ] **Trademark** — EUIPO registration (class 42)
- [ ] **EU AI Act** — monitor regulatory updates, delegated acts
- [ ] **Verify trade license** — active business registration for invoicing
- [ ] **Fill placeholders** — pricing URL in ToS, Privacy Policy, Cookie Policy, DPA
- [ ] **Privacy Policy — encryption at rest** — add mention in section 7 (Data Security)
- [ ] **Privacy Policy — data anonymization** — add description in section 4.3
- [ ] **DPA — add sub-processor list** — fill in hosting provider + payment processor (Sec. 4.4)
- [ ] **Sub-processor registry page** (`/legal/subprocessors`) — public page referenced in DPA

#### Launch (Phase 4.6.6)

- [ ] **Anthropic API key** — optional, for Anthropic provider on VM
- [ ] **Benchmark suite** — reproduce Agent Factory V2 results (93% success rate)
- [ ] **Final README review** — verify everything is current
- [ ] **Switch repo to public**
- [ ] **PyPI environment protection** — Settings → Environments → `pypi` → Required reviewers; re-enable release trigger in publish.yml
- [ ] **PyPI release** — `pip install engramia`
- [ ] **Docker image** — `ghcr.io/engramia/engramia:latest` (public after repo goes public)
- [ ] **Launch blog post** — "How self-learning agents achieve a 93% success rate"

#### Agent Factory V2 — Phase 3 (full integration)

- [ ] Inject Engramia context into the architect prompt (`agents/architect.py`)
- [ ] Inject Engramia feedback into the coder prompt (merge with local feedback DB)
- [ ] Benchmark: compare success rate/eval score before and after Brain integration (baseline: 8.6→8.8 observed in Phase 2)

#### Deferred from earlier phases

- [ ] **Model routing** module — data-driven model selection per role/task-type (originally Phase 2.5)

---

### Phase 5: Production Readiness + Commercial Foundation
> Goal: Transform from "solid MVP library" to "commercially credible pilot-ready product".
> Timeline: 30/60/90 day plan based on independent audit (2026-03-28).

#### Phase 5.0: Positioning + Messaging Reset 

- [x] **Rewrite README positioning** — from "self-learning brain" to "reusable agent execution memory + evaluation infrastructure"
- [x] **Feature categorization** — explicitly label features as: Stable, Experimental, Roadmap
- [x] **Clean naming drift** — audit all references to "Brain", "agent-brain", "Remanence"; standardize to "Engramia"
- [x] **Position compose/evolve as assistive** — not core guarantees, label as experimental/beta
- [x] **Define ICP** — AI platform teams, agent builders, automation studios, small-mid AI product teams

#### Phase 5.1: Tenant + Scope Isolation ✅ done (v0.5.4)
> P0 commercial blocker.

- [x] **Extend storage model** — `tenant_id`, `project_id` columns on `memory_data` + `memory_embeddings`; composite B-tree indexes; migration 003
- [x] **Scope-aware API** — all storage reads/writes filtered by scope via `contextvars`; `engramia/_context.py`
- [x] **Scope-aware SDK** — scope propagates automatically through FastAPI async → sync (anyio context copy)
- [x] **Scope-aware export/import** — JSONStorage and PostgresStorage enforce scope boundaries
- [x] **Migration** — `003_scope_rbac` Alembic migration; server default `'default'` for backward compat
- [x] **Tests** — 8 JSONStorage cross-scope isolation tests + 4 contextvar tests in `test_scope_rbac.py`

#### Phase 5.2: RBAC + Auth Model ✅ done (v0.5.4)
> P0 security/commercial blocker.

- [x] **Role model** — Owner > Admin > Editor > Reader; `PERMISSIONS` dict with explicit permission sets; strict subset hierarchy
- [x] **Project-scoped API keys** — keys in `api_keys` table; SHA-256 hash; `engramia_sk_<43 base64url>` format; tied to tenant + project
- [x] **Permission enforcement** — `require_permission("perm")` FastAPI dependency on all routes; owner wildcard `"*"`
- [x] **Key management** — `POST /v1/keys/bootstrap`, `POST /v1/keys`, `GET /v1/keys`, `DELETE /v1/keys/{id}`, `POST /v1/keys/{id}/rotate`
- [x] **Actor identity in audit logs** — `log_db_event()` records key_id + action + resource on all key ops; `KEY_CREATED/REVOKED/ROTATED/QUOTA_EXCEEDED` audit events
- [x] **Pattern count quota** — `max_patterns` per key; HTTP 429 with `quota_exceeded` detail; enforced in `/learn` and `/import`
- [x] **Tests** — RBAC permission tests, quota tests, key CRUD tests, DB auth cache tests in `test_scope_rbac.py`, `test_auth_db.py`, `test_keys.py`

#### Phase 5.3: Admin Dashboard / Product UI
> P0 product blocker.

- [ ] **Technology choice** — lightweight React/Next.js or similar
- [ ] **Core views**: projects, patterns/memories, recall history, eval history, metrics dashboard, provider settings
- [ ] **API key management UI** — create, rotate, revoke keys
- [ ] **Pattern explorer** — search, filter, view details, manual delete
- [ ] **Eval history** — scores over time, variance alerts
- [ ] **Analytics API** — `GET /v1/analytics` endpoints (reuse rate, success lift, cost savings, top patterns)
- [ ] **Dashboard integration** — ROI metrics visible in admin UI (charts, trends, leaderboard)
- [ ] **Deploy** — bundled with API or separate static site

#### Phase 5.6: Data Governance + Privacy ✅

- [x] **Retention policies** — configurable TTL per project, auto-cleanup
- [x] **Data classification flags** — mark patterns as public/internal/confidential
- [x] **PII/secrets redaction hooks** — optional pre-storage redaction pipeline
- [x] **Scoped deletion** — delete all data for a tenant/project (GDPR Art. 17)
- [x] **Scoped export** — export all data for a tenant/project (GDPR Art. 20)
- [x] **Data provenance metadata** — source, timestamp, run_id, author on all patterns
- [x] **Schema/data lifecycle** — compaction, dedup, index maintenance jobs

#### Phase 5.7: ROI Analytics + Evidence Layer
> Backend data collection + aggregation that feeds the Analytics API (Phase 5.3).

- [ ] **Reuse rate tracking** — % of tasks that reuse existing patterns (time-series, per-project)
- [ ] **Success lift metrics** — success rate improvement with vs without Engramia context
- [ ] **Token/cost savings proxy** — estimated tokens/iterations saved via reuse
- [ ] **Top reused patterns** — most valuable patterns leaderboard

#### Phase 5.8: Architecture Cleanup (Ongoing)

- [ ] **Service decomposition** — extract LearningService, RecallService, EvaluationService, CompositionService
- [ ] **Memory as thin facade** — delegates to services, keeps public API stable
- [ ] **Fix broad exception handling** — replace bare `except Exception` with specific exceptions (brain.py, eval_feedback.py)
- [ ] **Dev mode safety** — require explicit `--unsafe` flag or `ENGRAMIA_ALLOW_NO_AUTH=true`
- [ ] **Postgres test coverage** — add CRUD + vector search tests (with testcontainers or similar)
- [ ] **LLM error path tests** — mock provider failures, malformed responses, timeouts
- [ ] **Concurrent JSONStorage tests** — ThreadPoolExecutor test proving thread-safety claims

#### Phase 5.9: Enterprise Trust Pack

- [ ] **Security architecture document** — system overview, trust boundaries, data flow
- [ ] **Data handling document** — what data is stored, how, where, retention
- [ ] **Deployment hardening guide** — production checklist beyond Docker basics
- [ ] **Backup/restore playbook** — automated backups, defined RTO/RPO targets
- [ ] **Incident response playbook** — IR process, contact points, escalation
- [ ] **SSO/OIDC integration** — optional enterprise auth
- [ ] **SOC 2 controls** — implement controls without formal certification

---

### Phase 6: Commercial Platform

- [ ] **Hosted/managed offering** — define SKUs: OSS Core, Managed API, Team Plan, Enterprise Self-Hosted
- [ ] **Billing integration** — Stripe or similar for Team/Cloud tier
- [ ] **Commercial licensing page** — "Can I use this for X?" matrix
- [ ] **Contributor policy / CLA** — if accepting external PRs
- [ ] **Dependency license inventory** — full audit of transitive dependencies
- [ ] **Webhook notifications** — Slack, Discord integration for events
- [ ] **Config file** (YAML/TOML) as optional override
- [ ] **Deep framework integrations** — invest heavily in LangChain, CrewAI, OpenAI Agents adapters

### Phase 7: Memory Architecture

- [ ] **Knowledge Graph** — entity/relationship layer on top of patterns
- [ ] **Memory taxonomy** — explicit separation of episodic, semantic, procedural memory
- [ ] **Memory compression / summarization** — summarize old patterns instead of only decaying
- [ ] **Multi-agent memory sharing** — shared pattern pools with access control
- [ ] Research topic: graph DB (Neo4j/ArangoDB) for agent → skill → task relationships

### Phase 8: Multimodal + Providers

- [ ] **Multimodal memory** — store references to images/audio/video with text descriptions
- [ ] Voyage AI embedding provider
- [ ] Cohere embeddings
- [ ] Dedicated vector DB (Qdrant/Milvus) as StorageBackend — if scale exceeds 100k+ patterns

### Phase 9: Marketplace

- [ ] Share success patterns between users
- [ ] "Community patterns" — best practices for common task types
- [ ] Monetization: premium patterns, verified integrations

### Phase 10: Advanced Learning

- [ ] Reinforcement learning from eval scores
- [ ] Auto-tuning eval prompts (meta-learning)
- [ ] Cross-project knowledge transfer

---

## Success Metrics

| Phase | KPI | Target |
|------|-----|--------|
| 4.6 | PyPI weekly downloads | tracking starts |
| 4.6 | Benchmark: success rate improvement | ≥15% vs baseline without Brain |
| 5.0 | Positioning reset | README reflects reality |
| ~~5.1~~ | ~~Tenant isolation~~ | ✅ Cross-tenant data leak = 0 |
| ~~5.2~~ | ~~RBAC~~ | ✅ Role-based access tests PASS |
| 5.3 | Admin UI | Functional dashboard deployed |
| ~~5.4~~ | ~~Async jobs~~ | ✅ Long ops return job ID, no API timeout |
| ~~5.5~~ | ~~Observability~~ | ✅ Request traces visible in OTel collector; /v1/health/deep; Prometheus /metrics |
| ~~5.6~~ | ~~Data governance~~ | ✅ Retention + scoped delete + PII redaction + NDJSON export + provenance metadata |
| 5.7 | ROI analytics | Reuse rate + success lift data collected; exposed via 5.3 Analytics API |
| 5.9 | Enterprise trust | Security architecture doc complete |
| 7 | Memory architecture | Knowledge graph + taxonomy + compression |
| 8 | Multimodal | ≥1 non-text modality supported |

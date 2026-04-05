# Engramia Security Audit — 2026-04-05

> **Scope:** Engramia v0.6.5 (agent-brain).
> **Auditor:** Internal — based on full source review of `engramia/api/auth.py`, `docker-compose.prod.yml`, `.github/workflows/ci.yml`, `.github/workflows/docker.yml`, `docs/security-architecture.md`, `docs/soc2-controls.md`, `docs/data-handling.md`, `docs/security.md`, `docs/production-hardening.md`.
> **Classification:** Internal — share with enterprise prospects under NDA.

---

## Executive Summary

Engramia has a meaningfully strong security foundation for a pre-Series-A SaaS product: multi-mode authentication with timing-safe comparisons, four-role RBAC, cryptographic tenant isolation, TLS enforced by Caddy, structured audit logging, GDPR erasure/export endpoints, and automated vulnerability scanning in CI. The product is ready for B2B pilots and can credibly answer most enterprise security questionnaires.

The primary gaps fall into three buckets: (1) **operational controls not enforced by config** (Docker hardening options exist in docs but are absent from `docker-compose.prod.yml`), (2) **distributed-system risks** (in-memory rate limiter, per-process OIDC JWKS cache), and (3) **paper trail gaps** (no RoPA, no formal DPAs, no customer-facing privacy notice, no penetration test record). None are blocking for private beta; all are blocking for enterprise sales or SOC 2 Type II.

Traffic light status per standard:

| Standard | Status | Score |
|---|---|---|
| GDPR | 🟡 Partial | 6/10 |
| OWASP Top 10 (2021) | 🟡 Partial | 7/10 |
| OWASP API Security Top 10 (2023) | 🟢 Good | 8/10 |
| SOC 2 TSC | 🟡 Partial | 6/10 |
| ISO 27001:2022 | 🟡 Partial | 5/10 |
| CIS Controls v8 | 🟡 Partial | 6/10 |
| PCI DSS (Stripe scope) | 🟢 Low scope | 9/10 |

---

## 1. GDPR Compliance (Critical for EU SaaS)

Engramia is hosted in **Hetzner DE (FSN1, Frankfurt)** and processes data submitted by calling agent systems. Depending on whether those agent systems process end-user personal data, Engramia may act as a **data processor** (most common) or a **data controller** for operator data (API key holders).

### Article-by-Article Assessment

| Article | Topic | Status | Gap |
|---|---|---|---|
| Art. 5 | Data minimisation & purpose limitation | 🟢 Compliant | Only fields explicitly provided are stored; classification labels (PUBLIC/INTERNAL/CONFIDENTIAL) in place. |
| Art. 6 | Lawful basis | 🟡 Partial | No documented lawful basis mapping; for SaaS, contractual necessity (b) or legitimate interest (f) must be stated in ToS. |
| Art. 13/14 | Transparency / privacy notice | 🔴 Gap | No privacy notice or cookie policy exists. Required before public launch. |
| Art. 17 | Right to erasure | 🟢 Compliant | `DELETE /v1/governance/projects/{id}` cascades to patterns, embeddings, audit_log detail scrub, key revocation. Evidence: `data-handling.md` line 86. |
| Art. 20 | Right to portability | 🟢 Compliant | `GET /v1/governance/export` returns NDJSON with all fields. Re-import supported. |
| Art. 22 | Automated decision-making | 🟢 N/A | Eval scores are quality metrics for agent systems, not decisions affecting data subjects. |
| Art. 25 | Privacy by design | 🟡 Partial | PII redaction pipeline (`RedactionPipeline`) is **opt-in via code**, not on by default. `ENGRAMIA_REDACTION=false` can disable it. Should default-on in production. |
| Art. 28 | DPA with processors | 🟡 Partial | Sub-processors documented (OpenAI, Anthropic, Hetzner) in `data-handling.md`. OpenAI and Anthropic both provide DPAs, but Engramia has not documented that they are **signed and in effect**. No customer-facing DPA template exists. |
| Art. 30 | Records of Processing Activities (RoPA) | 🔴 Gap | No RoPA document. Required for controllers and processors. |
| Art. 32 | Security measures | 🟡 Partial | TLS, hashed keys, RBAC in place. Encryption at rest is **recommended** (Hetzner disk encryption) but not enforced or verified at application layer. |
| Art. 33 | Breach notification (72h to DPA) | 🟡 Partial | `production-hardening.md` mentions the 72-hour duty. No documented incident classification thresholds or DPA contact list. |
| Art. 35 | DPIA | 🟡 Partial | No formal Data Protection Impact Assessment. Needed if processing large volumes of potentially sensitive agent output (e.g. code containing credentials). |
| Art. 37 | DPO requirement | 🟢 N/A (for now) | Small-scale processing; no large-scale systematic profiling. DPO not mandatory at current scale. |
| Art. 46 | Cross-border transfers (SCCs) | 🟡 Partial | OpenAI/Anthropic are US-based. Data transfer mechanism (SCCs or adequacy decision) must be documented and referenced in the DPA. |

**GDPR Summary score: 6/10.** The technical controls (erasure, export, retention, PII redaction) are ahead of most pre-Series-A products. The legal/process layer (privacy notice, RoPA, signed DPAs, SCCs) is incomplete.

---

## 2. OWASP Top 10 (2021)

| # | Risk | Status | Finding |
|---|---|---|---|
| A01 | Broken Access Control | 🟢 Good | `require_permission()` dependency is on every endpoint. Tenant scope propagated via `contextvars`, never as a user-controlled parameter (`security-architecture.md` line 79). 12 tenant-isolation tests (`tests/test_security/test_tenant_isolation.py`). RBAC role hierarchy enforced on key creation. |
| A02 | Cryptographic Failures | 🟡 Partial | API keys hashed with SHA-256 (`auth.py:121`) — acceptable, but SHA-256 without salt is technically weaker than bcrypt/Argon2 for key storage (low practical risk as keys are high-entropy). Internal API→PostgreSQL traffic uses no TLS by default (`security-architecture.md` line 120). Backup encryption not documented. OIDC algorithm allowlist (RS/ES/PS only — no HS256) is correct. |
| A03 | Injection | 🟢 Good | All PostgreSQL queries use SQLAlchemy parameterized bindings. LIKE wildcard characters escaped. Prompt injection mitigated with XML delimiters and system-prompt instructions (acknowledged as partial defence only — `security.md` line 32). Path traversal: `..` and `/` rejected in pattern keys. |
| A04 | Insecure Design | 🟡 Partial | Threat model exists in `security-architecture.md`. Known limitations documented in `security.md`. Gap: no formal threat model document (e.g. STRIDE/PASTA). `dev` mode requires `ENGRAMIA_ALLOW_NO_AUTH=true` as deliberate ack — good footgun guard. |
| A05 | Security Misconfiguration | 🟡 Partial | Docker container runs as non-root (`brain:1001`). API port bound to `127.0.0.1:8000` only. **However:** `docker-compose.prod.yml` lacks `security_opt: no-new-privileges`, `read_only: true`, resource limits, and log rotation — all recommended in `production-hardening.md` but not applied. Swagger UI (`/docs`) is available in production — should be disabled or restricted by IP. |
| A06 | Vulnerable and Outdated Components | 🟢 Good | `pip-audit --strict` runs in CI on every push (`.github/workflows/ci.yml` line 102). Trufflehog secret scanning on every push. No image-level CVE scanning (e.g. Trivy) for the Docker image itself. |
| A07 | ID & Auth Failures | 🟢 Good | Timing-safe comparison via `hmac.compare_digest` (`auth.py:82`). LRU-bounded in-process cache (4096 entries, 60s TTL) prevents unbounded memory growth from invalid keys (`auth.py:128-131`). Rate limiting on auth failures. `dev` mode requires explicit opt-in. OIDC JWKS cached 1 hour; stale-key fallback on IdP outage creates a 1-hour window where a revoked OIDC key remains valid. |
| A08 | Software & Data Integrity | 🟡 Partial | GitHub release triggers Docker build; image tagged with semver. No `docker-compose.prod.yml` digest pinning (uses semver tag, not `sha256:…`). Local embedding model downloads from HuggingFace Hub without checksum verification (`security.md` line 55). `docker.yml` pushes `latest` tag on default branch. |
| A09 | Security Logging & Monitoring | 🟡 Partial | Structured JSON audit log for 9 event types (`security-architecture.md` line 127). No SIEM integration — audit log is append-only flat file/DB table. No alerting on repeated `AUTH_FAILURE` bursts beyond what Prometheus provides. Prometheus `/metrics` is optionally token-protected but not required. |
| A10 | SSRF | 🟡 Partial | Outbound calls limited to OpenAI/Anthropic (via their SDKs) and the Hetzner-local PostgreSQL. No user-supplied URLs are fetched. The `run_id` and `source` fields accept arbitrary strings but are not used as URLs. Low SSRF risk. However, no explicit allowlist of permitted outbound destinations is enforced at the network level. |

**OWASP Top 10 score: 7/10.**

---

## 3. OWASP API Security Top 10 (2023)

| # | Risk | Status | Finding |
|---|---|---|---|
| API1 | Broken Object-Level Auth | 🟢 Good | Every storage read/write is scoped to `(tenant_id, project_id)` set from auth context, never from request parameters (`security-architecture.md` line 80). No BOLA path identified. |
| API2 | Broken Authentication | 🟢 Good | Bearer token on every endpoint. Timing-safe comparison. No API key in URL parameters or query strings. `dev` mode requires explicit env var ack. |
| API3 | Broken Object Property-Level Auth | 🟡 Partial | `classification` field update endpoint (`PUT /v1/governance/patterns/{key}/classify`) — verify that editor-role cannot set classification to CONFIDENTIAL and then restrict their own access to bypass auditing. Role hierarchy on key creation enforced. |
| API4 | Unrestricted Resource Consumption | 🟡 Partial | Body size limit (1 MB default). `num_evals` capped at 10. Task/code field length limits. Rate limiter per IP/path. **Gap:** Rate limiter is in-process (`security.md` line 37) — in a multi-worker uvicorn deployment or multi-instance setup, each process has independent counters. No distributed rate limiter (Redis/API Gateway) deployed. |
| API5 | Broken Function-Level Auth | 🟢 Good | `require_permission()` factory generates endpoint-specific deps. Admin-only endpoints clearly gated. Bootstrap endpoint self-disables after first call (409 on repeat). |
| API6 | Unrestricted Access to Sensitive Business Flows | 🟡 Partial | `POST /v1/evolve` and `POST /v1/compose` are LLM-intensive and rate-limited to 10 req/min per IP. With in-process limits and multi-worker, this is bypassable. Async job queue (`Prefer: respond-async`) helps, but durability is best-effort only. |
| API7 | Server-Side Request Forgery | 🟢 Good | No user-supplied URLs fetched. Outbound limited to fixed providers. |
| API8 | Security Misconfiguration | 🟡 Partial | See A05 above. Swagger UI available at `/docs` in production. CORS disabled by default — good. |
| API9 | Improper Inventory Management | 🟢 Good | All endpoints under `/v1/` prefix. Version endpoint `GET /v1/version`. API stability policy documented (`docs/api-stability.md`). |
| API10 | Unsafe Consumption of APIs | 🟡 Partial | LLM provider responses are treated as untrusted (noted in `security.md` line 32). Eval variance detection (`>1.5` alert) as a sanity check. Prompt injection XML delimiters. However, no formal output validation schema for LLM-returned structured JSON beyond `extract_json_from_llm`. |

**OWASP API Security Top 10 score: 8/10.**

---

## 4. SOC 2 Trust Service Criteria

### CC — Security (Common Criteria)

| CC | Control | Have | Missing | Gap Severity |
|---|---|---|---|---|
| CC1 | Control environment | RBAC, license, SECURITY.md, audit log | Formal board/advisory oversight; no external code review requirement | Medium |
| CC2 | Communication & information | Structured audit log, OTel traces, SECURITY.md | Public vulnerability disclosure policy page; no CVE numbering process | Low |
| CC3 | Risk assessment | OWASP ASVS L2/3 framework, threat model, prior audit | No formal annual risk assessment cycle; no risk register | Medium |
| CC6 | Logical access controls | RBAC (4 roles), scope isolation, `require_permission()`, cache invalidation on revoke | No MFA for operator VM SSH access verified; OIDC JWKS stale-key window (1h) | High |
| CC7 | System operations | Prometheus, OTel tracing, Docker healthchecks, CI pip-audit, trufflehog | No SIEM integration; no automated alerting on repeated AUTH_FAILURE; no image-level CVE scan | High |
| CC8 | Change management | GitHub PR workflow, CI required before merge, semver releases, rollback docs | Solo review only — no second reviewer requirement enforced by branch protection | Medium |
| CC9 | Risk mitigation | Sub-processors documented, async job queue, provider timeouts | No formal vendor questionnaires for OpenAI/Anthropic; no supply chain SBOM | Medium |

### A1 — Availability

| Control | Have | Missing | Gap Severity |
|---|---|---|---|
| Availability commitments | Health endpoints, Prometheus, Docker restart policy | No uptime SLA published; no status page | Medium |
| Recovery planning | RTO 4h / RPO 24h documented; backup-restore.md | Backup encryption not documented; recovery has not been tested/drilled | High |
| Capacity planning | Disk sizing guidance in production-hardening.md; aging prunes stale patterns | No horizontal scaling runbook; single-instance only | Medium |

### PI1 — Processing Integrity

| Control | Have | Missing | Gap Severity |
|---|---|---|---|
| Completeness & accuracy | Pydantic v2 validation; eval variance detection | No end-to-end idempotency guarantee on job re-runs; best-effort async (no DLQ) | Low |
| Processing monitoring | 726 tests, 80.29% coverage; testcontainers integration tests | mypy `continue-on-error: true` in CI — type errors do not block merge | Low |

### C1 — Confidentiality

| Control | Have | Missing | Gap Severity |
|---|---|---|---|
| Identify confidential info | Per-pattern classification (PUBLIC/INTERNAL/CONFIDENTIAL) | No automatic classification — relies on caller setting it | Medium |
| Protect confidential info | RBAC, scope isolation, PII redaction pipeline, TLS | PII redaction opt-in (not default-on); encryption at rest not application-enforced | High |

### P — Privacy

| Control | Have | Missing | Gap Severity |
|---|---|---|---|
| Notice | Right to erasure and portability implemented | No customer-facing privacy notice/policy | Critical |
| Data retention | Configurable TTL; retention cleanup job | No documented default retention for audit logs themselves | Medium |
| Data breach | IR runbook references GDPR Art. 33 | No breach notification template; no DPA contact registry | High |

**SOC 2 overall: 6/10.** Technical controls are strong. The policy/process layer (privacy notice, annual risk review, second-reviewer branch protection, SIEM, tested recovery, SBOM) needs completion before a Type II audit.

---

## 5. ISO 27001:2022 — Top 20 Key Controls

| Control | Description | Status | Gap | Effort |
|---|---|---|---|---|
| A.5.1 | Information security policies | 🟡 Partial | SECURITY.md + security-architecture.md serve as policy. No formal policy document signed by management. | Low |
| A.5.2 | Information security roles | 🟡 Partial | RBAC documented. No RACI or named CISO/security function. | Low |
| A.5.9 | Inventory of assets | 🔴 Gap | No formal asset register (VMs, databases, secrets, external APIs). | Medium |
| A.5.10 | Acceptable use of assets | 🟡 Partial | CLAUDE.md permissions section covers dev workflow. No formal acceptable use policy for operators/customers. | Low |
| A.5.14 | Information transfer | 🟢 Good | TLS enforced. Sub-processors documented. | — |
| A.5.23 | Information security for cloud services | 🟡 Partial | Hetzner, OpenAI, Anthropic used. DPAs referenced but not verified/signed. No cloud security assessment. | Medium |
| A.5.26 | Incident response | 🟡 Partial | IR runbook exists (`docs/runbooks/incident-response.md`). No tabletop exercises documented. No incident log. | Medium |
| A.5.30 | ICT readiness for business continuity | 🟡 Partial | RTO/RPO documented. No tested recovery drill. | High |
| A.6.1 | Screening | 🔴 Gap | No background check policy for personnel with access to production. | Medium |
| A.6.3 | Information security awareness | 🔴 Gap | No security training programme for team members. | Low |
| A.6.8 | Information security event reporting | 🟡 Partial | security@engramia.dev with 72h SLA. No formal internal reporting process. | Low |
| A.7.1 | Physical security perimeters | 🟢 Delegated | Hetzner datacenter (ISO 27001 certified). Out of scope for application-layer audit. | — |
| A.8.2 | Privileged access rights | 🟡 Partial | RBAC enforced. No documented process for granting/reviewing privileged VM SSH access. | Medium |
| A.8.3 | Information access restriction | 🟢 Good | Scope isolation via contextvars; RBAC on all endpoints. | — |
| A.8.7 | Protection against malware | 🟢 Good | pip-audit + trufflehog in CI. No user-supplied executables. | — |
| A.8.8 | Management of technical vulnerabilities | 🟡 Partial | pip-audit covers Python deps. No container image CVE scan (e.g. Trivy). No patch SLA defined. | Medium |
| A.8.12 | Data leakage prevention | 🟡 Partial | PII redaction pipeline (opt-in). No DLP for audit log exports. | High |
| A.8.15 | Logging | 🟡 Partial | 9 structured audit event types. No log integrity protection (append-only but no WORM/signed log). No log retention policy. | Medium |
| A.8.24 | Cryptography | 🟡 Partial | TLS 1.2+, SHA-256 key hashes, OIDC RS/ES/PS only. SHA-256 without salt for key hashing is not ideal (bcrypt/Argon2 preferred for password-like material). | Low |
| A.8.32 | Change management | 🟡 Partial | GitHub PR + CI. No formal change advisory process; solo review only. | Medium |

**ISO 27001 score: 5/10.** The technical controls map reasonably well to Annex A, but the management system (asset register, training, policy documents, drills) is missing. Full ISO 27001 certification would require 6-12 months of management system build-out.

---

## 6. CIS Controls v8 — IG1 + IG2

### Implementation Group 1 (Foundational — all organisations)

| Control | Title | Status | Finding |
|---|---|---|---|
| CIS 1 | Inventory of Enterprise Assets | 🟡 Partial | VM, containers, DB known. No formal asset register. |
| CIS 2 | Inventory of Software Assets | 🟡 Partial | `pyproject.toml` + Docker image pin versions. No SBOM generated and published. |
| CIS 3 | Data Protection | 🟡 Partial | Classification labels, PII redaction (opt-in), RBAC. Encryption at rest not enforced. |
| CIS 4 | Secure Configuration of Enterprise Assets | 🟡 Partial | Non-root Docker, ports bound to 127.0.0.1. `security_opt: no-new-privileges`, `read_only`, resource limits missing from `docker-compose.prod.yml`. |
| CIS 5 | Account Management | 🟢 Good | `POST /v1/keys/bootstrap` one-time, `DELETE /v1/keys/{id}` immediate revocation, cache invalidation. |
| CIS 6 | Access Control Management | 🟢 Good | RBAC 4 roles, role hierarchy on key creation, scope isolation. |
| CIS 7 | Continuous Vulnerability Management | 🟡 Partial | pip-audit in CI. No scheduled re-scan of deployed container. No container image CVE scan. |
| CIS 11 | Data Recovery | 🟡 Partial | pg_dump procedure documented (RTO 4h, RPO 24h). Recovery not tested. Backup encryption not documented. |
| CIS 12 | Network Infrastructure Management | 🟡 Partial | Caddy TLS, port 8000 internal-only, Hetzner firewall documented. No outbound allowlist at OS/firewall level. |
| CIS 14 | Security Awareness and Skills Training | 🔴 Gap | No security awareness programme. |
| CIS 17 | Incident Response Management | 🟡 Partial | IR runbook exists. No tabletop exercise record. |

### Implementation Group 2 (Enterprise baseline)

| Control | Title | Status | Finding |
|---|---|---|---|
| CIS 8 | Audit Log Management | 🟡 Partial | Structured audit log, 9 event types. No centralised SIEM, no log retention/rotation policy, no log integrity control. |
| CIS 9 | Email and Web Browser Protections | 🟢 N/A | API-only product, no browser interaction. |
| CIS 10 | Malware Defenses | 🟢 Good | pip-audit, trufflehog, no user executables. |
| CIS 13 | Network Monitoring and Defense | 🔴 Gap | No IDS/IPS. Rate limiting in-process only. No WAF. Prometheus metrics present but no anomaly detection. |
| CIS 15 | Service Provider Management | 🟡 Partial | Sub-processors listed. No formal vendor risk assessments. |
| CIS 16 | Application Software Security | 🟢 Good | OWASP ASVS L2/3, Pydantic validation, parameterised SQL, pip-audit, 80%+ test coverage. |
| CIS 18 | Penetration Testing | 🔴 Gap | No penetration test conducted. Documented as planned in `soc2-controls.md`. |

**CIS Controls score: 6/10.** IG1 largely satisfied at the technical level. IG2 gaps are mostly in monitoring maturity, vendor management formality, and penetration testing.

---

## 7. PCI DSS Scope Reduction

Engramia does not directly process, store, or transmit payment card data. Stripe is assumed to be the payment processor (referenced in product pricing docs).

**Scope reduction by Stripe:**
- Stripe.js / Stripe Checkout handles card data in an iframe served from Stripe's domain — Engramia never sees the PAN.
- If using Stripe's hosted payment pages or Stripe Elements, Engramia qualifies for **SAQ A** (the smallest PCI scope tier).
- Engramia never stores CVV, full PAN, or magnetic stripe data.

**What remains in scope:**
- The Engramia API handles Stripe webhook events (subscription status, invoice events) — these events contain the customer's Stripe customer ID and subscription metadata, not card data.
- Webhook endpoint must validate Stripe's HMAC signature (`Stripe-Signature` header) to prevent replay/forgery. Confirm this is implemented in the billing module.
- HTTPS (TLS 1.2+) for all webhook traffic: **already satisfied** by Caddy.
- Stripe secret key (`STRIPE_SECRET_KEY` if used) must be stored as an environment variable, never in source or DB: consistent with Engramia's secrets management approach.

**PCI DSS score: 9/10.** Scope is minimal by design. Confirm webhook signature validation is implemented.

---

## 8. Findings Table

| # | Finding | Standard | Severity | Effort | Recommendation |
|---|---|---|---|---|---|
| F-01 | Docker `security_opt`, `read_only`, resource limits absent from `docker-compose.prod.yml` | CIS 4, A05 | High | Low | Add `security_opt: [no-new-privileges:true]`, `read_only: true`, `tmpfs: [/tmp]`, and `deploy.resources.limits` to `docker-compose.prod.yml` as documented in `production-hardening.md`. |
| F-02 | In-process rate limiter — bypass with multiple uvicorn workers | API4, A05 | High | Medium | Deploy Redis-backed rate limiter (e.g. `slowapi` with Redis backend) or use Caddy `rate_limit` plugin / Cloudflare for single-entry-point enforcement. |
| F-03 | No privacy notice / privacy policy page | GDPR Art. 13, SOC 2 P | Critical | Low | Write and publish a privacy notice at `engramia.dev/privacy` before any public sign-up. Minimum: data categories processed, lawful basis, processor relationships, data subject rights, contact. |
| F-04 | No Record of Processing Activities (RoPA) | GDPR Art. 30 | High | Low | Create an internal RoPA document listing: processing activity, purpose, lawful basis, data categories, retention period, sub-processors. 1–2 pages for current scope. |
| F-05 | PII redaction pipeline is opt-in, not default-on | GDPR Art. 25 | High | Low | Change default to `ENGRAMIA_REDACTION=true` (enabled unless explicitly disabled). Update docs. Operators should opt-out, not opt-in. |
| F-06 | No TLS between API container and PostgreSQL (internal bridge) | ISO A.8.24, GDPR Art. 32 | Medium | Medium | Add `?sslmode=require` guidance as a required (not optional) step in production-hardening.md. For same-host deployments, document the trust assumption explicitly. For future multi-host DB, enforce at connection string level. |
| F-07 | OIDC JWKS stale-key fallback: revoked key valid for up to 1 hour | A07, CC6 | High | Medium | Reduce JWKS TTL for OIDC mode to 5 minutes or add a revocation check endpoint. Document the 1-hour window as a known limitation with mitigation (immediate key rotation via IdP + API restart). |
| F-08 | No second-reviewer branch protection enforced on `main` | CC8, ISO A.8.32 | Medium | Low | Enable GitHub branch protection: require 1 approved review from a non-author before merge. For a solo founder, add a trusted external reviewer or use a security-focused review service. |
| F-09 | No container image CVE scanning in CI | CIS 7, CC7, ISO A.8.8 | High | Low | Add Trivy scan step to `docker.yml`: `uses: aquasecurity/trivy-action@master` with `image-ref: ghcr.io/engramia/engramia:${{ steps.meta.outputs.version }}`. Fail on CRITICAL. |
| F-10 | Swagger UI (`/docs`) accessible in production | A05, API8 | Medium | Low | Disable OpenAPI docs in production: set `docs_url=None, redoc_url=None` in `create_app()` when `ENGRAMIA_ENVIRONMENT=production`, or restrict to trusted IP ranges via Caddy. |
| F-11 | mypy `continue-on-error: true` — type errors do not block CI | ISO A.8.8, PI1 | Low | Low | Fix current mypy errors, then remove `continue-on-error: true` from `ci.yml` line 36. Type errors in auth/scope propagation paths can mask security bugs. |
| F-12 | No DPAs signed with OpenAI / Anthropic — not documented | GDPR Art. 28, CC9 | High | Medium | Sign OpenAI's DPA and Anthropic's DPA (both available on their websites). Store signed copies. Reference them in a public sub-processors list. |
| F-13 | Backup encryption not documented or enforced | ISO A.8.24, CIS 3 | High | Medium | Add `--encrypt` / `--symmetric` with GPG to the `pg_dump` command in the backup runbook. Store the encryption key in a separate location from the backup. |
| F-14 | No penetration test conducted | CC7, CIS 18 | High | High | Commission an external pentest before the first enterprise customer. Budget: $8k–$20k for API + infrastructure. Document findings and remediations. |
| F-15 | Prometheus `/metrics` endpoint protection is optional | A09, CIS 8 | Medium | Low | Make `ENGRAMIA_METRICS_TOKEN` required (not optional) when `ENGRAMIA_METRICS=true`. The metrics endpoint exposes pattern counts, eval scores, and reuse rates — commercially sensitive. |
| F-16 | Local embedding model downloads lack checksum verification | A08, ISO A.8.7 | Medium | Medium | Pin model versions and SHA-256 checksums in `LocalEmbeddings`. Validate before loading. Consider hosting approved model snapshots internally. |
| F-17 | No SIEM integration — audit log is flat JSON/DB table | CC7, ISO A.8.15 | High | Medium | Integrate with a SIEM or log aggregator (Datadog, Loki, Elastic). Minimum: ship `audit_log` table to an append-only external store. Add alerting on >10 `AUTH_FAILURE` events in 5 minutes. |
| F-18 | `docker-compose.prod.yml` has no log rotation configuration | CIS 8, A05 | Low | Low | Add `logging.driver: json-file` with `max-size: 100m, max-file: 5` to all services as documented in `production-hardening.md`. |
| F-19 | No formal incident response drills or tabletop exercises | ISO A.5.26, CIS 17 | Medium | Medium | Conduct a tabletop exercise (2 hours) against the IR runbook at least annually. Document the session and any runbook updates. |
| F-20 | No customer-facing DPA template | GDPR Art. 28, SOC 2 P | High | Low | Create a standard Data Processing Agreement template for B2B customers. This is a hard blocker for enterprise sales. Can be a 3-5 page standard document. |

---

## 9. Remediation Roadmap

### Phase 1: Before Public Launch / Private Beta (now → launch)

These items create legal liability or are easily exploited and must be resolved before any customer can sign up.

| Item | Finding | Owner | Priority |
|---|---|---|---|
| Publish privacy notice | F-03 | Founder | P0 |
| Create RoPA | F-04 | Founder | P0 |
| Default PII redaction on | F-05 | Engineering | P0 |
| Add Docker hardening to `docker-compose.prod.yml` | F-01 | Engineering | P1 |
| Disable Swagger UI in production | F-10 | Engineering | P1 |
| Add container image CVE scan to CI (Trivy) | F-09 | Engineering | P1 |
| Remove `mypy continue-on-error` | F-11 | Engineering | P1 |
| Log rotation in `docker-compose.prod.yml` | F-18 | Engineering | P1 |
| Protect `/metrics` with required token | F-15 | Engineering | P1 |
| Sign OpenAI + Anthropic DPAs | F-12 | Founder | P1 |

### Phase 2: Before First Enterprise Customer

Enterprise procurement will ask for these. Missing any will fail a security questionnaire.

| Item | Finding | Owner | Priority |
|---|---|---|---|
| External penetration test (API + infra) | F-14 | Founder | P1 |
| Customer-facing DPA template | F-20 | Legal/Founder | P1 |
| Deploy distributed rate limiter (Redis / Caddy plugin) | F-02 | Engineering | P1 |
| SIEM / log shipping with AUTH_FAILURE alerts | F-17 | Engineering | P2 |
| OIDC JWKS TTL reduction + revocation docs | F-07 | Engineering | P2 |
| Branch protection with required review | F-08 | Founder | P2 |
| Document and enforce backup encryption | F-13 | Engineering | P2 |
| Internal TLS for API→PostgreSQL (multi-host) | F-06 | Engineering | P2 |

### Phase 3: Before SOC 2 Type II Audit

SOC 2 Type II requires a 6-12 month observation period. Start the period only after Phase 2 is complete.

| Item | Finding | Owner | Priority |
|---|---|---|---|
| Formal asset register | — | Founder | P2 |
| Annual risk assessment cycle | ISO A.5.9 | Founder | P2 |
| Security awareness training (documented) | CIS 14 | Founder | P2 |
| Vendor questionnaires for OpenAI/Anthropic | CC9 | Founder | P2 |
| Tabletop IR drill (annual) | F-19 | Team | P2 |
| Local embedding model checksum verification | F-16 | Engineering | P3 |
| SBOM generation on release | CIS 2 | Engineering | P3 |
| Formal change management policy | ISO A.8.32 | Founder | P3 |
| Publish sub-processors list (public) | GDPR Art. 28 | Founder | P3 |
| Engage licensed CPA firm for SOC 2 Type II | — | Founder | P3 |

---

## 10. "Compliant Without Certification" Checklist

What a B2B customer's security team needs to say "yes, I'm using a compliant vendor." Current status as of 2026-04-05:

**Authentication & Access Control**
- [x] API keys hashed (SHA-256), never stored in plaintext
- [x] Timing-safe key comparison (`hmac.compare_digest`)
- [x] RBAC with 4 roles (owner/admin/editor/reader)
- [x] OIDC / SSO support (Okta, Azure AD, Keycloak)
- [x] Key revocation with immediate cache invalidation
- [x] Multi-tenant data isolation (verified by 12 automated tests)

**Transport & Encryption**
- [x] TLS 1.2+ enforced (Caddy + Let's Encrypt auto-renew)
- [x] HSTS header (`max-age=31536000; includeSubDomains`)
- [x] All outbound LLM API calls over HTTPS
- [ ] TLS for internal API→PostgreSQL traffic (optional today; required for multi-host)
- [ ] Encryption at rest enforced and documented (recommended but not verified)
- [ ] Backup encryption (TODO — F-13)

**Data Protection & GDPR**
- [x] Right to erasure — `DELETE /v1/governance/projects/{id}` (GDPR Art. 17)
- [x] Right to portability — `GET /v1/governance/export` (GDPR Art. 20)
- [x] Configurable data retention per tenant/project
- [x] Data classification labels (PUBLIC/INTERNAL/CONFIDENTIAL)
- [x] PII redaction pipeline (emails, tokens, credentials)
- [ ] PII redaction default-on (TODO — F-05)
- [ ] Privacy notice published (TODO — F-03)
- [ ] Record of Processing Activities (RoPA) (TODO — F-04)
- [ ] Signed DPAs with OpenAI and Anthropic (TODO — F-12)
- [ ] Customer-facing DPA template (TODO — F-20)

**Security Operations**
- [x] Structured audit log for all security events (9 event types)
- [x] Automated dependency scanning (pip-audit in CI)
- [x] Secret scanning (trufflehog on every push)
- [x] Non-root container (`brain:1001`)
- [x] API port not publicly exposed (bound to `127.0.0.1`)
- [x] Incident response runbook
- [ ] Container image CVE scanning (Trivy) (TODO — F-09)
- [ ] SIEM integration with alerting (TODO — F-17)
- [ ] External penetration test completed (TODO — F-14)
- [ ] Swagger UI disabled in production (TODO — F-10)
- [ ] Docker `no-new-privileges`, `read_only`, resource limits applied (TODO — F-01)

**Availability & Recovery**
- [x] Docker healthcheck with restart policy
- [x] Async job queue (LLM-intensive ops non-blocking)
- [x] Documented RTO (4h) and RPO (24h)
- [ ] Backup encryption (TODO — F-13)
- [ ] Recovery drill completed and documented (TODO — Phase 3)

**CI/CD & Change Management**
- [x] CI required to pass before deploy (GitHub Actions)
- [x] Semver release tagging with version verification
- [x] Automated migration on deploy (`alembic upgrade head`)
- [ ] Required code review by second reviewer (TODO — F-08)
- [ ] SBOM published on release (TODO — Phase 3)

---

*Generated from source review of Engramia v0.6.5 on 2026-04-05. Re-run this audit after each major version or when deploying to a new environment. Contact security@engramia.dev for questions.*

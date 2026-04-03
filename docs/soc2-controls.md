# SOC 2 Controls Reference

Engramia v0.6.0 · Trust Service Criteria: Security (CC), Availability (A)

> **Status:** Controls implemented — no formal SOC 2 audit conducted yet.
> This document maps Engramia's existing controls to SOC 2 Type II criteria
> for use in enterprise security reviews and pre-audit gap analysis.

---

## CC1 — Control Environment

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| CC1.1 | COSO principles applied | ✅ | BSL 1.1 license; SECURITY.md; this document |
| CC1.2 | Board oversight of security | 🟡 | Founder-level ownership; no formal board yet |
| CC1.3 | Organizational structure | ✅ | Roles documented (RBAC: owner/admin/editor/reader) |
| CC1.4 | Competence commitment | ✅ | Python 3.12, OWASP ASVS L2/3, 80% test coverage |
| CC1.5 | Accountability | ✅ | Audit log for all security events; key ownership tracked |

---

## CC2 — Communication and Information

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| CC2.1 | Security information use | ✅ | Structured JSON audit log; OpenTelemetry traces |
| CC2.2 | Internal communication | ✅ | SECURITY.md; runbooks; CLAUDE.md |
| CC2.3 | External communication | 🟡 | SECURITY.md public; security@engramia.dev; no formal disclosure policy page yet |

---

## CC3 — Risk Assessment

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| CC3.1 | Risk objectives | ✅ | OWASP ASVS L2/3 as risk framework |
| CC3.2 | Risk identification | ✅ | Audit findings 2026-03-28 (78/100); all P0/P1 resolved |
| CC3.3 | Risk analysis | ✅ | Threat model in security-architecture.md |
| CC3.4 | Risk mitigation | ✅ | All P0/P1 audit items closed by v0.6.0 |

---

## CC6 — Logical and Physical Access Controls

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| CC6.1 | Logical access | ✅ | RBAC (4 roles); `require_permission()` on every endpoint |
| CC6.2 | New user access registration | ✅ | `POST /v1/keys` (admin+); bootstrap once; role explicit |
| CC6.3 | Remove access | ✅ | `DELETE /v1/keys/{id}` (revoke); immediate cache invalidation |
| CC6.6 | Logical access restrictions | ✅ | Scope isolation (tenant/project); contextvars propagation |
| CC6.7 | Transmission security | ✅ | TLS 1.2+ via Caddy; HSTS; HTTPS for all outbound LLM calls |
| CC6.8 | Malware prevention | ✅ | pip-audit in CI; trufflehog secret scanning; no user-supplied executables |

---

## CC7 — System Operations

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| CC7.1 | Vulnerability detection | ✅ | `pip-audit --strict` in CI; trufflehog on every push |
| CC7.2 | Monitoring | ✅ | Prometheus metrics; OTel tracing; Docker healthcheck; `GET /v1/health/deep` |
| CC7.3 | Incident evaluation | ✅ | docs/runbooks/incident-response.md; severity levels defined |
| CC7.4 | Incident response | ✅ | Runbook with containment, investigation, notification steps |
| CC7.5 | Incident identification | ✅ | Audit log: AUTH_FAILURE, QUOTA_EXCEEDED, SCOPE_DELETED, PII_REDACTED |

---

## CC8 — Change Management

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| CC8.1 | Change management process | ✅ | GitHub PR workflow; CI required to pass before merge |
| CC8.1 | Code review | 🟡 | Solo project currently — code review by founder; external reviewers not yet required |
| CC8.1 | Deployment authorization | ✅ | GitHub release triggers automated deploy; `ENGRAMIA_ENVIRONMENT` guard |
| CC8.1 | Rollback capability | ✅ | Versioned Docker images; `alembic downgrade`; docs/deployment.md rollback |

---

## CC9 — Risk Mitigation

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| CC9.1 | Business disruption risk | ✅ | Async job queue for long ops; provider timeouts; fallback to JSON storage |
| CC9.2 | Vendor risk management | 🟡 | Sub-processors listed in data-handling.md; no formal vendor questionnaires yet |

---

## A1 — Availability

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| A1.1 | Availability commitments | ✅ | Health endpoints; Prometheus availability metrics; Docker restart policy |
| A1.2 | Recovery planning | ✅ | docs/backup-restore.md (RTO: 4h, RPO: 24h) |
| A1.3 | Environmental protections | ✅ | Hetzner DE datacenter; redundant power/network per Hetzner SLA |

---

## PI1 — Processing Integrity (partial)

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| PI1.1 | Complete and accurate processing | ✅ | Pydantic v2 validation; input length/type checks; eval variance detection |
| PI1.2 | Processing monitoring | ✅ | 726 tests (80.29% coverage); multi-evaluator with variance >1.5 alert |

---

## C1 — Confidentiality (partial)

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| C1.1 | Identify confidential information | ✅ | Data classification (PUBLIC/INTERNAL/CONFIDENTIAL) per pattern |
| C1.2 | Protect confidential information | ✅ | Scope isolation; RBAC; PII redaction pipeline; TLS in transit |

---

## Gap Summary

| Priority | Gap | Planned |
|----------|-----|---------|
| P1 | No formal security audit conducted | Planned for pre-Series A |
| P1 | Audit log not shipped to SIEM | Phase 6 backlog (Datadog / Loki integration) |
| P2 | External code review not formalized | Needed before external contributors |
| P2 | Vendor questionnaires for OpenAI/Anthropic | Phase 6 backlog |
| P2 | No formal penetration test | Planned for pre-enterprise launch |
| P3 | Board oversight / advisory board | Founder-owned until seed round |

---

## Using This Document in Enterprise Reviews

This document is intended for:
- Enterprise procurement security reviews
- Customer security questionnaires
- Pre-audit gap analysis before a formal SOC 2 Type II engagement

For a formal audit, engage a licensed CPA firm accredited by the AICPA (e.g., A-LIGN, Schellman, Dansa D'Arata Soucia).

Current posture summary for reviewers:
- **Authentication**: multi-mode (DB keys with SHA-256, RBAC, optional OIDC SSO)
- **Multi-tenancy**: cryptographic scope isolation at storage layer
- **Audit trail**: structured JSON, all security events
- **Data residency**: EU (Hetzner DE, Frankfurt region)
- **GDPR**: right to erasure (Art. 17) and portability (Art. 20) implemented
- **Test coverage**: 80.29% (726 tests), PostgreSQL integration tests via testcontainers

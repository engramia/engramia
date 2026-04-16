# SOC 2 Controls Reference

Engramia · Trust Service Criteria: Security (CC), Availability (A)

> **Status:** Controls implemented — no formal SOC 2 Type II audit conducted yet.
> This document maps Engramia's existing controls to SOC 2 criteria for use
> in enterprise security reviews. For a formal audit, engage a licensed CPA
> firm accredited by the AICPA (e.g., A-LIGN, Schellman, Dansa D'Arata Soucia).

---

## CC1 — Control Environment

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| CC1.1 | COSO principles applied | ✅ | BSL 1.1 license; SECURITY.md; this document |
| CC1.2 | Board oversight of security | 🟡 | Founder-level ownership |
| CC1.3 | Organizational structure | ✅ | Roles documented (RBAC: owner/admin/editor/reader) |
| CC1.4 | Competence commitment | ✅ | Python 3.12+, OWASP ASVS L2/3, 80%+ test coverage |
| CC1.5 | Accountability | ✅ | Audit log for all security events; key ownership tracked |

---

## CC2 — Communication and Information

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| CC2.1 | Security information use | ✅ | Structured JSON audit log; OpenTelemetry traces |
| CC2.2 | Internal communication | ✅ | SECURITY.md; internal runbooks |
| CC2.3 | External communication | ✅ | SECURITY.md public; support@engramia.dev; private GitHub security advisories |

---

## CC3 — Risk Assessment

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| CC3.1 | Risk objectives | ✅ | OWASP ASVS L2/3 as risk framework |
| CC3.2 | Risk identification | ✅ | Regular internal security audits; all identified P0/P1 items tracked to resolution |
| CC3.3 | Risk analysis | ✅ | Threat model in security-architecture.md |
| CC3.4 | Risk mitigation | ✅ | All P0/P1 items closed in current minor release |

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
| CC7.3 | Incident evaluation | ✅ | Severity levels defined; response runbook maintained (internal) |
| CC7.4 | Incident response | ✅ | Runbook with containment, investigation, notification steps (internal) |
| CC7.5 | Incident identification | ✅ | Audit log: AUTH_FAILURE, QUOTA_EXCEEDED, SCOPE_DELETED, PII_REDACTED |

---

## CC8 — Change Management

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| CC8.1 | Change management process | ✅ | GitHub PR workflow; CI required to pass before merge |
| CC8.1 | Code review | 🟡 | Solo project — code review by founder |
| CC8.1 | Deployment authorization | ✅ | GitHub release triggers automated deploy; `ENGRAMIA_ENVIRONMENT` guard |
| CC8.1 | Rollback capability | ✅ | Versioned Docker images; `alembic downgrade`; rollback procedure documented |

---

## CC9 — Risk Mitigation

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| CC9.1 | Business disruption risk | ✅ | Async job queue for long ops; provider timeouts; fallback to JSON storage |
| CC9.2 | Vendor risk management | 🟡 | Sub-processors listed in data-handling.md |

---

## A1 — Availability

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| A1.1 | Availability commitments | ✅ | Health endpoints; Prometheus availability metrics; Docker restart policy |
| A1.2 | Recovery planning | ✅ | Backup/restore procedure with documented RTO (4h) and RPO (24h) |
| A1.3 | Environmental protections | ✅ | EU datacenter; redundant power/network per hosting provider SLA |

---

## PI1 — Processing Integrity (partial)

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| PI1.1 | Complete and accurate processing | ✅ | Pydantic v2 validation; input length/type checks; eval variance detection |
| PI1.2 | Processing monitoring | ✅ | 1000+ tests, 80%+ coverage; multi-evaluator with variance >1.5 alert |

---

## C1 — Confidentiality (partial)

| Criterion | Requirement | Status | Evidence |
|-----------|-------------|--------|---------|
| C1.1 | Identify confidential information | ✅ | Data classification (PUBLIC/INTERNAL/CONFIDENTIAL) per pattern |
| C1.2 | Protect confidential information | ✅ | Scope isolation; RBAC; PII redaction pipeline; TLS in transit |

---

## Using This Document in Enterprise Reviews

This document is intended for:

- Enterprise procurement security reviews
- Customer security questionnaires
- Pre-audit gap analysis before a formal SOC 2 Type II engagement

For a formal audit, engage a licensed CPA firm accredited by the AICPA.

### Current posture summary for reviewers

- **Authentication:** multi-mode (DB keys with SHA-256, RBAC, optional OIDC SSO)
- **Multi-tenancy:** cryptographic scope isolation at storage layer
- **Audit trail:** structured JSON, all security events
- **Data residency:** EU (Frankfurt region)
- **GDPR:** right to erasure (Art. 17) and portability (Art. 20) implemented
- **Test coverage:** 80%+ (1000+ tests), PostgreSQL integration tests via testcontainers

### Known limitations

Formal SOC 2 Type II audit, SIEM integration, external code review, and
formal penetration testing are planned but not yet conducted. Contact
support@engramia.dev for the current state or to discuss an enterprise
engagement.

# Security

This page summarizes Engramia's security measures and links to detailed
documentation. For the full security policy, vulnerability reporting process,
and production deployment checklist, see the repository-level
[SECURITY.md](https://github.com/engramia/engramia/blob/main/SECURITY.md).

---

## Implemented Measures

| Area | Measure |
|------|---------|
| **Authentication** | Bearer token via `ENGRAMIA_API_KEYS`; timing-safe comparison (`hmac.compare_digest`) |
| **Rate limiting** | Per-IP, per-path fixed-window; separate limits for LLM-intensive endpoints |
| **Input validation** | `eval_score` bounds [0, 10]; `task` max 10,000 chars; `code` max 500,000 chars; `num_evals` capped at 10; `max_length` on all API string fields |
| **Path traversal** | Pattern keys must start with `patterns/` and must not contain `..` |
| **SQL injection** | All PostgreSQL queries use parameterized statements (SQLAlchemy `:param` binding) |
| **LIKE wildcard injection** | `%` and `_` are escaped in PostgreSQL `LIKE` queries |
| **Prompt injection** | XML delimiters around user content in LLM prompts; "disregard" instructions in system prompts |
| **CORS** | Disabled by default; must be explicitly configured via `ENGRAMIA_CORS_ORIGINS` |
| **Security headers** | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `X-Permitted-Cross-Domain-Policies: none` |
| **Body size limit** | Configurable max request body (default 1 MB) |
| **Error sanitization** | Exception details logged server-side only, not returned to clients |
| **Audit logging** | Structured JSON for `auth_failure`, `pattern_deleted`, `rate_limited` events |
| **Key hashing** | SHA-256 for all internal key generation |
| **Docker hardening** | Non-root user (`brain:1001`) |
| **API versioning** | All endpoints under `/v1/` prefix |

## Reporting Vulnerabilities

If you discover a security vulnerability, please report it responsibly.
**Do not open a public issue for security vulnerabilities.**

Contact: [security@engramia.dev](mailto:security@engramia.dev)

You will receive an acknowledgement within 48 hours. See the full
[SECURITY.md](https://github.com/engramia/engramia/blob/main/SECURITY.md)
for the disclosure process and known limitations.

## Detailed Security Documentation

| Document | Description |
|----------|-------------|
| [SECURITY.md](https://github.com/engramia/engramia/blob/main/SECURITY.md) | Full security policy — 10 known limitations, production deployment checklist, OWASP ASVS Level 2/3 compliance |
| [Security Architecture](architecture/security-architecture.md) | Threat model, defense layers, trust boundaries |
| [SOC 2 Controls](soc2-controls.md) | SOC 2 Type II control mapping |
| [Incident Response Plan](incident-response-plan.md) | Severity matrix, response procedures, GDPR breach notification, communication templates |
| [Production Hardening](production-hardening.md) | TLS termination, secrets management, infrastructure security |
| [Data Handling](data-handling.md) | How Engramia processes and stores data |

# Security Architecture

Engramia v0.6.0 · Classification: Internal

---

## Overview

Engramia is a REST API + Python library that stores and retrieves agent execution patterns.
It processes data provided by calling agent systems — task descriptions, code snippets, evaluation scores, and feedback — and persists them in a scoped storage backend.

Security posture: **OWASP ASVS Level 2/3** (see SECURITY.md for the full control mapping).

---

## System Boundaries

```
                       ┌─────────────────────────────────────────┐
  Agent / LLM          │              TRUST BOUNDARY              │
  Framework  ──HTTPS──▶│  Caddy (TLS termination)                 │
                       │         │                                │
                       │         ▼                                │
                       │  Engramia API (FastAPI, non-root)         │
                       │  ├── Auth middleware (Bearer / OIDC)     │
                       │  ├── Rate limiting (per IP/path)         │
                       │  ├── Body size limit (1 MB default)      │
                       │  ├── Security headers (CSP, HSTS, ...)   │
                       │  └── Business logic (Memory + services)  │
                       │         │                                │
                       │         ├──▶ PostgreSQL + pgvector       │
                       │         │    (scoped: tenant + project)  │
                       │         │                                │
                       │         └──▶ LLM Provider (outbound)    │
                       │              OpenAI / Anthropic HTTPS    │
                       └─────────────────────────────────────────┘
```

**External callers** authenticate with Bearer tokens. The API trusts nothing that crosses the boundary without a valid token.

**LLM providers** are downstream — the API calls out to OpenAI/Anthropic over HTTPS. API keys are held in environment variables only, never in storage.

---

## Authentication & Authorization

### Auth modes

| Mode | Mechanism | Use case |
|------|-----------|----------|
| `auto` (default) | DB if `DATABASE_URL` set, else env-var | Most deployments |
| `env` | `ENGRAMIA_API_KEYS` static list | Single-tenant, backward compat |
| `db` | DB `api_keys` table, SHA-256 hashed | Multi-tenant SaaS |
| `oidc` | OIDC JWT (RS256/ECDSA) + JWKS | Enterprise SSO (Okta, Azure AD, ...) |
| `dev` | No auth | Local development only |

### RBAC roles

| Role | Can do |
|------|--------|
| `owner` | All operations including tenant/key management |
| `admin` | Key management, governance, analytics |
| `editor` | Learn, recall, evaluate, compose, cancel jobs |
| `reader` | Recall, metrics, feedback, job status read |

Role is stored per API key in the DB (or mapped from a JWT claim in OIDC mode).

### Token security

- Keys are stored as **SHA-256 hashes** — plaintext is shown exactly once at creation
- Comparison uses `hmac.compare_digest` to prevent timing oracle attacks
- 60-second in-process TTL cache for DB lookups; cache is invalidated on revoke/rotate
- OIDC: JWKS keys are cached 1 hour; failed refresh keeps previous keys (availability over security for transient IdP outages)

---

## Multi-Tenancy and Data Isolation

Every storage read/write is scoped to `(tenant_id, project_id)`. The scope is set from the authenticated API key (or OIDC claims) and propagated through Python `contextvars` — it is never passed as a user-controlled parameter.

**PostgreSQL**: all queries include `AND tenant_id = :tid AND project_id = :pid` WHERE clauses. There is no code path that can read across tenant boundaries.

**JSON storage**: non-default scopes write to `{root}/{tenant}/{project}/`. Cross-scope reads return `None`.

**Test coverage**: `tests/test_security/test_tenant_isolation.py` — 12 tests verifying that tenant A cannot read, search, or list tenant B's data via any API path.

---

## Transport Security

- **TLS 1.2+** enforced by Caddy (Let's Encrypt auto-renewal)
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` header on all responses
- CORS disabled by default; explicit opt-in via `ENGRAMIA_CORS_ORIGINS`
- All outbound LLM API calls are HTTPS (enforced by provider SDK)

---

## Input Validation and Injection Prevention

- **Body size limit**: 1 MB by default (`ENGRAMIA_MAX_BODY_SIZE`)
- **Pydantic v2 validation** on all API request models (type, length, range)
- **Prompt injection mitigation**: all user content passed to LLMs is wrapped in XML delimiters (`<task>`, `<code>`, `<output>`) to prevent instruction injection
- **LIKE wildcard escaping**: `%` and `_` in pattern keys are escaped before use in SQL LIKE queries
- **Path traversal**: pattern keys containing `..` or `/` are rejected at the validation layer

---

## Data at Rest

- **PostgreSQL**: data is at rest on the host volume. Encryption at rest depends on the deployment host (Hetzner disk encryption or OS-level LUKS recommended for production).
- **JSON storage**: files on the host filesystem. Suitable for dev only; not recommended for production with sensitive data.
- **API keys**: SHA-256 hashed in DB. Original key is never logged or re-transmitted.
- **PII redaction**: the `RedactionPipeline` can be enabled to strip emails, IPs, JWTs, API keys, and credentials from pattern content before storage.

---

## Data in Transit

- All external traffic: HTTPS/TLS via Caddy
- Internal traffic (API → PostgreSQL): on Docker bridge network, no TLS by default. For production with separate DB hosts, configure `sslmode=require` in `ENGRAMIA_DATABASE_URL`.
- Outbound to LLM providers: HTTPS enforced by provider SDK

---

## Audit Logging

All security-relevant events are logged as structured JSON:

| Event | Trigger |
|-------|---------|
| `AUTH_FAILURE` | Invalid or missing token |
| `KEY_CREATED` | New API key issued |
| `KEY_REVOKED` | Key revoked |
| `KEY_ROTATED` | Key rotated |
| `QUOTA_EXCEEDED` | Pattern quota hit (HTTP 429) |
| `SCOPE_DELETED` | Tenant/project data deleted |
| `SCOPE_EXPORTED` | GDPR data export |
| `RETENTION_APPLIED` | Retention cleanup run |
| `PII_REDACTED` | PII found and redacted |

Log fields: `event`, `timestamp`, `ip`, `tenant_id`, `project_id`, `key_id`, `detail`.

---

## Rate Limiting

Per-IP, per-path, in-memory:

| Endpoint class | Default limit |
|----------------|--------------|
| Standard (learn, recall, metrics, ...) | 60 req/min |
| LLM-intensive (evaluate, compose, evolve) | 10 req/min |

For multi-instance deployments, configure an upstream rate limiter (Nginx, Caddy rate_limit, Cloudflare, AWS WAF).

---

## Error Handling

- HTTP 4xx/5xx responses never expose internal exception details, stack traces, or DB query fragments
- Error sanitization is applied in the FastAPI exception handlers
- Internal errors are logged at ERROR level with full context

---

## Secrets Management

| Secret | Storage | Rotation |
|--------|---------|----------|
| OpenAI API key | Environment variable | Manual, restart required |
| Anthropic API key | Environment variable | Manual, restart required |
| Engramia API keys | DB (hashed) | `POST /v1/keys/{id}/rotate` — zero downtime |
| PostgreSQL password | Environment variable / Docker secret | Manual |
| OIDC client secrets | Not stored (stateless JWT validation) | IdP-managed |

Secrets must never be committed to source control. Use `.env` files (gitignored) or a secrets manager (Vault, AWS Secrets Manager, Hetzner Cloud secrets).

---

## Known Limitations

See `SECURITY.md` for the full list. Key items:

1. Rate limiting is in-process — not effective for multi-instance deployments without an upstream rate limiter
2. Audit log is append-only JSON — no SIEM integration yet
3. No WAF in front of Caddy (optional: Cloudflare proxy)
4. OIDC JWKS cache is per-process — a compromised key continues to validate tokens until TTL expires (1 hour max)

---

## Security Contact

Report vulnerabilities privately to: **security@engramia.dev**

Response SLA: 72 hours acknowledgement, 30 days remediation for P0/P1.

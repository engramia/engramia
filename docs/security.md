# Security

## Implemented measures

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

## Reporting vulnerabilities

If you discover a security vulnerability, please report it responsibly via email or a private GitHub security advisory. **Do not open a public issue for security vulnerabilities.**

Contact: security@engramia.dev

## Known limitations

### 1. Prompt injection (fundamental LLM limitation)

User-supplied `task`, `code`, and `output` fields are inserted into LLM prompts. XML delimiters and explicit "disregard" instructions are applied, but **no technique can guarantee 100% prevention** of prompt injection with current LLMs.

**Recommendation:** Treat LLM outputs as untrusted. Validate results before acting on them.

### 2. Rate limiting is in-memory, single-process

In multi-worker or multi-instance deployments, each process has independent counters.

**Recommendation:** Use an external rate limiter (Redis, API gateway, WAF) in front of Engramia for production deployments.

### 3. IP identification behind reverse proxies

Rate limiting and audit logging use `request.client.host`. Behind a reverse proxy, this returns the proxy's IP.

**Recommendation:** Configure `X-Forwarded-For` headers and use uvicorn's `--proxy-headers` flag.

### 4. Dev mode (no authentication)

When `ENGRAMIA_API_KEYS` is not set, the API runs without authentication. A warning is logged at startup.

**Recommendation:** Always set `ENGRAMIA_API_KEYS` in production.

### 5. Model download verification (local embeddings)

When using `LocalEmbeddings`, models are downloaded from Hugging Face Hub without cryptographic signature verification.

**Recommendation:** Pin model versions and verify checksums in security-sensitive environments.

## OWASP ASVS compliance

Engramia targets **OWASP ASVS Level 2/3** for its security hardening. See the full [SECURITY.md](https://github.com/engramia/engramia/blob/main/SECURITY.md) in the repository for the complete security policy and production deployment checklist.

# Environment Variables

Complete reference for all Engramia environment variables, grouped by category.

---

## Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_STORAGE` | `json` | Storage backend: `json` (dev) or `postgres` (prod). |
| `ENGRAMIA_DATA_PATH` | `./engramia_data` | Root directory for JSON storage. Ignored when `ENGRAMIA_STORAGE=postgres`. |
| `ENGRAMIA_DATABASE_URL` | — | PostgreSQL connection string, e.g. `postgresql://user:pass@host:5432/db`. Required when `ENGRAMIA_STORAGE=postgres`. |

---

## LLM & Embeddings

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_LLM_PROVIDER` | `openai` | LLM backend: `openai` \| `anthropic` \| `none`. |
| `ENGRAMIA_LLM_MODEL` | `gpt-4.1` | Model name passed to the LLM provider. |
| `ENGRAMIA_LLM_TIMEOUT` | `30.0` | Timeout in seconds for LLM API calls (applies to both OpenAI and Anthropic). |
| `ENGRAMIA_LLM_CONCURRENCY` | `10` | Max parallel LLM calls across the entire process (bounded semaphore). |
| `ENGRAMIA_EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model. Set to `none` to disable semantic search. |
| `ENGRAMIA_LOCAL_EMBEDDINGS` | — | Set to any non-empty value to use `sentence-transformers` (no API key required). |
| `OPENAI_API_KEY` | — | OpenAI API key. Required when using OpenAI LLM or embeddings. |
| `ANTHROPIC_API_KEY` | — | Anthropic API key. Required when `ENGRAMIA_LLM_PROVIDER=anthropic`. |

---

## Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_AUTH_MODE` | `auto` | Auth strategy: `auto` \| `env` \| `db` \| `dev` \| `oidc`. |
| `ENGRAMIA_API_KEYS` | — | Comma-separated static API keys for `env` auth mode, e.g. `key1,key2`. |
| `ENGRAMIA_ALLOW_NO_AUTH` | — | Set to `true` to explicitly allow unauthenticated access in `dev` mode. **Never use in production.** |
| `ENGRAMIA_ENVIRONMENT` | — | Deployment environment label (`local`, `development`, `staging`, `production`). Used to block `ENGRAMIA_AUTH_MODE=dev` in non-local environments. |
| `ENGRAMIA_ENV_AUTH_ROLE` | `owner` | Role assigned to requests authenticated via `env` auth mode (`ENGRAMIA_API_KEYS`). Valid values: `owner` \| `admin` \| `editor` \| `reader`. Defaults to `owner` for backward compatibility with single-key deployments. Set to `reader` or `editor` to limit the scope of static keys in production. |
| `ENGRAMIA_BOOTSTRAP_TOKEN` | — | Secret token required to call `POST /v1/keys/bootstrap` (the first-ever owner key creation). Must be set before deploying to production. Without it the bootstrap endpoint is disabled. Minimum 32 characters recommended. |

**Auth mode behaviour:**

| Mode | Behaviour |
|------|-----------|
| `auto` | DB auth if `ENGRAMIA_DATABASE_URL` is set, otherwise env-var keys. |
| `env` | Always use `ENGRAMIA_API_KEYS` (backward compatible). |
| `db` | Always use DB key table (`api_keys`). Requires `ENGRAMIA_DATABASE_URL`. |
| `dev` | No auth. Requires `ENGRAMIA_ALLOW_NO_AUTH=true` as explicit opt-in. |

---

## Security & Networking

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_CORS_ORIGINS` | — | Comma-separated allowed CORS origins. CORS is disabled when unset. Use `*` only in dev. |
| `ENGRAMIA_RATE_LIMIT_DEFAULT` | `60` | Max requests per minute for standard endpoints (per IP). |
| `ENGRAMIA_RATE_LIMIT_EXPENSIVE` | `10` | Max requests per minute for LLM-intensive endpoints (`/evaluate`, `/compose`, `/evolve`). |
| `ENGRAMIA_RATE_LIMIT_PER_KEY` | `120` | Max requests per minute per API key across all paths. |
| `ENGRAMIA_MAX_BODY_SIZE` | `1048576` | Max request body size in bytes (default 1 MB). |
| `ENGRAMIA_MAX_LLM_RESPONSE` | `20000` | Max characters of LLM-generated response text before truncation. |
| `ENGRAMIA_REDACTION` | `true` | PII/secrets redaction at rest. Set to `false`/`0`/`no` to disable (dev only — **not for production**). |
| `ENGRAMIA_MAINTENANCE` | — | Set to `true` / `1` to activate maintenance mode. Returns `503` on all endpoints except `/v1/health`. |

---

## OIDC Authentication (Enterprise SSO)

Activated when `ENGRAMIA_AUTH_MODE=oidc`. Requires `pip install "engramia[oidc]"`.

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_OIDC_ISSUER` | — | **Required.** OIDC issuer URL, e.g. `https://company.okta.com/oauth2/default`. JWKS fetched from `{issuer}/.well-known/jwks.json`. |
| `ENGRAMIA_OIDC_AUDIENCE` | — | **Required.** Expected `aud` claim in the JWT. |
| `ENGRAMIA_OIDC_ROLE_CLAIM` | `engramia_role` | JWT claim that maps to an Engramia role (`owner`/`admin`/`editor`/`reader`). |
| `ENGRAMIA_OIDC_DEFAULT_ROLE` | `reader` | Fallback role when the role claim is absent. |
| `ENGRAMIA_OIDC_TENANT_CLAIM` | — | JWT claim for `tenant_id`. When unset, `default` tenant is used. |
| `ENGRAMIA_OIDC_PROJECT_CLAIM` | — | JWT claim for `project_id`. When unset, `default` project is used. |

---

## Async Jobs

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_JOB_POLL_INTERVAL` | `2.0` | Worker poll interval in seconds. |
| `ENGRAMIA_JOB_MAX_CONCURRENT` | `3` | Maximum concurrent job executions. |

---

## Observability (Telemetry)

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_JSON_LOGS` | `false` | Set to `true` for structured JSON log output (recommended in production). |
| `ENGRAMIA_TELEMETRY` | `false` | Set to `true` to enable OpenTelemetry tracing. |
| `ENGRAMIA_METRICS` | `false` | Set to `true` to mount the Prometheus `/metrics` endpoint. |
| `ENGRAMIA_METRICS_TOKEN` | — | Bearer token required to access `/metrics`. When set, requests without a matching `Authorization: Bearer <token>` header receive `401`. Required when `ENGRAMIA_METRICS=true` in production — without it the metrics endpoint is publicly accessible. |
| `ENGRAMIA_OTEL_SERVICE_NAME` | `engramia-api` | OTEL service name. |
| `ENGRAMIA_OTEL_ENDPOINT` | `http://localhost:4317` | OTEL collector gRPC endpoint. |

---

## Server

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_HOST` | `0.0.0.0` | Uvicorn bind host. |
| `ENGRAMIA_PORT` | `8000` | Uvicorn bind port. |

---

## SDK & Client

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_API_URL` | — | API base URL for SDK bridge mode (e.g. `https://api.engramia.dev`). |
| `ENGRAMIA_API_KEY` | — | Single API key for SDK bridge mode. |

---

## Internal / Testing

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_SKIP_AUTO_APP` | `0` | Set to `1` to prevent the module-level `app = create_app()` from running on import (used in tests). |

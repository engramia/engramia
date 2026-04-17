# REST API

Engramia provides a FastAPI-based REST API with Swagger UI, Bearer auth, rate limiting, and security headers.

## Running the server

=== "Docker (recommended)"

    ```bash
    # JSON storage (development)
    docker compose up

    # PostgreSQL storage (production)
    ENGRAMIA_STORAGE=postgres \
    ENGRAMIA_DATABASE_URL=postgresql://user:pass@localhost:5432/brain \
    OPENAI_API_KEY=sk-... \
    docker compose up
    ```

=== "CLI"

    ```bash
    pip install "engramia[openai,api]"
    engramia serve --host 0.0.0.0 --port 8000
    ```

=== "Python"

    ```python
    import uvicorn
    from engramia.api.app import create_app

    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)
    ```

Swagger UI is available at `http://localhost:8000/docs`.

## Configuration

| Environment variable | Default | Description |
|---------------------|---------|-------------|
| `ENGRAMIA_STORAGE` | `json` | `json` or `postgres` |
| `ENGRAMIA_DATA_PATH` | `./engramia_data` | Path for JSON storage |
| `ENGRAMIA_DATABASE_URL` | — | PostgreSQL URL (postgres mode only) |
| `ENGRAMIA_LLM_PROVIDER` | `openai` | LLM provider (`openai` or `anthropic`) |
| `ENGRAMIA_LLM_MODEL` | `gpt-4.1` | Model ID |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `ENGRAMIA_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `ENGRAMIA_API_KEYS` | *(empty)* | Bearer tokens (empty = dev mode, no auth) |
| `ENGRAMIA_PORT` | `8000` | Port |

### Security configuration

| Environment variable | Default | Description |
|---------------------|---------|-------------|
| `ENGRAMIA_CORS_ORIGINS` | *(empty)* | Allowed CORS origins (empty = CORS disabled) |
| `ENGRAMIA_RATE_LIMIT_DEFAULT` | `60` | Max requests/min for standard endpoints |
| `ENGRAMIA_RATE_LIMIT_EXPENSIVE` | `10` | Max requests/min for LLM-intensive endpoints |
| `ENGRAMIA_MAX_BODY_SIZE` | `1048576` | Max request body size in bytes (1 MB) |

## Authentication

When `ENGRAMIA_API_KEYS` is set, all endpoints require a Bearer token:

```bash
curl -H "Authorization: Bearer my-secret-key" http://localhost:8000/v1/metrics
```

!!! warning
    When `ENGRAMIA_API_KEYS` is empty, the API runs without authentication. This is intended for local development only. Always set API keys in production.

## Endpoints

All endpoints are under the `/v1/` prefix.

### POST /v1/learn

Store a success pattern.

```bash
curl -X POST http://localhost:8000/v1/learn \
  -H "Content-Type: application/json" \
  -d '{"task": "Parse CSV", "code": "import csv...", "eval_score": 8.5}'
```

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `task` | `string` | Yes | Task description |
| `code` | `string` | Yes | Code/solution |
| `eval_score` | `number` | Yes | Quality score (0–10) |
| `output` | `string` | No | Agent output |

---

### POST /v1/recall

Find relevant patterns via semantic search.

```bash
curl -X POST http://localhost:8000/v1/recall \
  -H "Content-Type: application/json" \
  -d '{"task": "Read CSV and compute averages", "limit": 3}'
```

**Request body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `task` | `string` | Yes | — | Task to search for |
| `limit` | `integer` | No | `5` | Max results |

---

### POST /v1/evaluate

Run multi-evaluator scoring.

```bash
curl -X POST http://localhost:8000/v1/evaluate \
  -H "Content-Type: application/json" \
  -d '{"task": "Parse CSV", "code": "import csv...", "num_evals": 3}'
```

---

### POST /v1/compose

Compose a multi-stage pipeline.

```bash
curl -X POST http://localhost:8000/v1/compose \
  -H "Content-Type: application/json" \
  -d '{"task": "Fetch data, analyze, write report"}'
```

---

### POST /v1/aging

Run pattern aging (decay + prune).

```bash
curl -X POST http://localhost:8000/v1/aging
```

---

### POST /v1/feedback/decay

Run feedback decay.

```bash
curl -X POST http://localhost:8000/v1/feedback/decay
```

---

### POST /v1/evolve

Generate an improved prompt based on recurring failure patterns.

```bash
curl -X POST http://localhost:8000/v1/evolve \
  -H "Content-Type: application/json" \
  -d '{"role": "coder", "current_prompt": "You are a coder..."}'
```

---

### POST /v1/analyze-failures

Cluster recurring failure patterns.

```bash
curl -X POST http://localhost:8000/v1/analyze-failures \
  -H "Content-Type: application/json" \
  -d '{"min_count": 2}'
```

---

### POST /v1/skills/register

Register skill tags on a pattern.

```bash
curl -X POST http://localhost:8000/v1/skills/register \
  -H "Content-Type: application/json" \
  -d '{"pattern_key": "patterns/abc123", "skills": ["csv_parsing", "statistics"]}'
```

---

### POST /v1/skills/search

Search patterns by skill tags.

```bash
curl -X POST http://localhost:8000/v1/skills/search \
  -H "Content-Type: application/json" \
  -d '{"skills": ["csv_parsing"], "match_all": true}'
```

---

### GET /v1/feedback

Get top recurring feedback patterns.

```bash
curl http://localhost:8000/v1/feedback?limit=5
```

---

### GET /v1/metrics

Get memory statistics.

```bash
curl http://localhost:8000/v1/metrics
```

---

### GET /v1/health

Health check with storage type.

```bash
curl http://localhost:8000/v1/health
```

---

### DELETE /v1/patterns/{key}

Delete a pattern by key. Permission: `patterns:delete` (admin+).

```bash
curl -X DELETE http://localhost:8000/v1/patterns/patterns%2Fabc123
```

### GET /v1/export

Export all patterns in the current scope. Permission: `export`.

Returns `{"records": [...], "count": N}` — same format accepted by `POST /v1/import`.

### POST /v1/import

Bulk-import patterns. Permission: `import`. Supports `Prefer: respond-async`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `records` | `list` | yes | Export records (max 10,000) |
| `overwrite` | `bool` | no | Overwrite existing keys (default `false`) |

### GET /v1/health/deep

Deep health check — probes storage, LLM, and embedding connectivity. Returns `status: ok|degraded|error`, per-check results, and uptime.

### GET /v1/version

Public endpoint (no auth). Returns `app_version`, `api_version`, `git_commit`, `build_time`.

---

## Key Management (`/v1/keys`)

Requires DB auth mode (`ENGRAMIA_AUTH_MODE=db` or `auto` with `ENGRAMIA_DATABASE_URL`).

### POST /v1/keys/bootstrap

One-time setup. Creates default tenant, project, and owner key. Requires `ENGRAMIA_BOOTSTRAP_TOKEN` env var.

### POST /v1/keys

Create a new API key. Permission: `keys:create` (admin+). Role hierarchy enforced.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `str` | yes | Display name (1-100 chars) |
| `role` | `str` | no | `owner`/`admin`/`editor`/`reader` (default `editor`) |
| `max_patterns` | `int` | no | Pattern quota (inherit from project if unset) |
| `expires_at` | `str` | no | ISO-8601 expiration |

### GET /v1/keys

List API keys for current project. Permission: `keys:list`.

### DELETE /v1/keys/{id}

Revoke an API key. Permission: `keys:revoke`.

### POST /v1/keys/{id}/rotate

Rotate key (generates new secret). Permission: `keys:rotate`.

---

## Analytics (`/v1/analytics`)

### POST /v1/analytics/rollup

Compute ROI rollup for a time window. Permission: `analytics:rollup`. Supports async.

| Field | Type | Description |
|-------|------|-------------|
| `window` | `str` | `hourly` / `daily` / `weekly` |

Response: composite ROI score (0-10), recall/learn summaries, percentiles.

### GET /v1/analytics/rollup/{window}

Fetch pre-computed rollup. Permission: `analytics:read`. Returns 404 if not yet computed.

### GET /v1/analytics/events

Raw ROI events. Permission: `analytics:read`. Query params: `limit` (1-1000), `since` (Unix timestamp).

---

## Jobs (`/v1/jobs`)

### GET /v1/jobs

List async jobs. Permission: `jobs:list`. Query params: `status`, `limit` (1-100).

### GET /v1/jobs/{id}

Get job status and result. Permission: `jobs:read`. Returns 404 if not found.

### POST /v1/jobs/{id}/cancel

Cancel a pending job. Permission: `jobs:cancel`.

---

## Data Governance (`/v1/governance`)

### GET /v1/governance/export

Stream patterns as NDJSON (GDPR Art. 20). Permission: `export`. Optional `classification` query filter.

### GET /v1/governance/retention

Get effective retention policy. Permission: `governance:read`.

### PUT /v1/governance/retention

Set retention policy (days). Permission: `governance:write`. Requires DB auth.

### POST /v1/governance/retention/apply

Apply retention — delete expired patterns. Permission: `governance:admin`. Supports async.

### PUT /v1/governance/patterns/{key}/classify

Update data classification (`public`/`internal`/`confidential`). Permission: `governance:write`.

### DELETE /v1/governance/projects/{project_id}

Delete ALL data for a project (GDPR Art. 17). Permission: `governance:delete`. Irreversible.

### DELETE /v1/governance/tenants/{tenant_id}

Delete ALL data for a tenant. Owner only. Irreversible.

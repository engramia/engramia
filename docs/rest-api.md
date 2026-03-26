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
| `ENGRAMIA_DATA_PATH` | `./brain_data` | Path for JSON storage |
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

Delete a pattern by key.

```bash
curl -X DELETE http://localhost:8000/v1/patterns/patterns%2Fabc123
```

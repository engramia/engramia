# Deployment

## Docker

### JSON storage (development)

```bash
docker compose up
```

### PostgreSQL storage (production)

```bash
ENGRAMIA_STORAGE=postgres \
ENGRAMIA_DATABASE_URL=postgresql://brain:brain@pgvector:5432/brain \
OPENAI_API_KEY=sk-... \
ENGRAMIA_API_KEYS=your-secret-key \
docker compose up
```

Apply database migrations on first run:

```bash
docker compose exec brain-api alembic upgrade head
```

### Docker image details

- Multi-stage build (builder + runtime)
- Non-root user (`brain:1001`)
- Default port: 8000

## PostgreSQL + pgvector

### Setup without Docker

```bash
pip install "engramia[openai,postgres]"
```

```python
from engramia import Memory
from engramia.providers import OpenAIProvider, OpenAIEmbeddings, PostgresStorage

storage = PostgresStorage(database_url="postgresql://user:pass@localhost:5432/engramia")
mem = Memory(
    llm=OpenAIProvider(),
    embeddings=OpenAIEmbeddings(),
    storage=storage,
)
```

### Database requirements

- PostgreSQL 15+
- pgvector extension installed
- Run Alembic migrations: `alembic upgrade head`

The migration creates:

- `engramia_data` table for pattern storage
- `memory_embeddings` table with pgvector column
- HNSW index for fast approximate nearest neighbor search

## Production checklist

### Authentication

Always set `ENGRAMIA_API_KEYS` with strong, randomly generated tokens:

```bash
ENGRAMIA_API_KEYS=your-secret-key-1,your-secret-key-2
```

!!! warning
    Without `ENGRAMIA_API_KEYS`, the API runs in dev mode with no authentication.

### Rate limiting

Default rate limits are applied per-IP:

| Endpoint type | Default limit |
|---------------|--------------|
| Standard endpoints | 60 req/min |
| LLM-intensive endpoints (evaluate, compose, evolve) | 10 req/min |

!!! note
    Rate limiting is in-memory and per-process. For multi-instance deployments, use an external rate limiter (Redis, API gateway, WAF) in front of Engramia.

### Reverse proxy

If running behind nginx or a load balancer, configure `X-Forwarded-For` headers and use uvicorn's `--proxy-headers` flag so rate limiting and audit logging use the real client IP.

### CORS

CORS is disabled by default. To enable:

```bash
ENGRAMIA_CORS_ORIGINS=https://your-app.com,https://admin.your-app.com
```

### Body size limit

Default max request body is 1 MB. Adjust if needed:

```bash
ENGRAMIA_MAX_BODY_SIZE=2097152  # 2 MB
```

### Periodic maintenance

Schedule these to run periodically (e.g., weekly cron):

```bash
# Via CLI
engramia aging --path ./engramia_data

# Via API
curl -X POST http://localhost:8000/v1/aging -H "Authorization: Bearer $KEY"
curl -X POST http://localhost:8000/v1/feedback/decay -H "Authorization: Bearer $KEY"
```

### Monitoring

- **Health check:** `GET /v1/health` returns storage type and status
- **Metrics:** `GET /v1/metrics` returns run counts, success rate, pattern count
- **Audit log:** Structured JSON logging for security events (auth failures, deletions, rate limits)

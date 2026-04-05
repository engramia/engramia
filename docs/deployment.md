# Deployment

> **Quick reference:** This is the single consolidated deployment guide for Engramia.
> It covers Docker Compose (dev + production), Kubernetes, database migrations,
> backup/restore, and rollback procedures.
>
> Related docs: [Environment Variables](environment-variables.md) · [Production Hardening](production-hardening.md) · [Backup & Restore](backup-restore.md)

---

## Docker

### JSON storage (development)

```bash
docker compose up
```

### PostgreSQL storage (production)

```bash
ENGRAMIA_STORAGE=postgres \
ENGRAMIA_DATABASE_URL=postgresql://engramia:engramia@pgvector:5432/engramia \
OPENAI_API_KEY=sk-... \
ENGRAMIA_API_KEYS=your-secret-key \
docker compose up
```

Apply database migrations on first run:

```bash
docker compose exec engramia-api alembic upgrade head
```

### Docker image details

- Multi-stage build (builder + runtime)
- Non-root user (`engramia:1001`)
- Default port: 8000

---

## Kubernetes

A reference manifest is provided at `deploy/k8s/engramia.yaml`. It creates a `engramia` namespace, ConfigMap, Secret, Deployment, Service, and HPA.

### Quick start

```bash
# 1. Edit secrets in deploy/k8s/engramia.yaml (ENGRAMIA_DATABASE_URL, OPENAI_API_KEY, etc.)
kubectl apply -f deploy/k8s/engramia.yaml

# 2. Apply database migrations
kubectl -n engramia exec deploy/engramia-api -- alembic upgrade head

# 3. Verify health
kubectl -n engramia port-forward svc/engramia-api 8000:8000
curl http://localhost:8000/v1/health/deep
```

### Running migrations in K8s

```bash
# Run as a one-off Job (recommended for production)
kubectl -n engramia exec deploy/engramia-api -- alembic upgrade head

# Check current revision
kubectl -n engramia exec deploy/engramia-api -- alembic current
```

### Zero-downtime update

```bash
# 1. Update the image tag in the Deployment
kubectl -n engramia set image deployment/engramia-api engramia-api=ghcr.io/engramia/engramia:0.6.6

# 2. Watch the rollout
kubectl -n engramia rollout status deployment/engramia-api

# 3. Rollback if needed (see Rollback section below)
kubectl -n engramia rollout undo deployment/engramia-api
```

---

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

### Async job processing

Async jobs (via `Prefer: respond-async`) use a lightweight DB-backed queue
(`SELECT … FOR UPDATE SKIP LOCKED` on PostgreSQL, in-memory fallback for
JSON storage). Crash recovery resets orphaned jobs on startup.

!!! warning "Best-effort durability"
    Engramia async jobs are **best-effort**.  Jobs are not guaranteed to
    complete exactly once.  There are no durable retries, no dead-letter
    queue, and no backpressure.  If the worker process is killed mid-job,
    the job is retried after the next restart — but only once.
    For Celery-level guarantees (at-least-once delivery, DLQ, retry
    policies), wrap Engramia behind a task queue such as Celery or ARQ.

### Monitoring

- **Health check:** `GET /v1/health` returns storage type and status
- **Metrics:** `GET /v1/metrics` returns run counts, success rate, pattern count
- **Prometheus:** `GET /metrics` (opt-in via `ENGRAMIA_METRICS=true`, requires `prometheus_client`)
- **Audit log:** Structured JSON logging for security events (auth failures, deletions, rate limits)

### Maintenance mode

Set `ENGRAMIA_MAINTENANCE=true` to put the API into maintenance mode. All endpoints except `/v1/health` and `/v1/health/deep` return `503 Service Unavailable`. Use this before applying migrations or deploying a new version.

```bash
# Enter maintenance mode (update .env or pass directly)
ENGRAMIA_MAINTENANCE=true docker compose up -d

# Exit maintenance mode
ENGRAMIA_MAINTENANCE=false docker compose up -d
```

---

## Backup and restore

### JSON storage

```bash
# Backup — copy the data directory
cp -r ./engramia_data ./engramia_data_backup_$(date +%Y%m%d)

# Restore
cp -r ./engramia_data_backup_20260101 ./engramia_data
```

Export via CLI (portable across storage backends):

```bash
engramia export --path ./engramia_data --output backup.json
```

Import:

```bash
engramia import --path ./engramia_data --input backup.json
```

### PostgreSQL storage

Always take a dump **before** running migrations:

```bash
# Dump
pg_dump $ENGRAMIA_DATABASE_URL -Fc -f engramia_$(date +%Y%m%d).dump

# Restore
pg_restore -d $ENGRAMIA_DATABASE_URL -c engramia_20260101.dump
```

With Docker Compose:

```bash
# Dump from running container
docker compose exec pgvector pg_dump -U engramia engramia -Fc > engramia_$(date +%Y%m%d).dump

# Restore into running container
cat engramia_20260101.dump | docker compose exec -T pgvector pg_restore -U engramia -d engramia -c
```

---

## Rollback strategy

### Docker image rollback

Each GitHub Actions release tags the image as `ghcr.io/engramia/engramia:<version>`. To roll back:

```bash
# On the production host
cd /opt/engramia

# 1. (Optional) Enter maintenance mode first
echo "ENGRAMIA_MAINTENANCE=true" >> .env && docker compose up -d

# 2. Take a database dump before rolling back
pg_dump $ENGRAMIA_DATABASE_URL -Fc -f pre_rollback_$(date +%Y%m%d%H%M).dump

# 3. Pin the image to the previous version in docker-compose.prod.yml
#    Change: image: ghcr.io/engramia/engramia:0.6.0
#    To:     image: ghcr.io/engramia/engramia:0.5.9

# 4. Downgrade the Alembic migration (if the new version added one)
docker compose -f docker-compose.prod.yml exec engramia-api alembic downgrade -1

# 5. Restart with the old image
docker compose -f docker-compose.prod.yml up -d

# 6. Exit maintenance mode
sed -i '/ENGRAMIA_MAINTENANCE/d' .env && docker compose up -d
```

### Alembic migration rollback

```bash
# Show current migration head
docker compose exec engramia-api alembic current

# Roll back one revision
docker compose exec engramia-api alembic downgrade -1

# Roll back to a specific revision
docker compose exec engramia-api alembic downgrade <revision_id>

# List all revisions
docker compose exec engramia-api alembic history
```

!!! warning
    Always take a `pg_dump` before running `alembic downgrade`. Downgrade scripts
    may drop columns or tables that cannot be recovered without a backup.

---

## Secret management

### Current approach

Secrets are passed via environment variables loaded from `.env` files by Docker Compose:

| Secret | Variable | Notes |
|--------|----------|-------|
| Database password | `ENGRAMIA_DATABASE_URL` | Full connection string |
| OpenAI API key | `OPENAI_API_KEY` | Required for LLM + embeddings |
| Anthropic API key | `ANTHROPIC_API_KEY` | If using Anthropic provider |
| Bootstrap token | `ENGRAMIA_BOOTSTRAP_TOKEN` | One-time, can be unset after use |
| Metrics token | `ENGRAMIA_METRICS_TOKEN` | Protects `/metrics` endpoint |
| Stripe keys | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Billing (Phase 6) |

**Best practices for the current setup:**

1. Never commit `.env` to git (`.gitignore` already excludes it)
2. Use separate `.env` files per environment (dev, staging, prod)
3. Restrict file permissions: `chmod 600 .env`
4. Unset `ENGRAMIA_BOOTSTRAP_TOKEN` after initial key creation
5. Rotate API keys periodically via `POST /v1/keys/{id}/rotate`

### Production (Hetzner VM)

Secrets are stored in `/opt/engramia/.env` on the production VM, accessible only to root. Docker Compose reads this file at container startup.

### Future: External secret managers (roadmap)

For enterprise deployments requiring centralized secret management, audit trails, and automatic rotation, integration with external providers (HashiCorp Vault, AWS Secrets Manager, Azure Key Vault) is planned. See the roadmap for timeline.

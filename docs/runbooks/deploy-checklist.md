# Deployment Runbook

> **Ops reference:** Step-by-step procedures for deploying, verifying, and rolling back Engramia in production.
> For background on configuration options see [Environment Variables](../environment-variables.md).
> For backup procedures see [Backup & Restore](../backup-restore.md).

---

## Prerequisites

### System requirements

- Docker 24+ and Docker Compose v2 (`docker compose`, not `docker-compose`)
- Access to the production VM via SSH
- `DEPLOY_PATH` on the VM contains `docker-compose.prod.yml` and `.env`

### Required environment variables (`.env`)

| Variable | Purpose |
|---|---|
| `ENGRAMIA_DATABASE_URL` | PostgreSQL connection string |
| `ENGRAMIA_API_KEYS` | Comma-separated bearer tokens for API auth |
| `OPENAI_API_KEY` | LLM + embedding provider |
| `ENGRAMIA_AUTH_MODE` | `db` for production (multi-tenant) |
| `ENGRAMIA_BOOTSTRAP_TOKEN` | One-time admin key — unset after first use |

Optional but recommended:

| Variable | Purpose |
|---|---|
| `STRIPE_SECRET_KEY` | Billing (Phase 6) |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook verification |
| `ENGRAMIA_METRICS=true` | Enable Prometheus `/metrics` endpoint |
| `ENGRAMIA_METRICS_TOKEN` | Bearer token protecting `/metrics` |
| `ENGRAMIA_JSON_LOGS=true` | Structured JSON log output |

### Database

PostgreSQL 15+ with the `pgvector` extension. The `pgvector` Docker service in
`docker-compose.prod.yml` includes this. Run migrations once before first start:

```bash
docker compose -f docker-compose.prod.yml exec engramia-api alembic upgrade head
```

---

## Standard deployment procedure

This is the procedure the CI/CD pipeline executes automatically on release. Run
it manually if deploying a hotfix or if CI is unavailable.

```bash
# 1. SSH into the production VM
ssh deploy@<host>
cd /opt/engramia

# 2. Set the target version
export IMAGE_TAG=0.6.1   # without leading 'v'

# 3. (Optional) Enable maintenance mode — prevents traffic during migration
echo "ENGRAMIA_MAINTENANCE=true" >> .env
docker compose -f docker-compose.prod.yml up -d engramia-api

# 4. Pull the new image
echo "$GHCR_TOKEN" | docker login ghcr.io -u <actor> --password-stdin
IMAGE_TAG=$IMAGE_TAG docker compose -f docker-compose.prod.yml pull engramia-api

# 5. Restart with the new image
IMAGE_TAG=$IMAGE_TAG docker compose -f docker-compose.prod.yml up -d engramia-api caddy

# 6. Run database migrations
IMAGE_TAG=$IMAGE_TAG docker compose -f docker-compose.prod.yml exec -T engramia-api alembic upgrade head

# 7. Remove maintenance mode
sed -i '/ENGRAMIA_MAINTENANCE/d' .env
docker compose -f docker-compose.prod.yml up -d engramia-api

# 8. Prune old images
docker image prune -f
```

---

## Health check verification

Run these after every deploy before closing the deployment window.

```bash
BASE=https://api.engramia.dev

# Version matches the release tag
curl -sf $BASE/v1/version | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['app_version'])"

# Shallow health (always fast)
curl -sf $BASE/v1/health | python3 -m json.tool

# Deep health — probes storage, LLM, embeddings, Stripe, and migration version
curl -sf $BASE/v1/health/deep | python3 -m json.tool
```

Expected output for a healthy deployment:

```json
{
  "status": "ok",
  "version": "0.6.1",
  "uptime_seconds": 12.4,
  "checks": {
    "storage": {"status": "ok", "latency_ms": 3.1},
    "llm": {"status": "ok", "latency_ms": 820.5},
    "embedding": {"status": "ok", "latency_ms": 210.3},
    "stripe": {"status": "ok", "latency_ms": 145.2},
    "migration": {"status": "ok", "latency_ms": 2.0}
  }
}
```

A `"status": "degraded"` response (HTTP 200) means at least one non-critical
probe failed. A `"status": "error"` response (HTTP 503) means all probes failed
— investigate before routing traffic.

---

## Zero-downtime deployment notes

The production `docker-compose.prod.yml` runs a single API container. True
zero-downtime requires either:

- **Kubernetes** — use `kubectl rollout` with replica counts ≥ 2 (see
  `deploy/k8s/engramia.yaml`)
- **Docker Compose with Caddy** — Caddy buffers connections; the restart gap
  is typically < 2 s, acceptable for most SLA targets

For migrations that add columns or tables (non-destructive), the old container
can run against the new schema without errors. For migrations that drop columns,
enable maintenance mode first (step 3 above).

---

## Rollback procedure

Use this when a deploy causes regressions or the deep health check returns
`"error"`.

```bash
ssh deploy@<host>
cd /opt/engramia

# 1. Enter maintenance mode immediately
echo "ENGRAMIA_MAINTENANCE=true" >> .env
docker compose -f docker-compose.prod.yml up -d engramia-api

# 2. Take a database snapshot before touching migrations
docker compose -f docker-compose.prod.yml exec pgvector \
  pg_dump -U engramia engramia -Fc > pre_rollback_$(date +%Y%m%d%H%M).dump

# 3. Identify the previous working version (check release tags or git log)
export PREV_TAG=0.6.0

# 4. Downgrade migrations introduced by the bad version (if any)
docker compose -f docker-compose.prod.yml exec -T engramia-api alembic downgrade -1

# 5. Update IMAGE_TAG and restart
sed -i "s/IMAGE_TAG=.*/IMAGE_TAG=$PREV_TAG/" .env   # if pinned in .env
# OR edit docker-compose.prod.yml to pin the image tag directly

IMAGE_TAG=$PREV_TAG docker compose -f docker-compose.prod.yml up -d engramia-api caddy

# 6. Verify the rollback succeeded
curl -sf https://api.engramia.dev/v1/version
curl -sf https://api.engramia.dev/v1/health/deep | python3 -m json.tool

# 7. Exit maintenance mode
sed -i '/ENGRAMIA_MAINTENANCE/d' .env
docker compose -f docker-compose.prod.yml up -d engramia-api
```

---

## Database migration rollback

```bash
# Show current migration head
docker compose -f docker-compose.prod.yml exec -T engramia-api alembic current

# List all revisions (newest first)
docker compose -f docker-compose.prod.yml exec -T engramia-api alembic history --verbose

# Roll back one revision
docker compose -f docker-compose.prod.yml exec -T engramia-api alembic downgrade -1

# Roll back to a specific revision ID
docker compose -f docker-compose.prod.yml exec -T engramia-api alembic downgrade 012

# Roll back all the way to an empty database
docker compose -f docker-compose.prod.yml exec -T engramia-api alembic downgrade base
```

!!! warning
    Always take a `pg_dump` before running `alembic downgrade`. Some downgrade
    scripts drop columns or tables; data lost this way cannot be recovered
    without a backup.

---

## Troubleshooting common issues

### Container exits immediately after start

```bash
# Inspect the last 100 log lines
docker compose -f docker-compose.prod.yml logs --tail=100 engramia-api
```

Common causes:

| Symptom | Likely cause | Fix |
|---|---|---|
| `ENGRAMIA_DATABASE_URL not set` | Missing env var | Add to `.env` |
| `connection refused` on startup | pgvector not ready | Wait for `pg_isready`, or add `depends_on` health check |
| `alembic.util.exc.CommandError` | Migration conflict | Run `alembic current` to check state |
| `ModuleNotFoundError: stripe` | Missing optional dep | Rebuild image or use `pip install engramia[billing]` |

### Deep health returns `storage: error`

```bash
# Check pgvector container is healthy
docker compose -f docker-compose.prod.yml ps pgvector

# Connect manually to verify
docker compose -f docker-compose.prod.yml exec pgvector \
  psql -U engramia -c "SELECT version();"
```

### Deep health returns `migration: error`

The running container reports a different migration revision than the code
expects. This usually means migrations were not applied after the last deploy.

```bash
docker compose -f docker-compose.prod.yml exec -T engramia-api alembic upgrade head
```

### Deep health returns `stripe: error`

Stripe API is unreachable or the secret key is invalid.

```bash
# Verify STRIPE_SECRET_KEY is set and starts with sk_live_ or sk_test_
grep STRIPE_SECRET_KEY .env

# Test reachability from the VM
curl -sf https://api.stripe.com/v1/
```

### API returns 503 for all endpoints

If `ENGRAMIA_MAINTENANCE=true` is set in `.env`, all endpoints except
`/v1/health` and `/v1/health/deep` return 503. Remove the variable and restart:

```bash
sed -i '/ENGRAMIA_MAINTENANCE/d' .env
docker compose -f docker-compose.prod.yml up -d engramia-api
```

### Rate limit errors (429) under load

The default rate limit is 60 req/min per IP for standard endpoints and
10 req/min for LLM-intensive endpoints. Adjust via:

```bash
ENGRAMIA_RATE_LIMIT_DEFAULT=120
ENGRAMIA_RATE_LIMIT_EXPENSIVE=20
```

Note: Rate limiting is per-process and in-memory. For multi-instance
deployments, configure an external rate limiter upstream (API gateway, WAF).

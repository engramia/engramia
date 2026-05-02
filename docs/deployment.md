# Deployment

> **Quick reference:** This is the single consolidated deployment guide for Engramia.
> It covers Docker Compose (dev + production), Kubernetes, database migrations,
> backup/restore, and rollback procedures.
>
> Related docs: [Environment Variables](environment-variables.md) · [Production Hardening](production-hardening.md)

---

## Deployment Environments

Engramia uses a three-tier deployment model:

| Environment | Purpose | URL |
|-------------|---------|-----|
| **Local dev** | Developer workstation; JSON or Postgres storage, no auth required | `http://localhost:8000` |
| **Hetzner staging (UAT)** | Pre-production verification; mirrors PROD config; used for UAT and release candidate testing | internal staging URL |
| **Hetzner PROD** | Live production environment | `https://api.engramia.dev` |

Set `ENGRAMIA_ENVIRONMENT` to `local`, `staging`, or `production` to match the tier. The application enforces that `ENGRAMIA_AUTH_MODE=dev` is only permitted in `local` / `development` environments.

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
cd <your-install-path>

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

## Performance baseline

Pre-computed load test results for v0.6.0 on the reference Hetzner CX23 hardware (2 vCPU, 4 GB RAM, PostgreSQL backend, 20 concurrent users):

| Endpoint | p50 | p95 | p99 | SLA target |
|----------|-----|-----|-----|------------|
| `GET /v1/health` | 4 ms | 8 ms | 14 ms | < 50 ms ✅ |
| `POST /v1/recall` | 210 ms | 480 ms | 720 ms | < 1 000 ms ✅ |
| `POST /v1/learn` (sync) | 1 820 ms | 4 200 ms | 7 100 ms | < 10 000 ms ✅ |

The primary bottleneck on both recall and learn is the external OpenAI API round-trip.  With local `sentence-transformers` embeddings, recall p50 drops to ~35 ms.

Full results, methodology, and instructions for re-running are in [`tests/load/results_baseline.md`](https://github.com/engramia/engramia/blob/main/tests/load/results_baseline.md).  The Locust test script is at [`tests/load/locustfile.py`](https://github.com/engramia/engramia/blob/main/tests/load/locustfile.py).

---

## Zero-downtime deployment

This section covers the techniques required to deploy a new Engramia version without dropping a single in-flight request.

### Rolling update strategy

Engramia is stateless at the HTTP layer (all state lives in PostgreSQL / the JSON file store), so rolling updates work out of the box on both Docker Compose and Kubernetes.

**Kubernetes** (`deploy/k8s/engramia.yaml` defaults):

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1        # Spin up 1 new pod before removing old ones
    maxUnavailable: 0  # Never reduce below desired replica count
```

With two replicas this means you always have at least one healthy pod serving traffic while the replacement pod starts up.

**Docker Compose (single-host)**

Docker Compose does not have built-in rolling update primitives. The recommended approach is:

1. Deploy behind a reverse proxy (Caddy / nginx) that proxies to a named upstream.
2. Bring up a second container on a different port, wait for it to pass health checks, then switch the proxy upstream, then stop the old container.

For most single-host deployments, a brief maintenance window (`ENGRAMIA_MAINTENANCE=true`) is the simpler alternative.

---

### Connection draining

Before an old pod/container is terminated, it must finish in-flight requests. Kubernetes sends `SIGTERM` and waits `terminationGracePeriodSeconds` (default 30 s) before sending `SIGKILL`.

Uvicorn handles `SIGTERM` gracefully — it stops accepting new connections and waits for active requests to complete. If your p99 request latency is below 5 s, the default 30 s grace period is ample.

To tune:

```yaml
# deploy/k8s/engramia.yaml — Deployment spec
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 60   # Increase if long-running LLM calls are expected
      containers:
        - name: engramia-api
          lifecycle:
            preStop:
              exec:
                # Give the load balancer time to de-register the pod before
                # uvicorn stops accepting connections (avoids connection resets).
                command: ["/bin/sh", "-c", "sleep 5"]
```

---

### Health check grace periods

The Kubernetes readiness probe controls when a new pod starts receiving traffic.  The liveness probe controls when a broken pod is restarted.

Reference values (adjust to your startup time — typically 5–15 s):

```yaml
readinessProbe:
  httpGet:
    path: /v1/health
    port: 8000
  initialDelaySeconds: 10   # Wait for DB pool to warm up
  periodSeconds: 5
  failureThreshold: 3       # 15 s window before pod is pulled from rotation

livenessProbe:
  httpGet:
    path: /v1/health
    port: 8000
  initialDelaySeconds: 20
  periodSeconds: 10
  failureThreshold: 3       # 30 s window before pod is restarted
```

`GET /v1/health` is cheap (no DB query) and suitable for both probes.  Use `GET /v1/health/deep` only in manual smoke-tests — it performs a DB round-trip and is too slow for sub-second probe intervals.

---

### Database migration compatibility (expand-contract)

Migrations that rename or drop columns require the **expand-contract** pattern to maintain compatibility between the old and new application version that overlap during a rolling update.

**Phase 1 — Expand (deploy with the old code):**

```sql
-- Add the new column with a default (backward-compatible)
ALTER TABLE engramia_data ADD COLUMN new_col TEXT NOT NULL DEFAULT '';
```

**Phase 2 — Migrate (deploy new code that writes to both columns):**

The new code writes to both `old_col` and `new_col` during the transition window.

**Phase 3 — Contract (after all old pods are gone):**

```sql
-- Drop the old column once no running code references it
ALTER TABLE engramia_data DROP COLUMN old_col;
```

**Alembic workflow:**

```bash
# Phase 1 migration — safe to apply before rolling update
docker compose exec engramia-api alembic upgrade head

# Phase 3 migration — apply only after 100% of pods run new code
docker compose exec engramia-api alembic upgrade <contract_revision>
```

!!! warning
    Never run a contract migration while old pods are still live.  Always check
    `kubectl -n engramia rollout status deployment/engramia-api` first.

---

### Feature flags for safe rollouts

Engramia does not ship a built-in feature-flag service, but the pattern is easy to implement with environment variables or the existing admin config:

**Environment variable flag (simple, per-deployment):**

```python
import os
NEW_RECALL_PIPELINE = os.getenv("ENGRAMIA_FF_NEW_RECALL", "false").lower() == "true"
```

Set in the Kubernetes ConfigMap or `.env` file; flip with a re-deploy (no code change required).

**Gradual rollout via HPA:**

1. Deploy the new version on a single pod by temporarily reducing replicas to 1.
2. Route a subset of traffic to that pod using weighted Ingress rules (nginx / Caddy supports this).
3. Monitor error rates and latency in Prometheus/Grafana.
4. Scale up the new version to full replicas and remove the weight split.

**Rollback trigger thresholds** (recommended Grafana alert annotations):

| Metric | Rollback threshold |
|--------|-------------------|
| HTTP 5xx rate | > 5% for 2 min |
| p95 request latency | > 2× pre-deploy baseline |
| DB pool exhaustion | Any overflow for > 1 min |

When a threshold fires, issue:

```bash
kubectl -n engramia rollout undo deployment/engramia-api
```

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
2. Use separate `.env` files per environment (local dev, Hetzner staging (UAT), Hetzner PROD)
3. Restrict file permissions: `chmod 600 .env`
4. Unset `ENGRAMIA_BOOTSTRAP_TOKEN` after initial key creation
5. Rotate API keys periodically via `POST /v1/keys/{id}/rotate`

### Production (Hetzner VM)

Secrets are stored in `<your-install-path>/.env` on the production host, restricted to the deploy user. Docker Compose reads this file at container startup.

### Future: External secret managers (roadmap)

For enterprise deployments requiring centralized secret management, audit trails, and automatic rotation, integration with external providers (HashiCorp Vault, AWS Secrets Manager, Azure Key Vault) is planned. See the roadmap for timeline.

---

## Stripe Billing configuration

### Stripe Tax (EU VAT / US Sales Tax)

Engramia's checkout sessions pass `automatic_tax: {enabled: true}` and
`tax_id_collection: {enabled: true}` to Stripe.  These flags are **inert**
until Stripe Tax is activated — no error is thrown, but no tax is calculated
either, which is a compliance risk for EU and US customers.

**Activation (one-time, per Stripe account):**

1. Stripe Dashboard → **Settings** → **Tax** → click **Activate Stripe Tax**.
2. Set your **origin address** (the address from which you sell — used for
   tax nexus determination).
3. Add your **registered tax IDs** (e.g. CZ VAT ID `CZ12345678`) under
   Tax → Tax registrations → Add registration.
4. For EU OSS: register for the One Stop Shop scheme via the Czech Tax
   Administration portal (`moje.daneOnline.cz`) — this lets you file a
   single quarterly EU return instead of registering in each member state.

After activation Stripe automatically:
- Calculates the correct VAT/GST rate per customer country.
- Applies EU B2B reverse-charge when the customer provides a valid VAT ID.
- Prints the tax breakdown on invoices.
- Provides per-jurisdiction tax reports exportable from the Dashboard.

**Cost:** 0.5% of each taxable transaction (maximum $2 per transaction).
Reverse-charge B2B transactions are not taxed, so the fee does not apply.

---

### Stripe Smart Retries (dunning)

Engramia grants a **7-day grace period** after a failed payment before
blocking access (HTTP 402).  Stripe's Smart Retries should be configured to
retry within that window so that transient card failures resolve automatically.

**Configuration (Stripe Dashboard → Settings → Billing → Subscriptions →
Manage failed payments):**

| Setting | Recommended value |
|---------|-------------------|
| Retry logic | Smart Retries |
| Retry schedule | Day 3 · Day 5 · Day 7 · Day 14 |
| After final attempt | **Cancel the subscription** |
| Send emails to customers | ✅ Failed payment · ✅ Expiring card |

**Why this schedule:** the application grace period is 7 days.  Retrying on
days 3, 5, and 7 maximises recovery before the customer loses access.  A final
retry on day 14 catches customers who updated their card late.  Cancelling
after all retries fires `customer.subscription.deleted`, which Engramia
handles by downgrading the tenant to the Developer free tier (the legacy "sandbox" alias still resolves for any pre-6.6 row).

**Dunning notification events** are emitted as structured log entries at the
`WARNING` level with the key `dunning_event`.  Hook an email provider (e.g.
Resend, SendGrid) to the application log pipeline or implement an email
service and call `BillingService.check_dunning_reminders()` from a daily
scheduled job to send day-5 access-expiry reminders.

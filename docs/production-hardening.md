# Production Hardening Guide

Engramia v0.6.0 — checklist for production deployments beyond Docker basics.

---

## Pre-Deployment Checklist

### Environment configuration

- [ ] `ENGRAMIA_ENVIRONMENT=production` — activates startup guard that blocks `AUTH_MODE=dev`
- [ ] `ENGRAMIA_AUTH_MODE=db` — DB-backed key management (or `oidc` for enterprise SSO)
- [ ] `OPENAI_API_KEY` set from a secrets manager (not hardcoded in compose file)
- [ ] `POSTGRES_PASSWORD` is a randomly generated 32+ character string
- [ ] `ENGRAMIA_CORS_ORIGINS` explicitly set to your frontend origin(s); never `*`
- [ ] `ENGRAMIA_JSON_LOGS=true` — structured logging for log aggregation
- [ ] `ENGRAMIA_METRICS=true` — Prometheus metrics if using a monitoring stack

### First boot — bootstrap owner key

```bash
# Run once after first deploy to create the owner API key
curl -X POST https://api.engramia.dev/v1/keys/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"name": "owner-key"}'

# Copy the returned secret — it is shown only once
# Store it in your password manager / secrets vault
```

After bootstrapping, the endpoint is disabled — subsequent calls return 409.

### Alembic migrations

Always run migrations before starting the new API version:

```bash
docker compose -f docker-compose.prod.yml exec engramia-api alembic upgrade head
```

The CI/CD pipeline (`docker.yml`) runs this automatically. For manual deployments, run it before `docker compose up`.

### Verify startup

```bash
# Health check — should return {"status": "ok", ...}
curl https://api.engramia.dev/v1/health

# Deep probe — storage + LLM + embeddings
curl https://api.engramia.dev/v1/health/deep \
  -H "Authorization: Bearer $OWNER_KEY"
```

---

## Network Hardening

### Caddy configuration

Caddy handles TLS automatically. Verify the Caddyfile includes:

```
api.engramia.dev {
    reverse_proxy localhost:8000
    header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
    header X-Content-Type-Options nosniff
    header X-Frame-Options DENY
    header Referrer-Policy no-referrer
}
```

### Firewall (Hetzner Cloud Firewall)

Allow inbound:
- TCP 80 — HTTP (Caddy redirects to HTTPS)
- TCP 443 — HTTPS

Block all other inbound ports. The API port (8000) is bound to `127.0.0.1` only in `docker-compose.prod.yml` and must not be exposed externally.

### PostgreSQL

- Bind only to the Docker internal network (`127.0.0.1` or bridge network)
- Never expose port 5432 to the internet
- Use a strong password (32+ characters)
- For external DB hosts: add `?sslmode=require` to `ENGRAMIA_DATABASE_URL`

---

## Runtime Hardening

### Docker security options

Add to `docker-compose.prod.yml` for defense-in-depth:

```yaml
engramia-api:
  security_opt:
    - no-new-privileges:true
  read_only: true
  tmpfs:
    - /tmp
```

### Resource limits

Prevent resource exhaustion:

```yaml
engramia-api:
  deploy:
    resources:
      limits:
        cpus: "2.0"
        memory: "1G"
      reservations:
        memory: "256M"
```

### Log rotation

Configure Docker log rotation to prevent disk exhaustion:

```yaml
engramia-api:
  logging:
    driver: json-file
    options:
      max-size: "100m"
      max-file: "5"
```

---

## Monitoring

### Health checks

The `engramia-api` service in `docker-compose.prod.yml` has a built-in Docker healthcheck:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/v1/health"]
  interval: 30s
  timeout: 5s
  retries: 3
```

Monitor container health with: `docker compose ps`

### Prometheus + Grafana (optional)

Enable Prometheus: `ENGRAMIA_METRICS=true`

Metrics available at `GET /metrics`:

| Metric | Type | Description |
|--------|------|-------------|
| `engramia_requests_duration_seconds` | histogram | Request latency by endpoint |
| `engramia_llm_call_duration_seconds` | histogram | LLM provider call latency |
| `engramia_embedding_duration_seconds` | histogram | Embedding provider call latency |
| `engramia_recall_hits_total` | counter | Successful recalls |
| `engramia_recall_misses_total` | counter | Recalls with no match above threshold |
| `engramia_jobs_submitted_total` | counter | Async jobs submitted |
| `engramia_jobs_completed_total` | counter | Async jobs completed (success/failure) |
| `engramia_pattern_count` | gauge | Current number of stored patterns |

Recommended alert: `engramia_requests_duration_seconds{quantile="0.99"} > 5` → API latency degraded.

### OpenTelemetry tracing (optional)

Enable: `ENGRAMIA_TELEMETRY=true`, `ENGRAMIA_OTEL_ENDPOINT=http://otel-collector:4317`

Traces are emitted for: LLM calls, embedding calls, storage operations, and all Memory facade methods.

---

## Periodic Maintenance

Schedule these weekly (e.g., cron or GitHub Actions scheduled workflow):

```bash
# Pattern aging — decay + prune stale patterns
curl -X POST https://api.engramia.dev/v1/aging \
  -H "Authorization: Bearer $OWNER_KEY"

# Feedback decay
curl -X POST https://api.engramia.dev/v1/feedback/decay \
  -H "Authorization: Bearer $OWNER_KEY"

# Retention cleanup (GDPR — prune expired patterns)
curl -X POST https://api.engramia.dev/v1/governance/retention/apply \
  -H "Authorization: Bearer $OWNER_KEY"

# ROI rollup (analytics)
curl -X POST https://api.engramia.dev/v1/analytics/rollup \
  -H "Authorization: Bearer $OWNER_KEY"
```

Or use `Prefer: respond-async` to run as background jobs if the call would take too long.

---

## Secret Rotation

### API key rotation (zero downtime)

```bash
# Rotate a specific key — new secret returned, old secret immediately invalidated
curl -X POST https://api.engramia.dev/v1/keys/{id}/rotate \
  -H "Authorization: Bearer $OWNER_KEY"
```

Update the secret in all consumers before the old key is fully invalidated.

### OpenAI / Anthropic key rotation

1. Generate a new key on the provider dashboard
2. Update `OPENAI_API_KEY` in `.env`
3. `docker compose -f docker-compose.prod.yml up -d engramia-api` — rolling restart

### PostgreSQL password rotation

Requires downtime (or a DB proxy with connection pooling):
1. Enter maintenance mode: `ENGRAMIA_MAINTENANCE=true`
2. Update password in PostgreSQL: `ALTER USER engramia WITH PASSWORD 'new-password';`
3. Update `.env`
4. Restart API: `docker compose up -d`
5. Exit maintenance mode: remove `ENGRAMIA_MAINTENANCE`

---

## Disk Management

Monitor disk usage — the PostgreSQL data volume can grow significantly with embeddings:

```bash
docker system df
du -sh /var/lib/docker/volumes/engramia_pgdata/_data
```

pgvector embedding size: ~6 KB per pattern (1536 × 4 bytes float32). 10 000 patterns ≈ 60 MB. Run `run_aging()` regularly to prune stale patterns.

---

## Incident Response

See [runbooks/incident-response.md](runbooks/incident-response.md) for the full IR process.

Quick contacts:
- **Infrastructure**: Hetzner Cloud Console (hetzner.com/cloud)
- **API keys compromise**: `POST /v1/keys/{id}/rotate` or `DELETE /v1/keys/{id}`
- **Data breach**: follow incident response playbook, notify DPA within 72 hours (GDPR Art. 33)

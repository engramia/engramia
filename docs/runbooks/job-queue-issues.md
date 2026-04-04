# Runbook: Job Queue Issues

**Severity:** P3-Low (async jobs are best-effort)

## Symptoms

- Jobs stuck in `pending` or `running` status
- `GET /v1/jobs` shows growing backlog
- Async operations not completing

## Diagnostics

```bash
# List recent jobs
curl -s -H "Authorization: Bearer $KEY" http://localhost:8000/v1/jobs?limit=50 | jq '.jobs[] | {id, operation, status, created_at, attempts}'

# Check for stuck running jobs (>10 min)
curl -s -H "Authorization: Bearer $KEY" http://localhost:8000/v1/jobs?status=running | jq '.jobs[]'

# Check worker logs
docker compose logs engramia-api --since 30m | grep -i "job\|worker\|poll" | tail -30
```

## Common Issues

### Jobs stuck in "pending"

**Cause:** Worker thread not running or polling too slowly.

```bash
# Check worker config
echo "Poll interval: $ENGRAMIA_JOB_POLL_INTERVAL (default: 2.0s)"
echo "Max concurrent: $ENGRAMIA_JOB_MAX_CONCURRENT (default: 3)"

# Restart to trigger orphan recovery
docker compose restart engramia-api
```

### Jobs stuck in "running"

**Cause:** Worker crashed mid-execution. Orphaned job recovery runs at startup and resets jobs running >10 min.

```bash
# Force restart — triggers orphan recovery
docker compose restart engramia-api
```

### All jobs failing

**Cause:** Usually an LLM provider issue (evaluate, compose, evolve jobs need LLM).

Check [llm-provider-outage.md](llm-provider-outage.md).

### Cancel stuck jobs manually

```bash
# Cancel a specific job
curl -X POST -H "Authorization: Bearer $KEY" http://localhost:8000/v1/jobs/JOB_ID/cancel
```

## In-Memory Mode Warning

When `ENGRAMIA_DATABASE_URL` is not set, jobs run in best-effort in-memory mode:
- Jobs are lost on process restart
- No persistence between restarts
- Suitable for development only

**Production:** Always use PostgreSQL-backed jobs (`ENGRAMIA_DATABASE_URL` set).

## Monitoring

```promql
# Job submission rate
rate(engramia_jobs_submitted_total[5m])

# Job completion rate by status
rate(engramia_jobs_completed_total[5m])

# Pending job backlog (if available via custom metric)
engramia_jobs_pending
```

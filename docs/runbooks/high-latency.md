# Runbook: High API Latency

## Symptoms
- p95 latency > 2s on `/v1/recall` or `/v1/evaluate`
- Users report timeouts
- Prometheus `engramia_request_duration_seconds` histogram shows elevated p99

## Diagnostics

### Step 1 — Identify the slow endpoint
```bash
# Check recent slow requests in structured logs
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml logs engramia-api \
     --since 30m | grep "duration_ms" | awk -F"duration_ms=" "{print \$2}" | sort -n | tail -20'
```

### Step 2 — Check PostgreSQL query performance
```bash
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml exec pgvector \
     psql -U engramia -c "
       SELECT query, mean_exec_time, calls
       FROM pg_stat_statements
       ORDER BY mean_exec_time DESC
       LIMIT 10;"'
```

### Step 3 — Check pgvector index health
```bash
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml exec pgvector \
     psql -U engramia -c "
       SELECT schemaname, tablename, n_dead_tup, n_live_tup, last_autovacuum
       FROM pg_stat_user_tables
       WHERE tablename IN ('"'"'memory_data'"'"', '"'"'memory_embeddings'"'"');"'
```

### Step 4 — Check embedding API latency (if OpenAI/Anthropic)
```bash
# Check for 429 or 503 from upstream in logs
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml logs engramia-api \
     --since 10m | grep -E "(429|503|timeout|embedding)"'
```

### Step 5 — Check system load
```bash
ssh root@engramia-staging 'top -bn1 | head -20'
ssh root@engramia-staging 'iostat -x 1 3'
```

## Resolution

### Slow pgvector queries — VACUUM + ANALYZE
```bash
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml exec pgvector \
     psql -U engramia -c "VACUUM ANALYZE memory_embeddings;"'
```

### Embedding API throttled — reduce rate
Set `ENGRAMIA_RATE_LIMIT_EXPENSIVE=5` in `.env` and restart:
```bash
ssh root@engramia-staging 'cd /opt/engramia && \
  docker compose -f docker-compose.prod.yml restart engramia-api'
```

### High CPU from concurrent evals — lower job concurrency
```bash
# Edit .env on VM: ENGRAMIA_JOB_MAX_CONCURRENT=1
ssh root@engramia-staging 'cd /opt/engramia && \
  docker compose -f docker-compose.prod.yml restart engramia-api'
```

### Pattern store too large — run aging
```bash
curl -X POST https://api.engramia.dev/v1/aging \
  -H "Authorization: Bearer $ENGRAMIA_API_KEY"
```

## Prevention
- Add pgvector HNSW index if pattern count > 10,000
- Enable `pg_stat_statements` for query profiling
- Alert when Prometheus `engramia_avg_eval_score` drops suddenly (LLM issues)

## Escalation
If latency remains high after all steps, check if OpenAI/Anthropic has an active incident at their status pages.

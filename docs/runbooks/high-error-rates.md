# Runbook: High Error Rates

**Severity:** P2-Medium (P1 if sustained >5 min or >50% of requests)

## Symptoms

- Elevated 5xx responses in Prometheus (`engramia_requests_total{status_code=~"5.."}`)
- Increased error-level logs in structured output
- Health check returning `degraded` or `error`

## Diagnostics

### 1. Identify error source

```bash
# Check deep health
curl -s http://localhost:8000/v1/health/deep | jq .

# Check structured logs for error patterns
docker compose logs engramia-api --since 10m | grep '"level":"ERROR"' | jq -r '.message' | sort | uniq -c | sort -rn
```

### 2. Classify errors

| Pattern | Likely Cause | Action |
|---------|-------------|--------|
| `ProviderError: OpenAI` | LLM provider outage | See [LLM Provider Outage](#llm-provider-outage) |
| `StorageError` | Database connectivity | See [database-recovery.md](database-recovery.md) |
| `ValidationError` | Bad client input | Check API consumers; not a system issue |
| `QuotaExceededError` | Tenant hitting limits | Review quotas; increase if legitimate |
| `RateLimited` | Burst traffic | See [rate-limit-tuning.md](rate-limit-tuning.md) |

### 3. Check Prometheus metrics

```promql
# Error rate over 5 minutes
rate(engramia_requests_total{status_code=~"5.."}[5m])
  / rate(engramia_requests_total[5m])

# LLM call failures
rate(engramia_llm_call_duration_seconds_count{status="error"}[5m])
```

## LLM Provider Outage

**Impact:** `/evaluate`, `/compose`, `/evolve` return 503. `/learn`, `/recall`, `/health` still work.

### Immediate actions

1. Check provider status page (status.openai.com or status.anthropic.com)
2. If prolonged (>15 min), enable maintenance mode for LLM-dependent endpoints:
   ```bash
   # Not currently supported per-endpoint; full maintenance mode:
   docker compose exec engramia-api env ENGRAMIA_MAINTENANCE=true
   ```
3. Communicate to API consumers that evaluation/composition is temporarily unavailable

### Recovery

- LLM endpoints auto-recover when provider returns; retry logic (3x with backoff) handles transient failures
- No manual intervention needed for recovery

## Escalation

- **P2** (elevated but <50%): Monitor for 15 min, investigate root cause
- **P1** (>50% or all requests failing): Immediate investigation, consider rollback if recent deployment
- **P0** (data corruption or security breach): Follow [Incident Response Plan](../incident-response-plan.md)

# Runbook: Rate Limit Tuning

## Current Defaults
| Env var | Default | Applies to |
|---------|---------|-----------|
| `ENGRAMIA_RATE_LIMIT_DEFAULT` | 60 req/min | All endpoints |
| `ENGRAMIA_RATE_LIMIT_EXPENSIVE` | 10 req/min | `/evaluate`, `/compose`, `/evolve` |

## Symptoms Indicating Limit Too Low
- Legitimate clients receive `429 Too Many Requests`
- Audit logs show `RATE_LIMITED` events for known good IPs
- Users report intermittent failures during batch operations

## Symptoms Indicating Limit Too High
- LLM API costs spike unexpectedly
- VM CPU/memory saturated during eval bursts

## Diagnosing Rate Limit Events

```bash
# Find rate-limited IPs and paths in logs
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml logs engramia-api \
     --since 1h | grep "Rate limit exceeded"'

# Check audit table (if DB auth mode)
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml exec pgvector \
     psql -U engramia -c "
       SELECT ip, path, count(*), max(created_at)
       FROM audit_log
       WHERE event = '"'"'rate_limited'"'"'
       AND created_at > NOW() - INTERVAL '"'"'1 hour'"'"'
       GROUP BY ip, path
       ORDER BY count DESC
       LIMIT 20;"'
```

## Adjusting Limits

### Temporary (no restart)
The rate limiter reads env vars at startup only. A restart is required.

### Permanent
```bash
ssh root@engramia-staging '
  cd /opt/engramia
  # Increase default limit to 120/min, keep expensive at 10/min
  sed -i "s/^ENGRAMIA_RATE_LIMIT_DEFAULT=.*/ENGRAMIA_RATE_LIMIT_DEFAULT=120/" .env
  grep -q ENGRAMIA_RATE_LIMIT_DEFAULT .env || echo "ENGRAMIA_RATE_LIMIT_DEFAULT=120" >> .env
  docker compose -f docker-compose.prod.yml restart engramia-api
'
```

### Per-client exemption (workaround)
The current rate limiter is per-IP. For trusted batch clients, consider:
1. Running them via a dedicated IP with a higher limit, or
2. Moving to the async job API (`Prefer: respond-async` header) to avoid synchronous rate limiting

## Resetting Rate Limit State
The in-memory counter resets on API restart:
```bash
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml restart engramia-api'
```

## Recommendations
- Keep `ENGRAMIA_RATE_LIMIT_EXPENSIVE` ≤ 20 to control LLM costs
- Alert when 429 rate exceeds 5% of total requests (Prometheus)
- For multi-instance deployments, replace the in-memory limiter with Redis

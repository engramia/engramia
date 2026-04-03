# Runbook: Maintenance Mode

## Overview

Setting `ENGRAMIA_MAINTENANCE=true` causes the API to return `503 Service Unavailable`
on all endpoints except `/v1/health` and `/v1/health/deep`. This allows load-balancer
health checks to continue while blocking client traffic during planned maintenance.

## Enabling Maintenance Mode

### Option A — Environment variable (requires restart)
```bash
ssh root@engramia-staging '
  cd /opt/engramia
  # Add or update in .env
  sed -i "s/^ENGRAMIA_MAINTENANCE=.*/ENGRAMIA_MAINTENANCE=true/" .env
  grep -q ENGRAMIA_MAINTENANCE .env || echo "ENGRAMIA_MAINTENANCE=true" >> .env
  docker compose -f docker-compose.prod.yml restart engramia-api
'
```

### Option B — Inline env override (no .env change, temporary)
```bash
ssh root@engramia-staging '
  cd /opt/engramia
  docker compose -f docker-compose.prod.yml stop engramia-api
  ENGRAMIA_MAINTENANCE=true docker compose -f docker-compose.prod.yml up -d engramia-api
'
```

## Verifying Maintenance Mode Is Active

```bash
# Should return 503
curl -i https://api.engramia.dev/v1/recall \
  -H "Authorization: Bearer $ENGRAMIA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"task": "test"}'
# Expected: HTTP 503 + {"detail": "Service is under scheduled maintenance..."}

# Health must still return 200
curl -i https://api.engramia.dev/v1/health
# Expected: HTTP 200
```

## Performing Maintenance

Common tasks done under maintenance mode:
- Running Alembic migrations:
  ```bash
  ssh root@engramia-staging \
    'docker compose -f /opt/engramia/docker-compose.prod.yml exec engramia-api \
       alembic upgrade head'
  ```
- VACUUM FULL on large tables (see [database-recovery.md](database-recovery.md))
- Deploying a breaking schema change

## Disabling Maintenance Mode

```bash
ssh root@engramia-staging '
  cd /opt/engramia
  sed -i "s/^ENGRAMIA_MAINTENANCE=.*/ENGRAMIA_MAINTENANCE=false/" .env
  docker compose -f docker-compose.prod.yml restart engramia-api
'

# Verify
curl https://api.engramia.dev/v1/health
```

## Client Communication
- Notify users via status page or email before enabling maintenance
- The `Retry-After: 3600` header is set automatically on 503 responses
- Recommended window: low-traffic period (e.g. 02:00–04:00 CET)

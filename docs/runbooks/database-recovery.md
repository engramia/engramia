# Runbook: Database Recovery

## Symptoms
- PostgreSQL container is unhealthy (`docker compose ps` shows `unhealthy`)
- API returns 503 with "storage unavailable" errors
- Data loss suspected after incident

## Diagnostics

```bash
# Check pgvector container status
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml ps pgvector'

# View PostgreSQL logs
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml logs pgvector --tail 100'

# Check disk space (common cause of PG failure)
ssh root@engramia-staging 'df -h /var/lib/docker/volumes/engramia_pgdata'
```

## Backup

### Create manual backup before any recovery action
```bash
ssh root@engramia-staging '
  docker compose -f /opt/engramia/docker-compose.prod.yml exec pgvector \
    pg_dump -U engramia engramia \
    > /opt/engramia/backup_$(date +%Y%m%d_%H%M%S).sql
'
```

### Restore from backup
```bash
BACKUP_FILE=/opt/engramia/backup_20260101_120000.sql

ssh root@engramia-staging "
  docker compose -f /opt/engramia/docker-compose.prod.yml exec -T pgvector \
    psql -U engramia engramia < ${BACKUP_FILE}
"
```

## Recovery Steps

### Case 1 — Container crashed, data intact
```bash
ssh root@engramia-staging '
  cd /opt/engramia
  docker compose -f docker-compose.prod.yml restart pgvector
  # Wait for healthy
  sleep 10
  docker compose -f docker-compose.prod.yml ps pgvector
'
```

### Case 2 — Migration failed, schema mismatch
```bash
# Run migrations manually
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml exec engramia-api \
     alembic upgrade head'

# Verify
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml exec engramia-api \
     alembic current'
```

### Case 3 — pgvector extension missing after container recreation
```bash
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml exec pgvector \
     psql -U engramia -c "CREATE EXTENSION IF NOT EXISTS vector;"'
```

### Case 4 — Data corruption, full restore required
```bash
# 1. Stop API to prevent writes
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml stop engramia-api'

# 2. Drop and recreate database
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml exec pgvector \
     psql -U postgres -c "DROP DATABASE engramia; CREATE DATABASE engramia OWNER engramia;"'

# 3. Restore from backup
ssh root@engramia-staging "
  docker compose -f /opt/engramia/docker-compose.prod.yml exec -T pgvector \
    psql -U engramia engramia < /opt/engramia/backup_YYYYMMDD_HHMMSS.sql
"

# 4. Run migrations to latest
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml exec engramia-api \
     alembic upgrade head'

# 5. Restart API
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml start engramia-api'
```

## Prevention
- Set up automated `pg_dump` cron job (daily, retain 7 days)
- Monitor `pgvector` container health via Prometheus `up` metric
- Use `pgdata` named Docker volume — never bind-mount to a path that gets cleaned up

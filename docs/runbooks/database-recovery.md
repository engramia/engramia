# Runbook: Database Recovery

Run commands from your deploy host (the server where `docker-compose.prod.yml`
lives). Commands below assume the working directory is the deploy path
(e.g. `/opt/engramia`). Adjust `COMPOSE_FILE` if yours differs.

## Symptoms
- PostgreSQL container is unhealthy (`docker compose ps` shows `unhealthy`)
- API returns 503 with "storage unavailable" errors
- Data loss suspected after incident

## Diagnostics

```bash
# Check pgvector container status
docker compose -f docker-compose.prod.yml ps pgvector

# View PostgreSQL logs
docker compose -f docker-compose.prod.yml logs pgvector --tail 100

# Check disk space (common cause of PG failure)
df -h /var/lib/docker/volumes/engramia_pgdata
```

## Backup

### Create manual backup before any recovery action
```bash
docker compose -f docker-compose.prod.yml exec pgvector \
  pg_dump -U engramia engramia \
  > ./backup_$(date +%Y%m%d_%H%M%S).sql
```

### Restore from backup
```bash
BACKUP_FILE=./backup_20260101_120000.sql

docker compose -f docker-compose.prod.yml exec -T pgvector \
  psql -U engramia engramia < "${BACKUP_FILE}"
```

## Recovery Steps

### Case 1 — Container crashed, data intact
```bash
docker compose -f docker-compose.prod.yml restart pgvector
sleep 10
docker compose -f docker-compose.prod.yml ps pgvector
```

### Case 2 — Migration failed, schema mismatch
```bash
# Run migrations manually
docker compose -f docker-compose.prod.yml exec engramia-api \
  alembic upgrade head

# Verify
docker compose -f docker-compose.prod.yml exec engramia-api \
  alembic current
```

### Case 3 — pgvector extension missing after container recreation
```bash
docker compose -f docker-compose.prod.yml exec pgvector \
  psql -U engramia -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Case 4 — Data corruption, full restore required
```bash
# 1. Stop API to prevent writes
docker compose -f docker-compose.prod.yml stop engramia-api

# 2. Drop and recreate database
docker compose -f docker-compose.prod.yml exec pgvector \
  psql -U postgres -c "DROP DATABASE engramia; CREATE DATABASE engramia OWNER engramia;"

# 3. Restore from backup
docker compose -f docker-compose.prod.yml exec -T pgvector \
  psql -U engramia engramia < ./backup_YYYYMMDD_HHMMSS.sql

# 4. Run migrations to latest
docker compose -f docker-compose.prod.yml exec engramia-api \
  alembic upgrade head

# 5. Restart API
docker compose -f docker-compose.prod.yml start engramia-api
```

## Prevention
- Set up automated `pg_dump` cron job (see `scripts/install-backup-cron.sh`)
- Monitor `pgvector` container health via Prometheus `up` metric
- Use `pgdata` named Docker volume — never bind-mount to a path that gets cleaned up

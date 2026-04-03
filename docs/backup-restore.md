# Backup and Restore Playbook

Engramia v0.6.0 · RTO: 4 hours · RPO: 24 hours

---

## Overview

| Storage backend | Backup method | Frequency | Off-site |
|-----------------|--------------|-----------|---------|
| PostgreSQL (prod) | `pg_dump` custom format | Daily | Hetzner Object Storage |
| JSON storage (dev) | Directory copy | Manual | N/A |

---

## PostgreSQL Backup

### Manual dump

```bash
# On the production host
cd /opt/engramia

# Dump to local file (custom format — smaller, supports parallel restore)
docker compose -f docker-compose.prod.yml exec -T pgvector \
  pg_dump -U engramia engramia -Fc \
  > /opt/engramia/backups/engramia_$(date +%Y%m%d_%H%M).dump

# Verify the dump is not empty
ls -lh /opt/engramia/backups/
```

### Automated daily backup (cron)

Add to `/etc/cron.d/engramia-backup` on the production VM:

```cron
# Daily at 03:00 — backup PostgreSQL + upload to Hetzner Object Storage
0 3 * * * root /opt/engramia/scripts/backup.sh >> /var/log/engramia-backup.log 2>&1
```

`/opt/engramia/scripts/backup.sh`:

```bash
#!/bin/bash
set -euo pipefail

BACKUP_DIR=/opt/engramia/backups
BUCKET=s3://engramia-backups
DATE=$(date +%Y%m%d_%H%M)
FILE="$BACKUP_DIR/engramia_${DATE}.dump"
KEEP_DAYS=30

# Create backup
docker compose -f /opt/engramia/docker-compose.prod.yml exec -T pgvector \
  pg_dump -U engramia engramia -Fc > "$FILE"

# Upload to Hetzner Object Storage (configure aws CLI with Hetzner S3 endpoint)
aws --endpoint-url https://fsn1.your-objectstorage.com s3 cp "$FILE" "$BUCKET/"

# Prune local backups older than 7 days
find "$BACKUP_DIR" -name "*.dump" -mtime +7 -delete

# Prune remote backups older than KEEP_DAYS
aws --endpoint-url https://fsn1.your-objectstorage.com s3 ls "$BUCKET/" \
  | awk '{print $4}' \
  | while read -r key; do
      age=$(( ($(date +%s) - $(date -d "$(echo "$key" | grep -oP '\d{8}_\d{4}' | sed 's/_/ /')" +%s)) / 86400 ))
      [ "$age" -gt "$KEEP_DAYS" ] && \
        aws --endpoint-url https://fsn1.your-objectstorage.com s3 rm "$BUCKET/$key"
    done

echo "[$DATE] Backup complete: $FILE"
```

### Verify backup integrity (weekly)

```bash
# Test restore into a temporary container — does not affect production
docker run --rm \
  -e POSTGRES_USER=engramia \
  -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=engramia \
  pgvector/pgvector:0.7.4-pg16 &

sleep 5
pg_restore --list /opt/engramia/backups/engramia_latest.dump | wc -l
# Should print > 0 (number of archived objects)
```

---

## PostgreSQL Restore

### Full restore (disaster recovery)

```bash
# 1. Enter maintenance mode
ssh root@engramia-staging
cd /opt/engramia
echo "ENGRAMIA_MAINTENANCE=true" >> .env
docker compose -f docker-compose.prod.yml up -d engramia-api

# 2. Stop the API to prevent writes during restore
docker compose -f docker-compose.prod.yml stop engramia-api

# 3. Drop and recreate the database
docker compose -f docker-compose.prod.yml exec pgvector \
  psql -U engramia -c "DROP DATABASE IF EXISTS engramia;"
docker compose -f docker-compose.prod.yml exec pgvector \
  psql -U engramia -c "CREATE DATABASE engramia;"

# 4. Restore from dump
cat /opt/engramia/backups/engramia_YYYYMMDD_HHMM.dump \
  | docker compose -f docker-compose.prod.yml exec -T pgvector \
    pg_restore -U engramia -d engramia -v

# 5. Run migrations to ensure schema is at head
docker compose -f docker-compose.prod.yml run --rm engramia-api \
  alembic upgrade head

# 6. Start API and exit maintenance mode
docker compose -f docker-compose.prod.yml up -d engramia-api
sed -i '/ENGRAMIA_MAINTENANCE/d' .env
docker compose -f docker-compose.prod.yml up -d
```

### Point-in-time (migration rollback only)

See [docs/deployment.md](deployment.md) § Rollback strategy for Alembic downgrade procedure.

---

## JSON Storage Backup (development)

```bash
# Backup
cp -r ./engramia_data ./engramia_data_backup_$(date +%Y%m%d)

# Or portable export (works across storage backends)
engramia export --path ./engramia_data --output backup.jsonl

# Restore
cp -r ./engramia_data_backup_20260101 ./engramia_data
# or
engramia import --path ./engramia_data --input backup.jsonl
```

---

## RTO / RPO Targets

| Scenario | RPO | RTO |
|----------|-----|-----|
| VM failure (no data loss) | 24h (last daily backup) | 2h (new VM + restore) |
| Database corruption | 24h (last daily backup) | 2h (pg_restore) |
| Accidental data deletion (single tenant) | 24h | 30min (pg_restore to temp DB, selective re-import) |
| Complete rebuild from scratch | N/A | 4h (VM + Caddy + Docker + migrate + restore) |

RPO can be improved to 1h by enabling PostgreSQL WAL archiving to object storage (requires `wal_level=replica` and a WAL archive destination).

---

## Pre-Migration Backup (mandatory)

Always take a dump before running `alembic upgrade`:

```bash
docker compose -f docker-compose.prod.yml exec -T pgvector \
  pg_dump -U engramia engramia -Fc \
  > /opt/engramia/backups/pre_migration_$(date +%Y%m%d_%H%M).dump
```

The CI/CD deploy step in `docker.yml` runs migrations automatically. If you're deploying manually, run the backup first.

---

## Off-Site Storage Configuration

Hetzner Object Storage (FSN1 region, S3-compatible):

```bash
# Configure aws CLI for Hetzner
aws configure set aws_access_key_id YOUR_ACCESS_KEY
aws configure set aws_secret_access_key YOUR_SECRET_KEY
aws configure set default.region eu-central-1

# Test access
aws --endpoint-url https://fsn1.your-objectstorage.com s3 ls s3://engramia-backups/
```

Create the bucket in the Hetzner Cloud Console → Object Storage → Create Bucket. Set lifecycle rule: delete objects older than 30 days.

#!/usr/bin/env bash
# Engramia PostgreSQL Restore Script
# Usage: ./scripts/restore.sh <backup_file.sql.gz>
#
# Supported formats:
#   .sql.gz   Plain SQL dump compressed with gzip (produced by backup.sh)
#   .sql      Plain SQL dump (uncompressed)
#   .dump     PostgreSQL custom format (pg_dump -Fc)
#
# Environment variables:
#   COMPOSE_FILE   Path to docker-compose file (default: /opt/engramia/docker-compose.prod.yml)
#   DB_USER        PostgreSQL user (default: engramia)
#   DB_NAME        PostgreSQL database name (default: engramia)
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────────
COMPOSE_FILE="${COMPOSE_FILE:-/opt/engramia/docker-compose.prod.yml}"
DB_USER="${DB_USER:-engramia}"
DB_NAME="${DB_NAME:-engramia}"

# ── Helpers ────────────────────────────────────────────────────────────────────
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [restore] $*"; }

# ── Argument validation ────────────────────────────────────────────────────────
BACKUP_FILE="${1:-}"

if [[ -z "$BACKUP_FILE" ]]; then
  echo "Usage: $0 <backup_file>"
  echo "  Supported formats: .sql.gz, .sql, .dump"
  exit 1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "ERROR: File not found: ${BACKUP_FILE}"
  exit 1
fi

if [[ ! -r "$BACKUP_FILE" ]]; then
  echo "ERROR: File not readable: ${BACKUP_FILE}"
  exit 1
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "ERROR: Compose file not found: ${COMPOSE_FILE}"
  exit 1
fi

FILE_SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)

# ── Detect format ──────────────────────────────────────────────────────────────
case "$BACKUP_FILE" in
  *.sql.gz) FORMAT="sql.gz" ;;
  *.sql)    FORMAT="sql" ;;
  *.dump)   FORMAT="dump" ;;
  *)
    echo "ERROR: Unrecognised file extension for: ${BACKUP_FILE}"
    echo "  Expected .sql.gz, .sql, or .dump"
    exit 1
    ;;
esac

# ── Confirmation prompt ────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  DANGER: This will DESTROY all current data in ${DB_NAME}  "
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  Backup file : ${BACKUP_FILE}"
echo "  File size   : ${FILE_SIZE}"
echo "  Format      : ${FORMAT}"
echo "  Compose     : ${COMPOSE_FILE}"
echo ""
echo "  This action is IRREVERSIBLE. Take a fresh backup first if needed:"
echo "    BACKUP_DIR=/tmp ./scripts/backup.sh"
echo ""
read -rp "  Type 'yes' to proceed: " CONFIRM
echo ""

if [[ "$CONFIRM" != "yes" ]]; then
  log "Aborted by user."
  exit 0
fi

# ── Stop API to prevent writes during restore ──────────────────────────────────
log "Stopping engramia-api..."
docker compose -f "$COMPOSE_FILE" stop engramia-api

# ── Drop and recreate the database ────────────────────────────────────────────
log "Dropping and recreating database '${DB_NAME}'..."
docker compose -f "$COMPOSE_FILE" exec -T pgvector \
  psql -U "$DB_USER" postgres \
  -c "DROP DATABASE IF EXISTS ${DB_NAME};" \
  -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"

# ── Restore pgvector extension ─────────────────────────────────────────────────
log "Ensuring pgvector extension is present..."
docker compose -f "$COMPOSE_FILE" exec -T pgvector \
  psql -U "$DB_USER" "$DB_NAME" \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"

# ── Restore from backup ────────────────────────────────────────────────────────
log "Restoring from ${BACKUP_FILE} (format: ${FORMAT})..."

case "$FORMAT" in
  sql.gz)
    zcat "$BACKUP_FILE" | \
      docker compose -f "$COMPOSE_FILE" exec -T pgvector \
        psql -U "$DB_USER" "$DB_NAME" -v ON_ERROR_STOP=1
    ;;
  sql)
    docker compose -f "$COMPOSE_FILE" exec -T pgvector \
      psql -U "$DB_USER" "$DB_NAME" -v ON_ERROR_STOP=1 \
      < "$BACKUP_FILE"
    ;;
  dump)
    docker compose -f "$COMPOSE_FILE" exec -T pgvector \
      pg_restore -U "$DB_USER" -d "$DB_NAME" -v \
      < "$BACKUP_FILE"
    ;;
esac

log "Database restored."

# ── Run Alembic migrations to bring schema to HEAD ────────────────────────────
log "Running Alembic migrations (upgrade head)..."
docker compose -f "$COMPOSE_FILE" run --rm engramia-api \
  alembic upgrade head

# ── Restart API ────────────────────────────────────────────────────────────────
log "Starting engramia-api..."
docker compose -f "$COMPOSE_FILE" up -d engramia-api

# ── Smoke test ────────────────────────────────────────────────────────────────
log "Waiting for API to become healthy..."
for i in $(seq 1 12); do
  if docker compose -f "$COMPOSE_FILE" exec -T engramia-api \
      curl -sf http://localhost:8000/v1/health &>/dev/null; then
    log "API is healthy."
    break
  fi
  if [[ $i -eq 12 ]]; then
    log "WARNING: API did not become healthy within 60s — check logs:"
    log "  docker compose -f ${COMPOSE_FILE} logs engramia-api"
  fi
  sleep 5
done

log "SUCCESS: Restore complete from ${BACKUP_FILE}"

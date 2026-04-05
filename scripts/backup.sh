#!/usr/bin/env bash
# Engramia PostgreSQL Backup Script
# Usage: ./scripts/backup.sh
#
# Environment variables:
#   BACKUP_DIR          Local backup directory (default: /var/backups/engramia)
#   BACKUP_S3_BUCKET    S3 bucket URL, e.g. s3://engramia-backups (optional)
#   BACKUP_S3_ENDPOINT  S3-compatible endpoint URL, e.g. https://fsn1.your-objectstorage.com (optional)
#   RETAIN_DAYS         Days to keep local backups (default: 30)
#   COMPOSE_FILE        Path to docker-compose file (default: /opt/engramia/docker-compose.prod.yml)
#   DB_USER             PostgreSQL user (default: engramia)
#   DB_NAME             PostgreSQL database name (default: engramia)
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-/var/backups/engramia}"
BACKUP_S3_BUCKET="${BACKUP_S3_BUCKET:-}"
BACKUP_S3_ENDPOINT="${BACKUP_S3_ENDPOINT:-}"
RETAIN_DAYS="${RETAIN_DAYS:-30}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/engramia/docker-compose.prod.yml}"
DB_USER="${DB_USER:-engramia}"
DB_NAME="${DB_NAME:-engramia}"

# ── Helpers ────────────────────────────────────────────────────────────────────
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [backup] $*"; }

TIMESTAMP=$(date '+%Y-%m-%d_%H-%M')
FILENAME="backup_${TIMESTAMP}.sql.gz"
FILEPATH="${BACKUP_DIR}/${FILENAME}"
EXIT_CODE=0

# ── Cleanup trap: remove partial file and log failure ─────────────────────────
cleanup() {
  local code=$?
  if [[ $code -ne 0 ]]; then
    log "ERROR: Backup failed (exit ${code}) — removing partial file"
    rm -f "$FILEPATH"
    exit 1
  fi
}
trap cleanup EXIT

# ── Pre-flight checks ──────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  log "ERROR: docker not found in PATH"
  exit 1
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
  log "ERROR: Compose file not found: ${COMPOSE_FILE}"
  exit 1
fi

# ── Create backup directory ────────────────────────────────────────────────────
mkdir -p "$BACKUP_DIR"

# ── Perform pg_dump ────────────────────────────────────────────────────────────
log "Starting backup → ${FILEPATH}"
docker compose -f "$COMPOSE_FILE" exec -T pgvector \
  pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$FILEPATH"

FILE_SIZE=$(du -sh "$FILEPATH" | cut -f1)
log "Dump complete: ${FILE_SIZE}"

# ── Upload to S3-compatible storage (optional) ─────────────────────────────────
if [[ -n "$BACKUP_S3_BUCKET" ]]; then
  log "Uploading to S3: ${BACKUP_S3_BUCKET}/${FILENAME}"

  S3_ARGS=()
  if [[ -n "$BACKUP_S3_ENDPOINT" ]]; then
    S3_ARGS+=(--endpoint-url "$BACKUP_S3_ENDPOINT")
  fi

  if ! aws "${S3_ARGS[@]}" s3 cp "$FILEPATH" "${BACKUP_S3_BUCKET}/${FILENAME}"; then
    log "WARNING: S3 upload failed — backup kept locally"
  else
    log "S3 upload complete: ${BACKUP_S3_BUCKET}/${FILENAME}"
  fi
fi

# ── Prune local backups older than RETAIN_DAYS ────────────────────────────────
PRUNED=$(find "$BACKUP_DIR" -name "backup_*.sql.gz" -mtime "+${RETAIN_DAYS}" -print -delete | wc -l | tr -d ' ')
if [[ "$PRUNED" -gt 0 ]]; then
  log "Pruned ${PRUNED} backup(s) older than ${RETAIN_DAYS} days"
fi

log "SUCCESS: ${FILEPATH} (${FILE_SIZE})"

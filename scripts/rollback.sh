#!/usr/bin/env bash
# Engramia — Rollback na předchozí verzi
#
# Spouštěj na serveru z /opt/engramia/:
#   cd /opt/engramia && ./scripts/rollback.sh <prev-version> [migration-steps]
#
# Příklady:
#   ./scripts/rollback.sh 0.6.0       → rollback bez downgrade migrací
#   ./scripts/rollback.sh 0.6.0 1     → rollback + 1 krok alembic downgrade
#   ./scripts/rollback.sh 0.6.0 2     → rollback + 2 kroky alembic downgrade
#
# Environment variables:
#   COMPOSE_FILE   Cesta ke compose souboru (default: /opt/engramia/docker-compose.prod.yml)
#   BACKUP_DIR     Složka pro pre-rollback snapshot (default: /var/backups/engramia)
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-/opt/engramia/docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/engramia}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [rollback] $*"; }

# ── Argument validation ────────────────────────────────────────────────────────
PREV_VERSION="${1:-}"
MIGRATION_STEPS="${2:-0}"

if [[ -z "$PREV_VERSION" ]]; then
  echo "Usage: $0 <prev-version> [migration-steps]"
  echo "  Příklad: $0 0.6.0 1"
  exit 1
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
  log "ERROR: Compose file not found: ${COMPOSE_FILE}"
  exit 1
fi

# ── Confirmation ──────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ROLLBACK na Engramia ${PREV_VERSION}"
echo "║  Migration downgrade kroků: ${MIGRATION_STEPS}"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  Compose: ${COMPOSE_FILE}"
echo "  Snapshot bude uložen do: ${BACKUP_DIR}/"
echo ""
read -rp "  Pokračovat? Zadej 'yes': " CONFIRM
echo ""
[[ "$CONFIRM" == "yes" ]] || { log "Aborted by user."; exit 0; }

# ── 1. Maintenance mode ───────────────────────────────────────────────────────
log "Entering maintenance mode..."
# Odstraní případný existující záznam a přidá nový
grep -v 'ENGRAMIA_MAINTENANCE' .env > .env.tmp && mv .env.tmp .env
echo "ENGRAMIA_MAINTENANCE=true" >> .env

CURRENT_IMAGE_TAG=$(grep '^IMAGE_TAG=' .env | cut -d= -f2 || echo "latest")
IMAGE_TAG=$CURRENT_IMAGE_TAG docker compose -f "$COMPOSE_FILE" up -d engramia-api
log "Maintenance mode active — API returns 503 for all non-health endpoints."

# ── 2. Pre-rollback DB snapshot ───────────────────────────────────────────────
mkdir -p "$BACKUP_DIR"
SNAPSHOT="${BACKUP_DIR}/pre_rollback_$(date +%Y%m%d%H%M).dump"
log "Taking DB snapshot → ${SNAPSHOT}"
docker compose -f "$COMPOSE_FILE" exec -T pgvector \
  pg_dump -U engramia engramia -Fc > "$SNAPSHOT"
SNAP_SIZE=$(du -sh "$SNAPSHOT" | cut -f1)
log "Snapshot saved: ${SNAPSHOT} (${SNAP_SIZE})"

# ── 3. Migration downgrade ────────────────────────────────────────────────────
if [[ "$MIGRATION_STEPS" -gt 0 ]]; then
  log "Downgrading ${MIGRATION_STEPS} migration step(s)..."
  log "Current migration state:"
  IMAGE_TAG=$CURRENT_IMAGE_TAG docker compose -f "$COMPOSE_FILE" run --rm -T engramia-api \
    alembic current || true

  for i in $(seq 1 "$MIGRATION_STEPS"); do
    log "  Step ${i}/${MIGRATION_STEPS}: alembic downgrade -1"
    IMAGE_TAG=$CURRENT_IMAGE_TAG docker compose -f "$COMPOSE_FILE" run --rm -T engramia-api \
      alembic downgrade -1
  done
  log "Migration downgrade complete."
else
  log "Skipping migration downgrade (migration-steps=0)."
fi

# ── 4. Pull předchozího image ─────────────────────────────────────────────────
log "Pulling image: ghcr.io/engramia/engramia:${PREV_VERSION}"
IMAGE_TAG=$PREV_VERSION docker compose -f "$COMPOSE_FILE" pull engramia-api

# ── 5. Restart na předchozím image ───────────────────────────────────────────
log "Starting engramia-api and caddy with version ${PREV_VERSION}..."
IMAGE_TAG=$PREV_VERSION docker compose -f "$COMPOSE_FILE" up -d engramia-api caddy

# ── 6. Exit maintenance mode ──────────────────────────────────────────────────
log "Exiting maintenance mode..."
grep -v 'ENGRAMIA_MAINTENANCE' .env > .env.tmp && mv .env.tmp .env
IMAGE_TAG=$PREV_VERSION docker compose -f "$COMPOSE_FILE" up -d engramia-api

# ── 7. Verify ─────────────────────────────────────────────────────────────────
log "Waiting for API to respond..."
sleep 8

ACTUAL=$(curl -sf https://api.engramia.dev/v1/version \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('app_version','unknown'))" 2>/dev/null \
  || echo "unknown")

DEEP_HTTP=$(curl -sf -o /dev/null -w "%{http_code}" https://api.engramia.dev/v1/health/deep 2>/dev/null \
  || echo "000")

log "Rolled back version : ${ACTUAL} (expected: ${PREV_VERSION})"
log "Deep health HTTP    : ${DEEP_HTTP}"

if [[ "$ACTUAL" == "$PREV_VERSION" && "$DEEP_HTTP" == "200" ]]; then
  log "SUCCESS: Rollback to ${PREV_VERSION} complete."
  log "  Pre-rollback snapshot: ${SNAPSHOT}"
else
  log "WARNING: Verify manually:"
  log "  Version: curl -sf https://api.engramia.dev/v1/version"
  log "  Health:  curl -sf https://api.engramia.dev/v1/health/deep | python3 -m json.tool"
  log "  Logs:    docker compose -f ${COMPOSE_FILE} logs --tail=50 engramia-api"
  log "  Snapshot pro obnovu: ${SNAPSHOT}"
fi

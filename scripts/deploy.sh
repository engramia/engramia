#!/usr/bin/env bash
# Engramia — Manuální produkční deploy
#
# Spouštěj na serveru z /opt/engramia/:
#   cd /opt/engramia && ./scripts/deploy.sh 0.6.1
#
# Environment variables:
#   COMPOSE_FILE   Cesta ke compose souboru (default: /opt/engramia/docker-compose.prod.yml)
#   GHCR_TOKEN     GitHub Container Registry token (volitelné, pokud je docker už přihlášený)
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-/opt/engramia/docker-compose.prod.yml}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [deploy] $*"; }

# ── Argument validation ────────────────────────────────────────────────────────
VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: $0 <version>"
  echo "  Příklad: $0 0.6.1   (bez leading 'v')"
  exit 1
fi

IMAGE="ghcr.io/engramia/engramia:${VERSION}"
log "Deploying Engramia ${VERSION} (${IMAGE})"

# ── Pre-flight ─────────────────────────────────────────────────────────────────
if [[ ! -f "$COMPOSE_FILE" ]]; then
  log "ERROR: Compose file not found: ${COMPOSE_FILE}"
  exit 1
fi

if ! command -v docker &>/dev/null; then
  log "ERROR: docker not found in PATH"
  exit 1
fi

# ── GHCR login (pokud je token k dispozici) ───────────────────────────────────
if [[ -n "${GHCR_TOKEN:-}" ]]; then
  log "Logging into ghcr.io..."
  echo "$GHCR_TOKEN" | docker login ghcr.io -u engramia --password-stdin
fi

# ── Pull nového image ─────────────────────────────────────────────────────────
log "Pulling image: ${IMAGE}"
IMAGE_TAG=$VERSION docker compose -f "$COMPOSE_FILE" pull engramia-api

# ── Databáze ──────────────────────────────────────────────────────────────────
log "Ensuring pgvector is running..."
IMAGE_TAG=$VERSION docker compose -f "$COMPOSE_FILE" up -d pgvector

log "Waiting for pgvector to be healthy..."
for i in $(seq 1 18); do
  if docker compose -f "$COMPOSE_FILE" exec -T pgvector pg_isready -U engramia &>/dev/null; then
    log "pgvector is ready."
    break
  fi
  if [[ $i -eq 18 ]]; then
    log "ERROR: pgvector did not become healthy within 90s"
    log "Check: docker compose -f ${COMPOSE_FILE} logs pgvector"
    exit 1
  fi
  sleep 5
done

# ── Migrace ───────────────────────────────────────────────────────────────────
log "Running Alembic migrations (upgrade head)..."
IMAGE_TAG=$VERSION docker compose -f "$COMPOSE_FILE" run --rm -T engramia-api \
  alembic upgrade head

# ── Restart API + Caddy ───────────────────────────────────────────────────────
log "Starting engramia-api and caddy..."
IMAGE_TAG=$VERSION docker compose -f "$COMPOSE_FILE" up -d engramia-api caddy

# ── Prune starých images ──────────────────────────────────────────────────────
log "Pruning dangling images..."
docker image prune -f

# ── Smoke test ────────────────────────────────────────────────────────────────
log "Waiting for API to become healthy..."
for i in $(seq 1 12); do
  HTTP=$(curl -sf -o /dev/null -w "%{http_code}" https://api.engramia.dev/v1/health 2>/dev/null || echo "000")
  if [[ "$HTTP" == "200" ]]; then
    log "API is healthy (HTTP 200)."
    break
  fi
  if [[ $i -eq 12 ]]; then
    log "WARNING: API did not return 200 within 60s (last status: ${HTTP})"
    log "  Check logs: docker compose -f ${COMPOSE_FILE} logs --tail=50 engramia-api"
  fi
  sleep 5
done

# ── Version check ─────────────────────────────────────────────────────────────
ACTUAL=$(curl -sf https://api.engramia.dev/v1/version \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('app_version','unknown'))" 2>/dev/null \
  || echo "unknown")

log "Deployed version: ${ACTUAL} (expected: ${VERSION})"

if [[ "$ACTUAL" != "$VERSION" ]]; then
  log "WARNING: Version mismatch — expected ${VERSION}, got ${ACTUAL}"
  log "  Verify: curl -sf https://api.engramia.dev/v1/version"
fi

# ── Deep health ───────────────────────────────────────────────────────────────
DEEP_HTTP=$(curl -sf -o /dev/null -w "%{http_code}" https://api.engramia.dev/v1/health/deep 2>/dev/null || echo "000")
log "Deep health HTTP status: ${DEEP_HTTP}"

if [[ "$DEEP_HTTP" != "200" ]]; then
  log "WARNING: Deep health returned ${DEEP_HTTP} — inspect:"
  curl -sf https://api.engramia.dev/v1/health/deep | python3 -m json.tool || true
fi

log "SUCCESS: Deploy of Engramia ${VERSION} complete."

#!/bin/bash
# /opt/engramia/scripts/seed-staging.sh
# Seed the staging database with test data.
# Snapshots current staging DB before reset so you can restore if needed.
#
# Usage: ./scripts/seed-staging.sh
# Requires: .env.staging loaded (or STAGING_POSTGRES_PASSWORD in env)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKUP_DIR="${PROJECT_DIR}/backups"
CONTAINER="engramia-pgvector-staging"

# Load staging env if not already set
if [ -z "${STAGING_POSTGRES_PASSWORD:-}" ] && [ -f "${PROJECT_DIR}/.env.staging" ]; then
    set -o allexport
    # shellcheck disable=SC1091
    source "${PROJECT_DIR}/.env.staging"
    set +o allexport
fi

if [ -z "${STAGING_POSTGRES_PASSWORD:-}" ]; then
    echo "Error: STAGING_POSTGRES_PASSWORD not set." >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

# ── 1. Snapshot current staging DB ───────────────────────────────────────────
echo "==> Snapshotting current staging DB..."
SNAPSHOT_FILE="${BACKUP_DIR}/staging-pre-seed-$(date +%Y%m%d-%H%M).sql.gz"
docker exec "$CONTAINER" pg_dump -U engramia_staging engramia_staging 2>/dev/null \
    | gzip > "$SNAPSHOT_FILE" || true
echo "    Snapshot: $SNAPSHOT_FILE"

# ── 2. Run migrations ─────────────────────────────────────────────────────────
echo "==> Running migrations on staging..."
docker exec engramia-api-staging alembic upgrade head

# ── 3. Seed test data ─────────────────────────────────────────────────────────
echo "==> Seeding test data..."
docker exec -i "$CONTAINER" psql -U engramia_staging -d engramia_staging << 'SQL'

-- Test users (Stripe test mode customer IDs)
INSERT INTO users (email, name, stripe_customer_id, plan, created_at) VALUES
  ('test-free@engramia.dev',       'Test Free User',      'cus_test_free_001',   'free',       NOW()),
  ('test-pro@engramia.dev',        'Test Pro User',       'cus_test_pro_001',    'pro',        NOW()),
  ('test-enterprise@engramia.dev', 'Test Enterprise',     'cus_test_ent_001',    'enterprise', NOW()),
  ('test-trial@engramia.dev',      'Test Trial User',     'cus_test_trial_001',  'trial',      NOW()),
  ('test-cancelled@engramia.dev',  'Test Cancelled',      'cus_test_cancel_001', 'cancelled',  NOW())
ON CONFLICT (email) DO NOTHING;

SQL

echo "==> Staging DB seeded."

#!/bin/bash
# /opt/engramia/scripts/reset-test-db.sh
# Reset the test database: drop → recreate → migrate.
# Called before each integration test run.
#
# Usage: ./scripts/reset-test-db.sh
# Requires: pgvector-test container running

set -euo pipefail

CONTAINER="engramia-pgvector-test"
API_CONTAINER="engramia-api-test"
DB_USER="engramia_test"
DB_NAME="engramia_test"

# Verify containers are running
if ! docker inspect "$CONTAINER" > /dev/null 2>&1; then
    echo "Error: $CONTAINER is not running. Start the test environment first." >&2
    exit 1
fi

echo "==> Resetting test database..."

# Terminate active connections
docker exec "$CONTAINER" psql -U "$DB_USER" -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();" \
    > /dev/null 2>&1 || true

# Drop and recreate
docker exec "$CONTAINER" psql -U "$DB_USER" -d postgres -c \
    "DROP DATABASE IF EXISTS ${DB_NAME}; CREATE DATABASE ${DB_NAME};"

echo "==> Running migrations..."
docker exec "$API_CONTAINER" alembic upgrade head

echo "==> Test DB ready."

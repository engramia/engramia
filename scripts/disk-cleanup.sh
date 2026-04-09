#!/bin/bash
# /opt/engramia/scripts/disk-cleanup.sh
# Weekly disk cleanup — removes unused Docker images, dangling volumes, old backups.
# Cron: 0 3 * * 0  (every Sunday at 03:00 UTC)
#
# Install cron:
#   chmod +x /opt/engramia/scripts/disk-cleanup.sh
#   (crontab -l 2>/dev/null; echo "0 3 * * 0 /opt/engramia/scripts/disk-cleanup.sh >> /var/log/engramia-cleanup.log 2>&1") | crontab -

set -euo pipefail

BACKUP_DIR="/opt/engramia/backups"
LOG_PREFIX="[$(date -u +%Y-%m-%dT%H:%M:%SZ)]"

echo "$LOG_PREFIX Disk cleanup started"
echo "$LOG_PREFIX Disk usage before: $(df -h / | tail -1 | awk '{print $3"/"$2, "("$5")"}')"

# ── 1. Remove unused Docker images (older than 7 days) ───────────────────────
docker image prune -a --filter "until=168h" -f > /dev/null
echo "$LOG_PREFIX Docker image prune: done"

# ── 2. Remove dangling volumes (unnamed only) ─────────────────────────────────
docker volume prune -f > /dev/null
echo "$LOG_PREFIX Docker volume prune: done"

# ── 3. Remove build cache older than 7 days ───────────────────────────────────
docker builder prune --filter "until=168h" -f > /dev/null
echo "$LOG_PREFIX Docker builder prune: done"

# ── 4. Rotate prod DB backups — keep last 14 ─────────────────────────────────
if [ -d "$BACKUP_DIR" ]; then
    old_backups=$(ls -t "${BACKUP_DIR}"/engramia-prod-*.sql.gz 2>/dev/null | tail -n +15 || true)
    if [ -n "$old_backups" ]; then
        echo "$old_backups" | xargs rm
        echo "$LOG_PREFIX Old prod backups removed"
    fi
    old_staging=$(ls -t "${BACKUP_DIR}"/staging-pre-seed-*.sql.gz 2>/dev/null | tail -n +8 || true)
    if [ -n "$old_staging" ]; then
        echo "$old_staging" | xargs rm
        echo "$LOG_PREFIX Old staging snapshots removed"
    fi
fi

echo "$LOG_PREFIX Disk usage after: $(df -h / | tail -1 | awk '{print $3"/"$2, "("$5")"}')"
echo "$LOG_PREFIX Disk cleanup finished"

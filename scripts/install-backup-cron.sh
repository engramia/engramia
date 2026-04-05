#!/usr/bin/env bash
# Install Engramia backup cron jobs
# Idempotent — safe to run multiple times.
#
# Installs:
#   Daily backup   — every day at 02:00
#   Weekly backup  — every Sunday at 03:00
#
# Logs go to /var/log/engramia-backup.log
set -euo pipefail

CRON_FILE="/etc/cron.d/engramia-backup"
LOG_FILE="/var/log/engramia-backup.log"

# ── Root check ─────────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: This script must be run as root (requires write access to /etc/cron.d/)"
  exit 1
fi

# ── Resolve the scripts directory ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPT="${SCRIPT_DIR}/backup.sh"

if [[ ! -x "$BACKUP_SCRIPT" ]]; then
  echo "ERROR: backup.sh not found or not executable: ${BACKUP_SCRIPT}"
  exit 1
fi

# ── Ensure log file exists ─────────────────────────────────────────────────────
touch "$LOG_FILE"
chmod 640 "$LOG_FILE"

# ── Write cron file (overwrites previous version — idempotent) ─────────────────
cat > "$CRON_FILE" << EOF
# Engramia automated backup jobs
# Managed by ${SCRIPT_DIR}/install-backup-cron.sh — do not edit manually.
# Re-run that script to update.

SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

# Daily backup — every day at 02:00
0 2 * * * root ${BACKUP_SCRIPT} >> ${LOG_FILE} 2>&1

# Weekly full backup — every Sunday at 03:00
0 3 * * 0 root ${BACKUP_SCRIPT} >> ${LOG_FILE} 2>&1
EOF

chmod 644 "$CRON_FILE"

echo "Cron jobs installed: ${CRON_FILE}"
echo ""
echo "Schedule:"
echo "  Daily  — every day at 02:00"
echo "  Weekly — every Sunday at 03:00"
echo ""
echo "Logs: ${LOG_FILE}"
echo ""
echo "To verify:"
echo "  cat ${CRON_FILE}"
echo "  tail -f ${LOG_FILE}"

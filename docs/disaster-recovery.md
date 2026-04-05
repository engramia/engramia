# Disaster Recovery Runbook

Engramia · Classification: Internal · Owner: On-call engineer

---

## RTO / RPO Targets

| Scenario | RPO (max data loss) | RTO (max downtime) | Severity |
|----------|--------------------|--------------------|----------|
| DB corruption (partial) | Last backup (≤24 h) | 2 hours | P0 |
| VM crash / hard reboot | Last backup (≤24 h) | 1 hour | P0 |
| Accidental data delete | Last backup (≤24 h) | 2 hours | P0–P1 |
| Stripe outage | N/A (no data loss) | Until Stripe recovers | P2 |
| LLM provider outage | N/A (no data loss) | Until provider recovers | P2 |

Backups run daily at 02:00 UTC. Weekly backups retained for 90 days.
See `scripts/backup.sh` and `scripts/install-backup-cron.sh` for configuration.

---

## Backup Verification (run weekly)

```bash
# 1. Confirm latest backup exists and is recent
ssh root@engramia-staging 'ls -lht /var/backups/engramia/ | head -5'

# 2. Verify backup integrity (check it can be decompressed and parsed)
ssh root@engramia-staging '
  LATEST=$(ls -t /var/backups/engramia/backup_*.sql.gz | head -1)
  echo "Testing: $LATEST"
  gunzip -t "$LATEST" && echo "OK: gzip integrity check passed"
  gunzip -c "$LATEST" | head -5    # Should print SQL header lines
'

# 3. Optionally restore to a test database
ssh root@engramia-staging '
  LATEST=$(ls -t /var/backups/engramia/backup_*.sql.gz | head -1)
  docker compose -f /opt/engramia/docker-compose.prod.yml exec -T pgvector \
    psql -U engramia postgres -c "CREATE DATABASE engramia_test OWNER engramia;" 2>/dev/null || true
  gunzip -c "$LATEST" | docker compose -f /opt/engramia/docker-compose.prod.yml exec -T pgvector \
    psql -U engramia engramia_test
  docker compose -f /opt/engramia/docker-compose.prod.yml exec -T pgvector \
    psql -U engramia engramia_test -c "SELECT COUNT(*) FROM memory_patterns;"
  docker compose -f /opt/engramia/docker-compose.prod.yml exec -T pgvector \
    psql -U engramia postgres -c "DROP DATABASE engramia_test;"
  echo "Verification complete."
'
```

---

## Scenario 1: Database Corruption

**Symptoms:** API returns 503 "storage unavailable"; `pg_isready` returns unhealthy;
PostgreSQL logs show `invalid page` / `checksum mismatch` / `PANIC`.

### Step 1 — Diagnose

```bash
ssh root@engramia-staging
cd /opt/engramia

# Check container health
docker compose -f docker-compose.prod.yml ps pgvector

# Review PostgreSQL logs
docker compose -f docker-compose.prod.yml logs pgvector --tail 100

# Test database accessibility
docker compose -f docker-compose.prod.yml exec pgvector \
  psql -U engramia engramia -c "SELECT COUNT(*) FROM memory_patterns;" 2>&1
```

### Step 2 — Enter maintenance mode

```bash
echo "ENGRAMIA_MAINTENANCE=true" >> .env
docker compose -f docker-compose.prod.yml up -d engramia-api
```

### Step 3 — Attempt in-place recovery (minor corruption)

```bash
# Try PostgreSQL autovacuum recovery
docker compose -f docker-compose.prod.yml exec pgvector \
  psql -U engramia engramia -c "VACUUM FULL;"

# If that fails, try pg_resetwal (last resort — data loss possible)
# Only use after consulting Hetzner support.
```

### Step 4 — Full restore from backup

If in-place recovery fails, proceed to **full restore** (Scenario 2, Step 3+).

---

## Scenario 2: VM Crash / Hard Reboot

**Symptoms:** SSH unreachable; Hetzner console shows server stopped or in error state.

### Step 1 — Recover the VM

```bash
# Option A: Reboot from Hetzner Cloud Console
# https://console.hetzner.cloud → Servers → engramia-staging → Power → Reboot

# Option B: Reboot via hcloud CLI
hcloud server reboot engramia-staging
```

### Step 2 — Verify auto-recovery

All services have `restart: unless-stopped` — they start automatically on boot.

```bash
ssh root@engramia-staging '
  docker compose -f /opt/engramia/docker-compose.prod.yml ps
'
# Wait ~60s for API healthcheck to pass

curl -sf https://api.engramia.dev/v1/health && echo "OK"
```

### Step 3 — If API does not recover automatically

```bash
ssh root@engramia-staging
cd /opt/engramia

# Bring all services up
docker compose -f docker-compose.prod.yml up -d

# Monitor startup
docker compose -f docker-compose.prod.yml logs -f --tail 50
```

### Step 4 — If database is corrupted after crash

PostgreSQL may have journal replay issues after a hard crash. If `pg_isready` fails:

```bash
# Find the latest clean backup
ls -lht /var/backups/engramia/ | head -5

# Run the restore script
cd /opt/engramia
./scripts/restore.sh /var/backups/engramia/backup_YYYY-MM-DD_HH-MM.sql.gz
```

The `restore.sh` script will:
1. Stop `engramia-api`
2. Drop and recreate the database
3. Restore from the backup file
4. Run `alembic upgrade head`
5. Start `engramia-api` and wait for healthcheck

---

## Scenario 3: Accidental Data Delete

**Symptoms:** Tenant reports missing data; `DELETE` events visible in audit log.

### Step 1 — Identify the scope

```bash
ssh root@engramia-staging
docker compose -f /opt/engramia/docker-compose.prod.yml exec pgvector \
  psql -U engramia engramia -c "
    SELECT key_id, action, resource_type, resource_id, ts
    FROM audit_log
    WHERE action IN ('SCOPE_DELETED', 'PATTERN_DELETED', 'KEY_DELETED')
    ORDER BY ts DESC
    LIMIT 50;
  "
```

### Step 2 — Take a safety backup of current state

```bash
ssh root@engramia-staging \
  'BACKUP_DIR=/var/backups/engramia /opt/engramia/scripts/backup.sh'
```

### Step 3a — Point-in-time restore (single scope, low blast radius)

If only one tenant's scope was deleted and the database is otherwise healthy:

```bash
# Restore to a separate DB to extract specific rows
ssh root@engramia-staging '
  BACKUP=/var/backups/engramia/backup_YYYY-MM-DD_HH-MM.sql.gz
  docker compose -f /opt/engramia/docker-compose.prod.yml exec -T pgvector \
    psql -U engramia postgres -c "CREATE DATABASE engramia_restore OWNER engramia;"
  gunzip -c "$BACKUP" | docker compose -f /opt/engramia/docker-compose.prod.yml exec -T pgvector \
    psql -U engramia engramia_restore

  # Extract the deleted rows and re-insert them into the live DB
  docker compose -f /opt/engramia/docker-compose.prod.yml exec -T pgvector \
    psql -U engramia engramia_restore -c "
      COPY (SELECT * FROM memory_patterns WHERE scope = '\''<SCOPE_ID>'\'')
      TO '\''/tmp/recover_scope.csv'\'' CSV HEADER;
    "
  # Then import into live engramia DB (manual step — validate before inserting)
'
```

### Step 3b — Full restore (large-scale delete, multiple scopes)

```bash
cd /opt/engramia
./scripts/restore.sh /var/backups/engramia/backup_YYYY-MM-DD_HH-MM.sql.gz
```

### Step 4 — Notify affected tenant(s)

If personal data was involved, GDPR breach notification may apply (72 h window).
See [incident-response.md](runbooks/incident-response.md) — "P0 Response: Data Breach".

---

## Scenario 4: Stripe Outage

**Symptoms:** `POST /v1/subscribe` or webhook delivery fails; Stripe dashboard shows degraded.

**Impact:** New subscriptions and billing events cannot be processed. **Existing API access is unaffected** — authentication uses API keys, not Stripe.

### During the outage

1. Monitor https://status.stripe.com
2. No action required for existing subscribers — API continues to work normally.
3. New sign-ups will receive a 503 error; retry is safe (idempotent by `idempotency_key`).

### After Stripe recovers

```bash
# Check for failed webhook deliveries in Stripe Dashboard
# Stripe retries failed webhooks automatically for up to 72 hours.

# Manually trigger missed webhooks (if needed):
# Stripe Dashboard → Developers → Webhooks → [endpoint] → Recent deliveries → Retry

# Verify subscription states are in sync
docker compose -f /opt/engramia/docker-compose.prod.yml exec pgvector \
  psql -U engramia engramia -c "
    SELECT status, COUNT(*) FROM subscriptions
    GROUP BY status ORDER BY status;
  "
```

### If a subscription state is stuck

```bash
# Fetch current state from Stripe API and reconcile manually
curl https://api.stripe.com/v1/subscriptions/<sub_id> \
  -u "$STRIPE_SECRET_KEY:"

# Update local DB if needed (use with care — document in incident log)
docker compose -f /opt/engramia/docker-compose.prod.yml exec pgvector \
  psql -U engramia engramia -c "
    UPDATE subscriptions SET status = 'active', updated_at = NOW()
    WHERE stripe_subscription_id = '<sub_id>';
  "
```

---

## Scenario 5: LLM Provider Outage

See [runbooks/llm-provider-outage.md](runbooks/llm-provider-outage.md) for full details.

**Summary:**
- `learn` and `recall` endpoints are **unaffected** — no LLM required.
- `evaluate`, `compose`, `evolve` return 503 during outage.
- Built-in retry (3× exponential backoff) handles transient failures automatically.
- To switch provider: update `ENGRAMIA_LLM_PROVIDER` in `.env` and restart API.
- To disable LLM features: set `ENGRAMIA_LLM_PROVIDER=none`.

---

## Rollback Procedure (bad deploy)

See [runbooks/deploy-rollback.md](runbooks/deploy-rollback.md) for the full procedure.

**Quick reference:**

```bash
# Identify the last known-good image tag
ssh root@engramia-staging \
  'docker images ghcr.io/engramia/engramia --format "{{.Tag}}\t{{.CreatedAt}}" | sort -k2 -r | head -5'

# Roll back
ROLLBACK_TAG=v0.6.4
ssh root@engramia-staging "
  cd /opt/engramia
  IMAGE_TAG=${ROLLBACK_TAG} docker compose -f docker-compose.prod.yml up -d engramia-api
"

# Verify
curl -sf https://api.engramia.dev/v1/health | jq '.version'

# If a migration must also be rolled back:
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml exec engramia-api alembic downgrade -1'
```

---

## Escalation Matrix

| Situation | First contact | Escalation |
|-----------|--------------|-----------|
| API down > 15 min | On-call engineer | Founder direct |
| DB corruption confirmed | On-call engineer | Hetzner support ticket |
| Data breach suspected | security@engramia.dev | Founder + legal@engramia.dev |
| GDPR notification required | legal@engramia.dev | Czech DPA: uoou.gov.cz (72 h SLA) |
| Stripe billing issue | On-call engineer | Stripe support dashboard |
| LLM provider down > 2 h | Monitor status page | Switch provider (see Scenario 5) |

---

## Related Runbooks

- [backup-restore.md](backup-restore.md) — backup configuration and manual restore steps
- [runbooks/database-recovery.md](runbooks/database-recovery.md) — PostgreSQL-specific recovery cases
- [runbooks/incident-response.md](runbooks/incident-response.md) — P0/P1 response playbook and post-mortem template
- [runbooks/deploy-rollback.md](runbooks/deploy-rollback.md) — deploy and rollback procedure
- [runbooks/llm-provider-outage.md](runbooks/llm-provider-outage.md) — LLM provider failover
- [runbooks/disk-full.md](runbooks/disk-full.md) — disk space recovery

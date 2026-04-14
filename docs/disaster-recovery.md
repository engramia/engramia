# Disaster Recovery

High-level DR principles for Engramia self-hosted deployments. For operator-specific
playbooks (on-call escalation, hosting-provider steps, incident contacts), see the
individual runbooks linked below.

---

## RTO / RPO Targets

| Scenario | RPO (max data loss) | RTO (max downtime) | Severity |
|----------|--------------------|--------------------|----------|
| DB corruption (partial) | Last backup (≤24 h) | 2 hours | P0 |
| VM crash / hard reboot | Last backup (≤24 h) | 1 hour | P0 |
| Accidental data delete | Last backup (≤24 h) | 2 hours | P0–P1 |
| Stripe outage | N/A (no data loss) | Until Stripe recovers | P2 |
| LLM provider outage | N/A (no data loss) | Until provider recovers | P2 |

These targets assume daily backups. Adjust your backup cadence to match the
RPO you want to guarantee.

---

## Backup Strategy

Engramia ships `scripts/backup.sh` — a `pg_dump`-based script that writes
compressed SQL dumps locally and optionally uploads to any S3-compatible
object storage. Install the recommended schedule with
`scripts/install-backup-cron.sh`:

- Daily backup (retained 30 days by default)
- Weekly backup (retained 90 days)

Verify backup integrity weekly: decompress the latest dump, load it into a
throwaway database, and assert row counts on your key tables. The
`scripts/test_backup_restore.py` test exercises the full backup → restore
loop and is the reference for what "verified" means.

---

## Scenarios

### 1. Database corruption
PostgreSQL logs show `invalid page` / `checksum mismatch` / `PANIC`,
`pg_isready` returns unhealthy, API returns 503.

1. Enter maintenance mode (`ENGRAMIA_MAINTENANCE=true` in `.env`, restart API).
2. Attempt in-place recovery (`VACUUM FULL`). Consult your hosting provider
   before using destructive tools like `pg_resetwal`.
3. If in-place recovery fails, full restore from the latest verified backup —
   see [runbooks/database-recovery.md](runbooks/database-recovery.md) Case 4.

### 2. VM crash / hard reboot
Services use `restart: unless-stopped` and recover automatically on boot.
If the API healthcheck does not pass within ~60 seconds after reboot,
follow [runbooks/database-recovery.md](runbooks/database-recovery.md) —
PostgreSQL may need a WAL replay or restore after an unclean shutdown.

### 3. Accidental data delete
1. Inspect the `audit_log` table to scope the deletion.
2. Snapshot current state before any restore (`scripts/backup.sh`).
3. For a single tenant or scope: restore the latest backup into a separate
   database, `COPY` the deleted rows out, import into the live DB.
4. For large-scale loss: full restore via `scripts/restore.sh`.
5. If personal data was involved, GDPR breach notification may apply
   (72-hour window). See [incident-response-plan.md](incident-response-plan.md).

### 4. Stripe outage
Existing API access is unaffected — Engramia auth uses API keys, not Stripe.
New sign-ups return 503; retries are idempotent via `idempotency_key`.
After Stripe recovers, reconcile subscription state and re-trigger any missed
webhooks from the Stripe dashboard.

### 5. LLM provider outage
`learn` and `recall` are unaffected (no LLM required). `evaluate`, `compose`,
and `evolve` return 503. Built-in retry with exponential backoff handles
transient failures; for extended outages, switch provider via
`ENGRAMIA_LLM_PROVIDER` or set it to `none` to disable LLM features.
See [runbooks/llm-provider-outage.md](runbooks/llm-provider-outage.md).

### 6. Bad deploy
See [runbooks/deploy-rollback.md](runbooks/deploy-rollback.md). Engramia
images are tagged immutably, so rollback is a matter of redeploying the
previous `IMAGE_TAG` and, if necessary, `alembic downgrade -1`.

---

## Related Runbooks

- [backup-restore.md](backup-restore.md) — backup configuration and manual restore
- [runbooks/database-recovery.md](runbooks/database-recovery.md) — PostgreSQL recovery cases
- [runbooks/deploy-rollback.md](runbooks/deploy-rollback.md) — deploy and rollback
- [runbooks/llm-provider-outage.md](runbooks/llm-provider-outage.md) — LLM failover
- [runbooks/disk-full.md](runbooks/disk-full.md) — disk space recovery
- [incident-response-plan.md](incident-response-plan.md) — severity matrix and IR procedures

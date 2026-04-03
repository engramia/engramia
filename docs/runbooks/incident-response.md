# Incident Response Playbook

Engramia v0.6.0 · Classification: Internal

---

## Severity Levels

| Severity | Definition | Response time | Examples |
|----------|------------|--------------|---------|
| **P0 — Critical** | Production down or data breach | 1 hour | API unreachable, DB down, confirmed key leak |
| **P1 — High** | Degraded service, security concern | 4 hours | High latency, failed auth in audit log, disk >90% |
| **P2 — Medium** | Non-critical failure, data quality | 24 hours | Aging job failed, backup failed, elevated error rate |
| **P3 — Low** | Cosmetic, no user impact | 72 hours | Dashboard chart missing, log noise |

---

## Contact Points

| Role | Contact | Escalation |
|------|---------|-----------|
| On-call engineer | Defined per rotation | Next engineer in rotation |
| Security incidents | security@engramia.dev | Founder direct |
| Infrastructure | Hetzner Cloud Console | Hetzner support ticket |
| Legal / GDPR DPA | legal@engramia.dev | Czech DPA (uoou.gov.cz) |

---

## P0 Response: API Unreachable

### Detection

```bash
curl -sf https://api.engramia.dev/v1/health || echo "DOWN"
```

### Diagnosis

```bash
ssh root@engramia-staging
cd /opt/engramia

# Check container status
docker compose -f docker-compose.prod.yml ps

# Check recent logs (last 100 lines)
docker compose -f docker-compose.prod.yml logs --tail=100 engramia-api

# Check Caddy
docker compose -f docker-compose.prod.yml logs --tail=50 caddy

# Check DB
docker compose -f docker-compose.prod.yml exec pgvector pg_isready -U engramia
```

### Common fixes

**Container exited:**
```bash
docker compose -f docker-compose.prod.yml up -d
```

**Out of memory:**
```bash
free -h
# If OOM: check if pgvector is consuming too much
docker stats --no-stream
```

**Disk full:**
See [disk-full.md](disk-full.md) runbook.

**DB connection refused:**
```bash
docker compose -f docker-compose.prod.yml restart pgvector
sleep 10
docker compose -f docker-compose.prod.yml restart engramia-api
```

---

## P0 Response: Data Breach / Compromised API Key

### Immediate containment (< 15 minutes)

```bash
# 1. Revoke the compromised key immediately
curl -X DELETE https://api.engramia.dev/v1/keys/{KEY_ID} \
  -H "Authorization: Bearer $OWNER_KEY"

# 2. If the owner key is compromised — rotate via direct DB access
ssh root@engramia-staging
docker compose -f /opt/engramia/docker-compose.prod.yml exec pgvector \
  psql -U engramia engramia \
  -c "UPDATE api_keys SET revoked_at = NOW() WHERE role = 'owner';"

# 3. Enter maintenance mode to stop all access
cd /opt/engramia
echo "ENGRAMIA_MAINTENANCE=true" >> .env
docker compose -f docker-compose.prod.yml up -d
```

### Investigation

```bash
# Review audit log for the compromised key ID
docker compose -f /opt/engramia/docker-compose.prod.yml exec pgvector \
  psql -U engramia engramia \
  -c "SELECT * FROM audit_log WHERE key_id = '{KEY_ID}' ORDER BY ts DESC LIMIT 100;"

# Check what data was accessed
# - AUTH_FAILURE events: unauthorized probing
# - SCOPE_EXPORTED: data was exported
# - SCOPE_DELETED: data was deleted
```

### Notification

- [ ] Notify affected tenants (data subjects) within **72 hours** (GDPR Art. 33)
- [ ] File DPA notification if personal data was accessed: https://www.uoou.cz
- [ ] Document: when discovered, what data was accessible, scope of access, remediation taken

### Recovery

1. Issue new API keys to affected tenants
2. Review and tighten permissions (reduce to minimum required role)
3. Enable audit log monitoring alerts
4. Post-mortem within 5 business days

---

## P1 Response: High API Latency

```bash
# Check deep health
curl https://api.engramia.dev/v1/health/deep \
  -H "Authorization: Bearer $OWNER_KEY"
# Look for degraded/error components

# Check Prometheus metrics (if enabled)
curl https://api.engramia.dev/metrics | grep engramia_requests_duration

# Check DB performance
docker compose exec pgvector \
  psql -U engramia engramia \
  -c "SELECT pid, wait_event_type, wait_event, state, query FROM pg_stat_activity WHERE state != 'idle';"
```

See [high-latency.md](high-latency.md) for detailed diagnosis steps.

---

## P1 Response: Backup Failure

```bash
# Check backup log
tail -50 /var/log/engramia-backup.log

# Manual backup
/opt/engramia/scripts/backup.sh

# Verify object storage connectivity
aws --endpoint-url https://fsn1.your-objectstorage.com s3 ls s3://engramia-backups/
```

See [backup-restore.md](../backup-restore.md) for full restore procedures.

---

## P0 Response: Database Corruption

```bash
# Check PostgreSQL logs
docker compose -f /opt/engramia/docker-compose.prod.yml logs pgvector | grep -i error

# Run pg integrity check
docker compose exec pgvector pg_dumpall -U engramia --globals-only > /dev/null \
  && echo "DB accessible" || echo "DB corrupted"
```

If corruption confirmed:
1. Stop the API (enter maintenance mode)
2. Take a dump of what's recoverable: `pg_dump --no-synchronous-commit`
3. Restore from last clean backup (see [backup-restore.md](../backup-restore.md))
4. Apply any recoverable transactions from the partial dump

---

## Post-Incident: Blameless Post-Mortem Template

```markdown
## Incident: [title] — [date]

**Severity:** P0/P1/P2
**Duration:** [start] → [end] ([X] minutes)
**Impact:** [what was affected, how many tenants]

### Timeline
- HH:MM — [event]
- HH:MM — [detection]
- HH:MM — [first action]
- HH:MM — [resolution]

### Root Cause
[1-3 sentence description]

### What Went Well
-

### What Could Be Improved
-

### Action Items
| Action | Owner | Due |
|--------|-------|-----|
| | | |
```

---

## SOC 2 Incident Classification

For SOC 2 Type II purposes, incidents must be classified and logged:

| Category | SOC 2 Criterion |
|----------|----------------|
| Unauthorized access | CC6.1, CC6.7 |
| Availability incident | A1.1, A1.2 |
| Data loss | A1.3, CC9.1 |
| System failure | CC7.1, CC7.2 |

Log all P0/P1 incidents in the incident register (`docs/incident-register.md`) within 24 hours of resolution.

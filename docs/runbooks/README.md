# Operational Runbooks — Engramia

Quick-reference guides for common production issues on `api.engramia.dev`
(**Hetzner PROD**, CX23, SSH alias `engramia-staging` in `~/.ssh/config`).

## Runbooks

| Runbook | When to use |
|---------|-------------|
| [disk-full.md](disk-full.md) | `df -h` shows 100%, API returning 500s |
| [high-latency.md](high-latency.md) | p95 latency > 2s, timeouts reported |
| [deploy-rollback.md](deploy-rollback.md) | Deploy to prod, or roll back a bad release |
| [database-recovery.md](database-recovery.md) | PostgreSQL unhealthy, data loss suspected |
| [api-key-rotation.md](api-key-rotation.md) | Key compromise, offboarding, 90-day rotation |
| [maintenance-mode.md](maintenance-mode.md) | Planned downtime, schema migrations |
| [rate-limit-tuning.md](rate-limit-tuning.md) | Legitimate clients hitting 429s, or cost spikes |
| [certificate-renewal.md](certificate-renewal.md) | TLS cert expiry, HTTPS errors |

## Common Quick Commands

```bash
# Health check
curl https://api.engramia.dev/v1/health

# View live API logs
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml logs -f engramia-api'

# Restart API (no downtime for active connections)
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml restart engramia-api'

# Check all container statuses
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml ps'
```

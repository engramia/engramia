# Runbook: Deploy & Rollback

## Standard Deploy

```bash
# From GitHub Actions (automatic on release):
# .github/workflows/docker.yml builds image and tags as v0.x.y
# .github/workflows/publish.yml deploys via SSH

# Manual deploy:
ssh root@engramia-staging '
  cd /opt/engramia
  IMAGE_TAG=v0.5.4 docker compose -f docker-compose.prod.yml pull engramia-api
  IMAGE_TAG=v0.5.4 docker compose -f docker-compose.prod.yml up -d engramia-api
'
```

## Verify Deploy

```bash
# Health check
curl -f https://api.engramia.dev/v1/health
# Expected: {"status": "ok", "version": "0.5.4", ...}

# Deep health (checks DB + embeddings)
curl -f https://api.engramia.dev/v1/health/deep \
  -H "Authorization: Bearer $ENGRAMIA_API_KEY"
```

## Rollback

### Step 1 — Identify the previous working version
```bash
ssh root@engramia-staging 'docker images ghcr.io/engramia/engramia --format "{{.Tag}}\t{{.CreatedAt}}" | sort -k2 -r | head -10'
```

### Step 2 — Rollback to previous image
```bash
ROLLBACK_TAG=v0.5.3  # replace with the target version

ssh root@engramia-staging "
  cd /opt/engramia
  IMAGE_TAG=${ROLLBACK_TAG} docker compose -f docker-compose.prod.yml up -d engramia-api
"
```

### Step 3 — Verify rollback succeeded
```bash
curl -f https://api.engramia.dev/v1/health
# Confirm version matches the rolled-back tag
```

### Step 4 — If database migration needs rollback (Alembic)

CAUTION: Only run if the new version introduced a migration that must be reversed.

```bash
# Check current revision
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml exec engramia-api \
     alembic current'

# Downgrade one step
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml exec engramia-api \
     alembic downgrade -1'
```

## Symptoms Requiring Rollback
- `/v1/health` returns non-200 after deploy
- Spike in 500 errors in logs immediately post-deploy
- Alembic migration fails during startup

## Prevention
- Always pin `IMAGE_TAG` — never use `:latest` in prod
- Run migrations in a separate step before switching traffic
- Keep the previous 2 image versions available on the registry

# Runbook: API Key Rotation

## When to Rotate
- Suspected key compromise
- Regular rotation policy (every 90 days recommended)
- Employee/service offboarding

## Rotating a Key (DB auth mode)

### Step 1 — Find the key ID
```bash
curl https://api.engramia.dev/v1/keys \
  -H "Authorization: Bearer $ENGRAMIA_ADMIN_KEY" | jq '.[] | {id, label, role, created_at}'
```

### Step 2 — Rotate the key
```bash
KEY_ID="key-uuid-here"

NEW_KEY=$(curl -s -X POST \
  https://api.engramia.dev/v1/keys/${KEY_ID}/rotate \
  -H "Authorization: Bearer $ENGRAMIA_ADMIN_KEY" \
  | jq -r '.key')

echo "New key: $NEW_KEY"
# Store securely — this is the only time the plaintext is shown
```

### Step 3 — Distribute new key to clients
Update the secret in:
- GitHub Actions secrets (`ENGRAMIA_API_KEY`)
- Any SDK/agent integrations using the old key
- `.env` files on client machines

### Step 4 — Verify new key works
```bash
curl https://api.engramia.dev/v1/health \
  -H "Authorization: Bearer $NEW_KEY"
```

### Step 5 — Revoke old key (after clients migrated)
```bash
# The rotate endpoint revokes the old key automatically.
# If you want to explicitly revoke a separate key:
curl -X DELETE \
  https://api.engramia.dev/v1/keys/${KEY_ID} \
  -H "Authorization: Bearer $ENGRAMIA_ADMIN_KEY"
```

## Rotating Env-Var Keys (env auth mode)

If `ENGRAMIA_AUTH_MODE=env`:

```bash
# Edit .env on VM
ssh root@engramia-staging 'nano /opt/engramia/.env'
# Update: ENGRAMIA_API_KEYS=newkey1,newkey2

# Restart API to pick up new keys (no downtime needed with rolling restart)
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml restart engramia-api'
```

## Emergency: Revoke All Keys

If a master key is compromised:

```bash
# 1. Immediately rotate the bootstrap/admin key
# 2. Revoke all other keys
curl https://api.engramia.dev/v1/keys \
  -H "Authorization: Bearer $NEW_ADMIN_KEY" | jq -r '.[].id' | while read id; do
    curl -X DELETE https://api.engramia.dev/v1/keys/$id \
      -H "Authorization: Bearer $NEW_ADMIN_KEY"
done

# 3. Re-issue keys with new secrets for each service
```

## Prevention
- Store keys only in secrets managers (GitHub Secrets, Vault, etc.) — never in code
- Audit key usage via `/v1/keys` listing (note `last_used_at`)
- Set up TruffleHog in CI (item 13) to catch accidental key commits

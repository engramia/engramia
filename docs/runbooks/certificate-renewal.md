# Runbook: Certificate Renewal

## Overview

TLS certificates for `api.engramia.dev` are managed by Caddy via Let's Encrypt
ACME (HTTP-01 challenge). Caddy renews certificates automatically ~30 days before
expiry. Manual intervention is rarely needed.

## Checking Certificate Status

```bash
# From local machine
echo | openssl s_client -connect api.engramia.dev:443 2>/dev/null \
  | openssl x509 -noout -dates
# Look for: notAfter=...

# On VM — check Caddy logs
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml logs caddy \
     --since 24h | grep -i "certificate\|tls\|acme\|renew"'
```

## If Auto-Renewal Fails

### Step 1 — Check Caddy container is running
```bash
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml ps caddy'
```

### Step 2 — Verify port 80 is reachable (required for HTTP-01 challenge)
```bash
curl -I http://api.engramia.dev
# Must return 200 or 301 — if blocked, Let's Encrypt challenge will fail
```

### Step 3 — Check caddy_data volume is intact
```bash
ssh root@engramia-staging \
  'docker run --rm -v engramia_caddy_data:/data alpine ls /data/caddy/certificates'
# Should list certificates directory
```

### Step 4 — Force Caddy to retry renewal
```bash
ssh root@engramia-staging '
  cd /opt/engramia
  docker compose -f docker-compose.prod.yml restart caddy
'
# Caddy will attempt renewal on startup if cert is near expiry
```

### Step 5 — Manual renewal via Caddy CLI (if above fails)
```bash
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml exec caddy \
     caddy renew --force'
```

## Caddyfile Reference

Current config at `/opt/engramia/Caddyfile`:
```
api.engramia.dev {
    reverse_proxy engramia-api:8000
}
```

Caddy handles HTTPS automatically — no manual cert config needed.

## Prevention
- Monitor certificate expiry: alert if `notAfter` < 14 days
- Ensure port 80 is open in Hetzner firewall rules
- Keep `caddy_data` volume backed up (contains ACME account + certs)
- Do not use `caddy:latest` — pin to a semver tag (already done in `docker-compose.prod.yml`)

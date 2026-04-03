# Runbook: Disk Full

## Symptoms
- API returns 500 errors or hangs
- `docker compose logs engramia-api` shows `OSError: No space left on device`
- `df -h` on the VM shows 100% usage on `/`

## Diagnostics

```bash
# Check disk usage on VM
ssh root@engramia-staging 'df -h'

# Find the largest consumers
ssh root@engramia-staging 'du -sh /var/lib/docker/volumes/* | sort -rh | head -20'

# Check Docker volume sizes specifically
ssh root@engramia-staging 'docker system df -v'

# Check PostgreSQL data volume
ssh root@engramia-staging 'du -sh /var/lib/docker/volumes/engramia_pgdata'

# Check log sizes
ssh root@engramia-staging 'journalctl --disk-usage'
```

## Resolution

### Step 1 — Free Docker overhead (safe, fast)
```bash
ssh root@engramia-staging 'docker system prune -f'
# Removes stopped containers, dangling images, unused networks
# Does NOT remove volumes
```

### Step 2 — Truncate old container logs
```bash
ssh root@engramia-staging '
  for log in $(docker inspect --format="{{.LogPath}}" $(docker ps -q)); do
    truncate -s 0 "$log"
  done
'
```

### Step 3 — Rotate journal logs
```bash
ssh root@engramia-staging 'journalctl --vacuum-size=100M'
```

### Step 4 — If pgdata is the problem
```bash
# Connect to PostgreSQL and VACUUM
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml exec pgvector \
     psql -U engramia -c "VACUUM FULL memory_data; VACUUM FULL memory_embeddings;"'

# Check table bloat before/after
ssh root@engramia-staging \
  'docker compose -f /opt/engramia/docker-compose.prod.yml exec pgvector \
     psql -U engramia -c "\dt+"'
```

### Step 5 — Emergency: remove old Docker images
```bash
# List images sorted by size
ssh root@engramia-staging 'docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" | sort -k3 -rh'

# Remove old Engramia images (keep current IMAGE_TAG)
ssh root@engramia-staging 'docker image prune -a --filter "until=72h" -f'
```

## Prevention
- Configure log rotation in `/etc/docker/daemon.json`:
  ```json
  {"log-driver": "json-file", "log-opts": {"max-size": "50m", "max-file": "3"}}
  ```
- Run `VACUUM ANALYZE` weekly via cron
- Monitor disk via Prometheus `node_filesystem_free_bytes` alert at < 20%

## Escalation
If disk is full and none of the above frees enough space, scale the Hetzner volume or upgrade to CX33.

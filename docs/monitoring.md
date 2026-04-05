# Self-Hosted Monitoring Stack for Engramia

Complete guide for deploying a zero-cost observability stack alongside Engramia
on a Hetzner VPS with Docker Compose.

**Stack:** Prometheus + Grafana + Loki + Promtail + Alertmanager + Uptime Kuma

**Cost:** $0 (all open-source, runs on the same VPS or a dedicated CX22 for ~€5/mo)

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Architecture Overview](#architecture-overview)
- [Engramia Observability Features](#engramia-observability-features)
- [docker-compose.monitoring.yml](#docker-composemonitoringyml)
- [Configuration Files](#configuration-files)
  - [Prometheus](#prometheus-configuration)
  - [Alertmanager](#alertmanager-configuration)
  - [Alert Rules](#prometheus-alert-rules)
  - [Loki](#loki-configuration)
  - [Promtail](#promtail-configuration)
  - [Grafana Provisioning](#grafana-provisioning)
- [Deployment](#deployment)
- [LLM Provider Recommendations](#llm-provider-recommendations)
- [Sizing Guide](#sizing-guide)
- [Operations](#operations)

---

## Prerequisites

- Ubuntu 22.04 VPS on Hetzner (CX22 or higher recommended)
- Docker Engine 24+ and Docker Compose v2 installed
- Engramia running via `docker-compose.prod.yml` with:
  - `ENGRAMIA_METRICS=true`
  - `ENGRAMIA_JSON_LOGS=true`
  - (Optional) `ENGRAMIA_METRICS_TOKEN` set for secured `/metrics` scraping

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Hetzner VPS (CX22 — 2 vCPU / 4 GB RAM)                   │
│                                                             │
│  ┌─── Engramia Stack (docker-compose.prod.yml) ───────────┐ │
│  │  Caddy :80/:443 ──▶ engramia-api :8000                 │ │
│  │                      │  /metrics  (Prometheus)          │ │
│  │                      │  /v1/health (health check)       │ │
│  │                      │  /v1/health/deep (deep probe)    │ │
│  │                      │  stdout → JSON logs              │ │
│  │  pgvector :5432                                         │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌─── Monitoring Stack (docker-compose.monitoring.yml) ───┐ │
│  │  Prometheus :9090  ──scrape──▶ engramia-api /metrics   │ │
│  │  Alertmanager :9093 ──email──▶ SMTP                    │ │
│  │  Loki :3100                                             │ │
│  │  Promtail ──reads──▶ Docker container logs (JSON)       │ │
│  │  Grafana :3000 ──queries──▶ Prometheus + Loki           │ │
│  │  Uptime Kuma :3001 ──pings──▶ /v1/health               │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

Both compose files share an external Docker network so Prometheus can scrape
the Engramia API container directly by service name.

---

## Engramia Observability Features

Enable these in your Engramia `.env`:

```env
# Required for /metrics endpoint
ENGRAMIA_METRICS=true
# Optional: protect /metrics with a Bearer token
ENGRAMIA_METRICS_TOKEN=prom-scrape-secret-changeme
# Structured JSON logs (required for Loki parsing)
ENGRAMIA_JSON_LOGS=true
# Optional: OpenTelemetry tracing
ENGRAMIA_TELEMETRY=false
```

### Exposed Prometheus Metrics

**Custom gauges** (from pattern store statistics):

| Metric | Type | Description |
|--------|------|-------------|
| `engramia_pattern_count` | Gauge | Total stored patterns |
| `engramia_avg_eval_score` | Gauge | Rolling average eval score (0-10) |
| `engramia_total_runs` | Gauge | Total learn() calls |
| `engramia_success_rate` | Gauge | Fraction of successful runs (0-1) |
| `engramia_reuse_rate` | Gauge | Fraction of recall() with >= 1 match |

**Request/operation metrics** (from middleware + providers):

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `engramia_request_duration_seconds` | Histogram | `method`, `path`, `status_code` | HTTP request latency |
| `engramia_requests_total` | Counter | `method`, `path`, `status_code` | Total HTTP requests |
| `engramia_llm_call_duration_seconds` | Histogram | `provider`, `model` | LLM call latency |
| `engramia_embedding_duration_seconds` | Histogram | `provider` | Embedding call latency |
| `engramia_storage_op_duration_seconds` | Histogram | `backend`, `operation` | Storage operation latency |
| `engramia_recall_hits_total` | Counter | — | Recall ops returning >= 1 result |
| `engramia_recall_misses_total` | Counter | — | Recall ops returning 0 results |
| `engramia_jobs_submitted_total` | Counter | `operation` | Async jobs submitted |
| `engramia_jobs_completed_total` | Counter | `operation`, `status` | Async jobs finished |
| `engramia_pattern_count_total` | Gauge | — | Total patterns (telemetry variant) |

### Health Endpoints

| Endpoint | Auth | Description |
|----------|------|-------------|
| `GET /v1/health` | None | Returns `{"status": "ok", "storage": "...", "pattern_count": N}` |
| `GET /v1/health/deep` | API key | Probes storage, LLM, embedding; returns latency per check |
| `GET /v1/metrics` | API key | Aggregate stats (runs, success_rate, avg_eval_score, etc.) |
| `GET /metrics` | Optional token | Prometheus exposition format |

### Structured Log Fields (JSON mode)

When `ENGRAMIA_JSON_LOGS=true`, each log line is JSON with:
`timestamp`, `level`, `message`, `logger`, `request_id`, `trace_id`,
`span_id`, `tenant_id`, `project_id`.

---

## docker-compose.monitoring.yml

Create this file in your project root alongside `docker-compose.prod.yml`.

```yaml
# docker-compose.monitoring.yml
# Deploy: docker compose -f docker-compose.monitoring.yml up -d

networks:
  engramia-net:
    external: true        # Shared with docker-compose.prod.yml
  monitoring:
    driver: bridge

services:
  # ---------- Prometheus ----------
  prometheus:
    image: prom/prometheus:v2.53.0
    container_name: prometheus
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--storage.tsdb.retention.time=90d"
      - "--storage.tsdb.retention.size=1GB"
      - "--web.enable-lifecycle"
    volumes:
      - ./monitoring/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./monitoring/prometheus/alerts.yml:/etc/prometheus/alerts.yml:ro
      - prometheus_data:/prometheus
    networks:
      - engramia-net
      - monitoring
    ports:
      - "127.0.0.1:9090:9090"
    restart: unless-stopped
    mem_limit: 256m

  # ---------- Alertmanager ----------
  alertmanager:
    image: prom/alertmanager:v0.27.0
    container_name: alertmanager
    command:
      - "--config.file=/etc/alertmanager/alertmanager.yml"
      - "--storage.path=/alertmanager"
    volumes:
      - ./monitoring/alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
      - alertmanager_data:/alertmanager
    networks:
      - monitoring
    ports:
      - "127.0.0.1:9093:9093"
    restart: unless-stopped
    mem_limit: 64m

  # ---------- Loki ----------
  loki:
    image: grafana/loki:3.1.0
    container_name: loki
    command: -config.file=/etc/loki/loki.yml
    volumes:
      - ./monitoring/loki/loki.yml:/etc/loki/loki.yml:ro
      - loki_data:/loki
    networks:
      - monitoring
    ports:
      - "127.0.0.1:3100:3100"
    restart: unless-stopped
    mem_limit: 256m

  # ---------- Promtail ----------
  promtail:
    image: grafana/promtail:3.1.0
    container_name: promtail
    command: -config.file=/etc/promtail/promtail.yml
    volumes:
      - ./monitoring/promtail/promtail.yml:/etc/promtail/promtail.yml:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - promtail_positions:/tmp
    networks:
      - monitoring
    restart: unless-stopped
    mem_limit: 64m

  # ---------- Grafana ----------
  grafana:
    image: grafana/grafana-oss:11.1.0
    container_name: grafana
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-changeme}
      GF_SERVER_ROOT_URL: ${GRAFANA_ROOT_URL:-http://localhost:3000}
      GF_SMTP_ENABLED: "true"
      GF_SMTP_HOST: ${SMTP_HOST}:${SMTP_PORT:-587}
      GF_SMTP_USER: ${SMTP_USER}
      GF_SMTP_PASSWORD: ${SMTP_PASSWORD}
      GF_SMTP_FROM_ADDRESS: ${SMTP_FROM:-monitoring@engramia.dev}
      GF_USERS_ALLOW_SIGN_UP: "false"
    volumes:
      - ./monitoring/grafana/provisioning:/etc/grafana/provisioning:ro
      - grafana_data:/var/lib/grafana
    networks:
      - monitoring
    ports:
      - "127.0.0.1:3000:3000"
    depends_on:
      - prometheus
      - loki
    restart: unless-stopped
    mem_limit: 192m

  # ---------- Uptime Kuma ----------
  uptime-kuma:
    image: louislam/uptime-kuma:1.23
    container_name: uptime-kuma
    volumes:
      - uptime_kuma_data:/app/data
    networks:
      - engramia-net
      - monitoring
    ports:
      - "127.0.0.1:3001:3001"
    restart: unless-stopped
    mem_limit: 128m

volumes:
  prometheus_data:
  alertmanager_data:
  loki_data:
  grafana_data:
  uptime_kuma_data:
  promtail_positions:
```

### Shared Network Setup

The Engramia prod compose must use a named external network so Prometheus
and Uptime Kuma can reach `engramia-api` by container name.

Add to `docker-compose.prod.yml`:

```yaml
networks:
  engramia-net:
    name: engramia-net

services:
  engramia-api:
    networks:
      - engramia-net
    # ... rest of config
  caddy:
    networks:
      - engramia-net
  pgvector:
    networks:
      - engramia-net
```

Create the network before starting:

```bash
docker network create engramia-net
```

---

## Configuration Files

### Directory Structure

```
monitoring/
├── prometheus/
│   ├── prometheus.yml
│   └── alerts.yml
├── alertmanager/
│   └── alertmanager.yml
├── loki/
│   └── loki.yml
├── promtail/
│   └── promtail.yml
└── grafana/
    └── provisioning/
        └── datasources/
            └── datasources.yml
```

Create the directory tree:

```bash
mkdir -p monitoring/{prometheus,alertmanager,loki,promtail,grafana/provisioning/datasources}
```

---

### Prometheus Configuration

`monitoring/prometheus/prometheus.yml`:

```yaml
global:
  scrape_interval: 30s       # Low traffic — no need for 15s default
  evaluation_interval: 30s
  scrape_timeout: 10s

rule_files:
  - alerts.yml

alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]

scrape_configs:
  - job_name: "engramia-api"
    metrics_path: /metrics
    scrape_interval: 30s
    # If ENGRAMIA_METRICS_TOKEN is set, uncomment:
    # authorization:
    #   type: Bearer
    #   credentials: "prom-scrape-secret-changeme"
    static_configs:
      - targets: ["engramia-api:8000"]
        labels:
          instance: "engramia-prod"

  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]
```

---

### Alertmanager Configuration

`monitoring/alertmanager/alertmanager.yml`:

```yaml
global:
  smtp_smarthost: "smtp.example.com:587"       # CHANGE: your SMTP server
  smtp_from: "monitoring@engramia.dev"          # CHANGE: sender address
  smtp_auth_username: "monitoring@engramia.dev" # CHANGE: SMTP user
  smtp_auth_password: "smtp-password-here"      # CHANGE: SMTP password
  smtp_require_tls: true

route:
  group_by: ["alertname", "severity"]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: "email-default"

  routes:
    - match:
        severity: critical
      receiver: "email-critical"
      repeat_interval: 1h

receivers:
  - name: "email-default"
    email_configs:
      - to: "ops@engramia.dev"        # CHANGE: your email
        send_resolved: true
        headers:
          Subject: '{{ template "email.default.subject" . }}'

  - name: "email-critical"
    email_configs:
      - to: "ops@engramia.dev"        # CHANGE: your email
        send_resolved: true
        headers:
          Subject: "[CRITICAL] {{ .GroupLabels.alertname }}"

inhibit_rules:
  - source_match:
      severity: "critical"
    target_match:
      severity: "warning"
    equal: ["alertname"]
```

**Free SMTP options:**

| Provider | Free Tier | Notes |
|----------|-----------|-------|
| Gmail SMTP | 500/day | Use app password, `smtp.gmail.com:587` |
| Brevo (ex-Sendinblue) | 300/day | `smtp-relay.brevo.com:587` |
| Mailgun | 100/day (sandbox) | Requires domain verification |
| Resend | 100/day | `smtp.resend.com:465` |

For a few alerts per day, any of these suffices.

---

### Prometheus Alert Rules

`monitoring/prometheus/alerts.yml`:

```yaml
groups:
  - name: engramia
    rules:
      # --- Availability ---
      - alert: EngramiaDown
        expr: up{job="engramia-api"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Engramia API is down"
          description: "Prometheus cannot scrape engramia-api for over 2 minutes."

      # --- Latency ---
      - alert: HighRequestLatency
        expr: |
          histogram_quantile(0.95,
            rate(engramia_request_duration_seconds_bucket[5m])
          ) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "p95 request latency > 5s"
          description: "95th percentile latency is {{ $value }}s over the last 5m."

      - alert: HighLLMLatency
        expr: |
          histogram_quantile(0.95,
            rate(engramia_llm_call_duration_seconds_bucket[5m])
          ) > 30
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "p95 LLM call latency > 30s"
          description: "LLM provider {{ $labels.provider }} p95 = {{ $value }}s."

      # --- Error Rate ---
      - alert: HighErrorRate
        expr: |
          (
            sum(rate(engramia_requests_total{status_code=~"5.."}[5m]))
            /
            sum(rate(engramia_requests_total[5m]))
          ) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Error rate > 10%"
          description: "{{ $value | humanizePercentage }} of requests returning 5xx."

      # --- Memory/Eval Health ---
      - alert: LowSuccessRate
        expr: engramia_success_rate < 0.5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Pattern success rate dropped below 50%"
          description: "Current success rate: {{ $value }}."

      - alert: LowEvalScore
        expr: engramia_avg_eval_score < 3
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "Average eval score below 3/10"
          description: "Rolling eval score: {{ $value }}/10."

      - alert: ZeroPatterns
        expr: engramia_pattern_count == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "No patterns stored"
          description: "Pattern count is 0 — storage may be empty or disconnected."

      # --- Recall Quality ---
      - alert: HighRecallMissRate
        expr: |
          (
            rate(engramia_recall_misses_total[1h])
            /
            (rate(engramia_recall_hits_total[1h]) + rate(engramia_recall_misses_total[1h]))
          ) > 0.8
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Recall miss rate > 80%"
          description: "Most recall queries return no matches — embedding index may be degraded."
```

---

### Loki Configuration

`monitoring/loki/loki.yml`:

```yaml
auth_enabled: false

server:
  http_listen_port: 3100

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: "2024-01-01"
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

limits_config:
  retention_period: 30d
  max_query_series: 500
  max_query_parallelism: 2

compactor:
  working_directory: /loki/compactor
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
```

---

### Promtail Configuration

`monitoring/promtail/promtail.yml`:

```yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: docker
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 10s
    relabel_configs:
      # Keep only containers from engramia stack
      - source_labels: ["__meta_docker_container_name"]
        regex: "/(engramia-api|caddy|pgvector)"
        action: keep
      - source_labels: ["__meta_docker_container_name"]
        regex: "/(.*)"
        target_label: "container"
      - source_labels: ["__meta_docker_container_label_com_docker_compose_service"]
        target_label: "service"
    pipeline_stages:
      # Parse JSON logs from engramia-api
      - match:
          selector: '{container="engramia-api"}'
          stages:
            - json:
                expressions:
                  level: level
                  request_id: request_id
                  tenant_id: tenant_id
                  project_id: project_id
                  trace_id: trace_id
                  message: message
            - labels:
                level:
                tenant_id:
            - output:
                source: message
```

---

### Grafana Provisioning

`monitoring/grafana/provisioning/datasources/datasources.yml`:

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
    jsonData:
      timeInterval: "30s"

  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    editable: false
    jsonData:
      maxLines: 1000
```

---

## Deployment

### 1. Prepare Engramia Environment

Ensure your Engramia `.env` has observability enabled:

```bash
# Add to existing .env
echo "ENGRAMIA_METRICS=true" >> .env
echo "ENGRAMIA_JSON_LOGS=true" >> .env
echo "ENGRAMIA_METRICS_TOKEN=prom-scrape-secret-changeme" >> .env
```

### 2. Create Monitoring Configs

```bash
# Clone configs from this guide
mkdir -p monitoring/{prometheus,alertmanager,loki,promtail,grafana/provisioning/datasources}

# Copy each config file above into the corresponding path
# Then edit alertmanager.yml with your SMTP credentials
```

### 3. Create Shared Network

```bash
docker network create engramia-net
```

Add the network to your `docker-compose.prod.yml` as shown in
[Shared Network Setup](#shared-network-setup).

### 4. Start Monitoring Stack

```bash
# Start monitoring
docker compose -f docker-compose.monitoring.yml up -d

# Verify all containers are healthy
docker compose -f docker-compose.monitoring.yml ps
```

### 5. Restart Engramia (to pick up .env changes + network)

```bash
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d
```

### 6. Verify Scraping

```bash
# Check Prometheus targets
curl -s http://localhost:9090/api/v1/targets | python3 -m json.tool

# Check metrics flow
curl -s http://localhost:9090/api/v1/query?query=up | python3 -m json.tool
```

### 7. Configure Uptime Kuma

Open `http://<your-vps-ip>:3001` (or tunnel via SSH) and add monitors:

| Monitor | Type | URL | Interval |
|---------|------|-----|----------|
| Engramia Health | HTTP | `http://engramia-api:8000/v1/health` | 60s |
| Engramia Deep | HTTP | `https://api.engramia.dev/v1/health/deep` | 300s |
| Prometheus | HTTP | `http://prometheus:9090/-/healthy` | 60s |
| Grafana | HTTP | `http://grafana:3000/api/health` | 60s |

Configure email notifications in Uptime Kuma settings (uses its own SMTP config).

### 8. Access Dashboards

All monitoring UIs listen on `127.0.0.1` only. Access via SSH tunnel:

```bash
# From your local machine
ssh -L 3000:127.0.0.1:3000 \
    -L 9090:127.0.0.1:9090 \
    -L 3001:127.0.0.1:3001 \
    root@your-vps-ip
```

Or expose Grafana through Caddy (add to your `Caddyfile`):

```
grafana.engramia.dev {
    reverse_proxy grafana:3000
    # Consider basic_auth or Caddy's forward_auth for protection
}
```

---

## LLM Provider Recommendations

Engramia implements two LLM providers. Both are production-ready, with
retry logic, timeout handling, and metric instrumentation.

### OpenAI (Default, Recommended)

- **LLM model:** `gpt-4.1` (configurable via `ENGRAMIA_LLM_MODEL`)
- **Embeddings:** `text-embedding-3-small` (1536 dimensions, native batch support)
- **Why recommended:**
  - Single API key covers both LLM and embeddings
  - `text-embedding-3-small` is the cheapest high-quality embedding model
  - `gpt-4.1` provides strong eval and pattern extraction at reasonable cost
  - Native batch embedding reduces API calls for bulk operations
- **Cost estimate (tens of requests/day):** ~$1-5/month

### Anthropic (Alternative)

- **LLM model:** `claude-sonnet-4-6` (configurable via `ENGRAMIA_LLM_MODEL`)
- **Embeddings:** Not provided — must pair with OpenAI or local embeddings
- **When to use:**
  - If you prefer Anthropic's style for pattern evaluation and prompt evolution
  - For Claude-based agent ecosystems where consistency matters
- **Note:** Requires two API keys (Anthropic for LLM + OpenAI for embeddings)
  unless using local embeddings

### Local Embeddings (Zero-Cost Fallback)

- Via `sentence-transformers` — no API key needed
- Suitable for development or extremely cost-sensitive deployments
- Trade-off: lower embedding quality, slower on CPU-only VPS

### Recommended Setup for Self-Hosted Production

```env
ENGRAMIA_LLM_PROVIDER=openai
ENGRAMIA_LLM_MODEL=gpt-4.1
ENGRAMIA_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_API_KEY=sk-...
```

For minimal cost, `gpt-4.1-mini` can replace `gpt-4.1` with some quality trade-off
on eval scoring and pattern extraction.

---

## Sizing Guide

### Memory Budget (Monitoring Stack Only)

| Service | Idle RAM | With `mem_limit` |
|---------|----------|------------------|
| Prometheus | 80-120 MB | 256 MB |
| Alertmanager | 15-25 MB | 64 MB |
| Loki | 60-100 MB | 256 MB |
| Promtail | 20-30 MB | 64 MB |
| Grafana | 50-80 MB | 192 MB |
| Uptime Kuma | 40-60 MB | 128 MB |
| **Total** | **~300-400 MB** | **960 MB cap** |

### Hetzner Plan Recommendations

| Plan | Specs | Price | Verdict |
|------|-------|-------|---------|
| **CX11** | 1 vCPU, 2 GB RAM, 20 GB disk | €3.79/mo | Too tight if colocated with Engramia + PostgreSQL. Viable as a dedicated monitoring-only VPS, but no headroom. |
| **CX22** | 2 vCPU, 4 GB RAM, 40 GB disk | €5.39/mo | **Recommended for dedicated monitoring VPS.** Comfortable headroom for all 6 services + 90 days of metrics retention. |
| **Colocated** | — | €0 extra | Run monitoring on the same CX22/CX23 where Engramia already runs. Works if your app VPS has >= 4 GB RAM total (CX22+). |

### Colocated vs. Separate VPS

**Colocated (same VPS as Engramia):**
- Pro: Zero additional cost
- Pro: Simpler networking (localhost)
- Con: Monitoring goes down when the app VPS goes down
- Con: Resource contention under load
- Verdict: Fine for single-digit tenants and tens of requests/day

**Separate monitoring VPS:**
- Pro: Independent observability — you see when the app VPS is down
- Pro: No resource contention
- Con: €5/mo extra
- Verdict: Worth it once you have paying customers

### Disk Usage Estimates (90 days retention)

| Data | Estimate |
|------|----------|
| Prometheus TSDB | 200-500 MB (11 metrics, 30s interval) |
| Loki chunks | 500 MB - 1 GB (depends on log volume) |
| Grafana | < 50 MB |
| Uptime Kuma SQLite | < 100 MB |
| **Total** | **~1-2 GB** |

A CX22 with 40 GB disk has ample room.

---

## Operations

### Useful Grafana Queries

**Request rate (Prometheus):**
```promql
sum(rate(engramia_requests_total[5m])) by (path)
```

**p95 latency per endpoint:**
```promql
histogram_quantile(0.95, sum(rate(engramia_request_duration_seconds_bucket[5m])) by (le, path))
```

**LLM cost proxy (calls per hour):**
```promql
sum(increase(engramia_llm_call_duration_seconds_count[1h])) by (provider, model)
```

**Error logs in Loki:**
```logql
{container="engramia-api"} | json | level="ERROR"
```

**Logs for a specific request:**
```logql
{container="engramia-api"} | json | request_id="<uuid>"
```

**Logs by tenant:**
```logql
{tenant_id="tenant-123"} | json
```

### Backup

Monitoring data is disposable — you can always re-scrape. But if you want
to preserve dashboards:

```bash
# Export Grafana dashboards
docker exec grafana grafana-cli admin export-dashboard <uid> > dashboard.json

# Or just back up the volume
docker run --rm -v grafana_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/grafana-backup.tar.gz /data
```

### Upgrading

```bash
# Pull new images
docker compose -f docker-compose.monitoring.yml pull

# Rolling restart
docker compose -f docker-compose.monitoring.yml up -d
```

### Troubleshooting

**Prometheus shows target as DOWN:**
```bash
# Verify engramia-api is reachable from prometheus container
docker exec prometheus wget -qO- http://engramia-api:8000/metrics
```

**Promtail not collecting logs:**
```bash
# Check promtail targets
curl -s http://localhost:9080/targets | head -50

# Verify Docker socket is readable
docker exec promtail ls -la /var/run/docker.sock
```

**Loki query returns nothing:**
```bash
# Check Loki readiness
curl http://localhost:3100/ready

# List label values
curl http://localhost:3100/loki/api/v1/label/container/values
```

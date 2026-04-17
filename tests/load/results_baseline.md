# Load Test — Performance Baseline

Baseline results for Engramia v0.6.0 on the reference production hardware.

## Environment

| Parameter | Value |
|-----------|-------|
| Host | Hetzner CX23 (2 vCPU AMD, 4 GB RAM) |
| OS | Ubuntu 22.04 LTS |
| Storage backend | PostgreSQL 16 + pgvector 0.7 |
| Embedding model | `text-embedding-3-small` (OpenAI) |
| LLM model | `gpt-4.1` (OpenAI) |
| Uvicorn workers | 1 process, async (single-process baseline) |
| Engramia version | v0.6.0 |
| Date | 2026-04-07 |

## Test Configuration

```
locust -f tests/load/locustfile.py \
    --host http://localhost:8000 \
    --users 20 --spawn-rate 2 --run-time 120s --headless
```

Traffic mix: 20% learn, 79% recall, 1% health (matching `ENGRAMIA_LOAD_RATIO=0.2`).

## Results

### `/v1/health` (health check — DB-less)

| Metric | Value |
|--------|-------|
| Requests | 312 |
| Failures | 0 (0%) |
| Median latency | 4 ms |
| p95 latency | 8 ms |
| p99 latency | 14 ms |
| Peak RPS | 28 req/s |

### `/v1/recall` (read path — embedding + vector search)

| Metric | Value |
|--------|-------|
| Requests | 2 341 |
| Failures | 0 (0%) |
| Median latency | 210 ms |
| p95 latency | 480 ms |
| p99 latency | 720 ms |
| Peak RPS | 21 req/s |

> **Bottleneck:** OpenAI embedding API round-trip (~140 ms median).
> With `sentence-transformers` local embeddings the median drops to ~35 ms.

### `/v1/learn` (write path — LLM evaluation + storage)

| Metric | Value |
|--------|-------|
| Requests | 591 |
| Failures | 0 (0%) |
| Median latency | 1 820 ms |
| p95 latency | 4 200 ms |
| p99 latency | 7 100 ms |
| Peak RPS | 3.2 req/s |

> **Bottleneck:** LLM eval call to `gpt-4.1` (~1 500 ms median).
> Async mode (`Prefer: respond-async`) returns immediately and processes in the background.

## SLA Targets

| Endpoint | p95 SLA | Status |
|----------|---------|--------|
| `/v1/health` | < 50 ms | ✅ (8 ms) |
| `/v1/recall` | < 1 000 ms | ✅ (480 ms) |
| `/v1/learn` (sync) | < 10 000 ms | ✅ (4 200 ms) |
| `/v1/learn` (async, job completion) | < 30 000 ms | ✅ (est. ~5 000 ms) |

## Scaling Notes

- **Single process** handles ~20 concurrent users within SLA on CX23.
- Adding a second Uvicorn worker (or replica) roughly doubles recall throughput since the embedding semaphore (`ENGRAMIA_LLM_CONCURRENCY`) is the primary bottleneck.
- The PostgreSQL connection pool (`ENGRAMIA_DB_POOL_SIZE`, default 10) is not saturated at 20 users; pool usage stays below 40%.
- For > 50 concurrent users, scale horizontally (add replicas) rather than vertically. Use an external rate limiter (Redis / API gateway) if per-key limits need to be enforced globally.

## Re-running the Baseline

```bash
# 1. Start a local stack with test data
ENGRAMIA_STORAGE=postgres \
ENGRAMIA_DATABASE_URL=postgresql://engramia:engramia@localhost:5432/engramia \
ENGRAMIA_ALLOW_NO_AUTH=true \
ENGRAMIA_AUTH_MODE=dev \
uvicorn engramia.api.app:app --host 0.0.0.0 --port 8000

# 2. Seed test patterns (optional — recall returns empty results otherwise)
python examples/postgres_backend.py

# 3. Run the load test
pip install locust
locust -f tests/load/locustfile.py \
    --host http://localhost:8000 \
    --users 20 --spawn-rate 2 --run-time 120s --headless \
    --html tests/load/results_latest.html

# 4. Open results_latest.html in a browser to compare against baseline
```

# Runbook: LLM Provider Outage

**Severity:** P2-Medium (core learn/recall unaffected)

## Impact

LLM-dependent operations fail with 503:
- `POST /v1/evaluate` — multi-evaluator scoring
- `POST /v1/compose` — pipeline decomposition
- `POST /v1/evolve` — prompt evolution

**Unaffected** (no LLM needed):
- `POST /v1/learn` / `POST /v1/recall` — pattern storage and retrieval
- `GET /v1/health` / `GET /v1/metrics` — monitoring
- `POST /v1/aging` / `POST /v1/feedback/decay` — maintenance
- All key management, governance, analytics endpoints

## Diagnostics

```bash
# Check deep health for LLM status
curl -s http://localhost:8000/v1/health/deep | jq '.checks.llm'

# Check provider status pages
# OpenAI: https://status.openai.com
# Anthropic: https://status.anthropic.com

# Check logs for LLM errors
docker compose logs engramia-api --since 10m | grep -i "llm\|openai\|anthropic" | tail -20
```

## Mitigation

### Option 1: Wait for recovery (recommended)

Built-in retry logic (3 attempts with exponential backoff) handles transient failures. Most outages resolve within 15-30 minutes.

### Option 2: Switch provider

If using OpenAI and Anthropic is available (or vice versa):

```bash
# Update .env
ENGRAMIA_LLM_PROVIDER=anthropic
ENGRAMIA_LLM_MODEL=claude-sonnet-4-6

# Restart
docker compose restart engramia-api
```

### Option 3: Disable LLM features

```bash
# Set provider to none — LLM endpoints return 501 instead of timing out
ENGRAMIA_LLM_PROVIDER=none
docker compose restart engramia-api
```

## Recovery

- LLM endpoints auto-recover when the provider returns
- No data loss during outage (patterns, embeddings, analytics unaffected)
- Async jobs that failed due to LLM outage can be retried via the jobs API

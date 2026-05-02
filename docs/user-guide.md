# Engramia User Guide

Complete guide to using Engramia — reusable execution memory and evaluation infrastructure for AI agent frameworks.

**Version:** v0.6.5 | **License:** BSL 1.1

---

## Table of Contents

1. [What is Engramia](#1-what-is-engramia)
2. [Quick Start (Cloud)](#2-quick-start-cloud)
3. [Installation (Self-hosted)](#3-installation-self-hosted)
4. [Configuration](#4-configuration)
5. [Core API — How to Use](#5-core-api--how-to-use)
6. [Billing (Cloud)](#6-billing-cloud)
7. [GDPR and Data](#7-gdpr-and-data)
8. [Limits and Rate Limiting](#8-limits-and-rate-limiting)
9. [Troubleshooting](#9-troubleshooting)
10. [Integrations and SDK](#10-integrations-and-sdk)
11. [Monitoring](#11-monitoring)

---

## 1. What is Engramia

### The Problem

AI agent frameworks (LangChain, CrewAI, AutoGPT, etc.) are stateless — every execution starts from scratch. Your agents don't learn from previous runs, don't remember what worked, and can't reuse successful solutions.

### The Solution

Engramia is a **memory layer** you add beneath any agent framework. It records successful agent runs as reusable patterns, finds them when a similar task comes up, and continuously evaluates quality.

### Who is it For

- **AI platform teams** building multi-agent pipelines
- **Agent builders** using LangChain, CrewAI, or custom frameworks
- **Automation studios** running repeated agentic workflows

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Pattern** | A stored successful agent run — contains the task description, code, quality score, and metadata. Patterns are the fundamental unit of memory. |
| **Memory** | The collection of all stored patterns for a project. The `Memory` class is the main API entry point. |
| **Project** | An isolated namespace for patterns. Each project has its own memory. A tenant can have multiple projects. |
| **Tenant** | Top-level isolation boundary (usually one per organization). |
| **Eval Run** | A multi-LLM quality evaluation of agent code. Multiple independent LLM evaluators score the code and results are aggregated. |
| **Reuse Tier** | Classification of a recall match: `duplicate` (similarity >= 0.92, use as-is), `adapt` (0.70-0.92, modify for new task), or `fresh` (< 0.70, write new code). |
| **Scope** | The combination of `tenant_id` + `project_id` that isolates data between organizations and projects. |

### Core Operations

```
Learn → Recall → Evaluate → Improve
```

1. **Learn** — record a successful agent run as a reusable pattern
2. **Recall** — semantic search to find relevant patterns for a new task
3. **Evaluate** — multi-LLM scoring with variance detection
4. **Compose** — decompose complex tasks into multi-stage pipelines *(Experimental)*
5. **Evolve** — LLM-based prompt improvement from recurring feedback *(Experimental)*

---

## 2. Quick Start (Cloud)

Use the hosted Engramia cloud at `https://api.engramia.dev`.

### Step 1: Register and Get an API Key

1. Go to `https://api.engramia.dev/docs` — this opens the Swagger UI.
2. The **Developer** tier is free, no credit card required. You get:
   - 2 projects
   - 5,000 eval runs / month
   - 10,000 patterns
   - Bring your own LLM key (OpenAI, Anthropic, Gemini, Ollama)

### Step 2: Store Your First Pattern (Learn)

```bash
curl -X POST https://api.engramia.dev/v1/learn \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Parse a CSV file and compute basic statistics",
    "code": "import csv\nimport statistics\n\ndef analyze(path):\n    with open(path) as f:\n        reader = csv.DictReader(f)\n        values = [float(row[\"value\"]) for row in reader]\n    return {\"mean\": statistics.mean(values), \"stdev\": statistics.stdev(values)}",
    "eval_score": 8.5,
    "output": "mean=42.3, stdev=7.1"
  }'
```

**Expected response:**

```json
{
  "stored": true,
  "pattern_count": 1
}
```

### Step 3: Retrieve Relevant Patterns (Recall)

```bash
curl -X POST https://api.engramia.dev/v1/recall \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Read CSV and calculate averages",
    "limit": 5
  }'
```

**Expected response:**

```json
{
  "matches": [
    {
      "similarity": 0.91,
      "reuse_tier": "adapt",
      "pattern_key": "patterns/abc123...",
      "pattern": {
        "task": "Parse a CSV file and compute basic statistics",
        "code": "import csv\nimport statistics\n...",
        "success_score": 8.5,
        "reuse_count": 0
      }
    }
  ],
  "has_more": false,
  "next_offset": null
}
```

The `reuse_tier: "adapt"` tells your agent to modify this existing solution for the new task rather than writing from scratch.

### Step 4: Verify Everything Works

```bash
curl https://api.engramia.dev/v1/health \
  -H "Authorization: Bearer YOUR_API_KEY"
```

```json
{
  "status": "ok",
  "storage": "postgres",
  "pattern_count": 1
}
```

---

## 3. Installation (Self-hosted)

### Prerequisites

- **Docker** and **Docker Compose** (recommended)
- OR **Python 3.12+** for native installation
- **PostgreSQL 15+** with **pgvector** extension (for production)
- An **OpenAI API key** or **Anthropic API key** (for evaluation and composition features)

### Option A: Docker Compose (Recommended)

#### Development Setup (JSON Storage)

For quick local experimentation without a database:

```bash
git clone https://github.com/engramia/engramia.git
cd engramia
docker compose up
```

The API is now available at `http://localhost:8000`. Swagger UI: `http://localhost:8000/docs`.

#### Production Setup (PostgreSQL + pgvector)

1. **Create an `.env` file** in the project root:

```env
# Storage
ENGRAMIA_STORAGE=postgres
ENGRAMIA_DATABASE_URL=postgresql://engramia:your-secure-password@pgvector:5432/engramia

# LLM Provider
OPENAI_API_KEY=sk-your-openai-key

# Authentication
ENGRAMIA_AUTH_MODE=db
ENGRAMIA_BOOTSTRAP_TOKEN=your-bootstrap-token-min-32-characters-long

# Security
ENGRAMIA_CORS_ORIGINS=https://your-app.com
ENGRAMIA_JSON_LOGS=true
ENGRAMIA_REDACTION=true
```

2. **Start the services:**

```bash
docker compose up -d
```

3. **Apply database migrations:**

```bash
docker compose exec engramia-api alembic upgrade head
```

4. **Create your first API key** (owner role):

```bash
curl -X POST http://localhost:8000/v1/keys/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"token": "your-bootstrap-token-min-32-characters-long"}'
```

Response:

```json
{
  "key_id": "uuid-...",
  "secret": "sk_...",
  "role": "owner"
}
```

> **Important:** Save the `secret` value — it is shown only once. Remove `ENGRAMIA_BOOTSTRAP_TOKEN` from your `.env` after use.

5. **Smoke test:**

```bash
curl http://localhost:8000/v1/health \
  -H "Authorization: Bearer sk_your-owner-key"
```

### Option B: pip Install (Native)

```bash
# Base (JSON storage, no LLM)
pip install engramia

# With OpenAI (recommended to start)
pip install "engramia[openai]"

# Full production stack
pip install "engramia[openai,api,postgres]"
```

**Available extras:**

| Extra | Contents |
|-------|----------|
| `openai` | OpenAI LLM + embeddings provider |
| `anthropic` | Anthropic/Claude LLM provider |
| `postgres` | PostgreSQL + pgvector storage backend |
| `api` | FastAPI REST server |
| `local` | sentence-transformers embeddings (no API key) |
| `langchain` | LangChain callback integration |
| `crewai` | CrewAI callback integration |
| `cli` | CLI tool (Typer + Rich) |
| `mcp` | MCP server (Claude Desktop, Cursor, Windsurf) |
| `oidc` | OIDC SSO (Okta, Azure AD, Auth0, Keycloak) |

---

## 4. Configuration

All configuration is via environment variables. No config files needed.

### Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_STORAGE` | `json` | Storage backend: `json` (dev) or `postgres` (prod). |
| `ENGRAMIA_DATA_PATH` | `./engramia_data` | Root directory for JSON storage. |
| `ENGRAMIA_DATABASE_URL` | — | PostgreSQL connection string. **Required** when `ENGRAMIA_STORAGE=postgres`. |

### LLM & Embeddings

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_LLM_PROVIDER` | `openai` | LLM backend: `openai`, `anthropic`, or `none`. |
| `ENGRAMIA_LLM_MODEL` | `gpt-4.1` | Model name passed to the LLM provider. |
| `ENGRAMIA_LLM_TIMEOUT` | `30.0` | Timeout in seconds for LLM API calls. |
| `ENGRAMIA_LLM_CONCURRENCY` | `10` | Max parallel LLM calls (bounded semaphore). |
| `ENGRAMIA_EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model name. |
| `ENGRAMIA_LOCAL_EMBEDDINGS` | — | Set to any non-empty value to use `sentence-transformers` (no API key required). |
| `OPENAI_API_KEY` | — | **Required** when using OpenAI LLM or embeddings. |
| `ANTHROPIC_API_KEY` | — | **Required** when `ENGRAMIA_LLM_PROVIDER=anthropic`. |

**LLM Provider Setup:**

- **OpenAI (default):** Set `OPENAI_API_KEY`. Supports `gpt-4.1`, `gpt-4o`, `gpt-4o-mini`, etc.
- **Anthropic:** Set `ENGRAMIA_LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`. Supports Claude models.
- **No LLM:** Set `ENGRAMIA_LLM_PROVIDER=none`. Evaluate, compose, and evolve endpoints will return HTTP 501.

**Embedding Provider Setup:**

- **OpenAI Embeddings (default):** Requires `OPENAI_API_KEY`. Uses `text-embedding-3-small`.
- **Local Embeddings:** Set `ENGRAMIA_LOCAL_EMBEDDINGS=1`. Uses `sentence-transformers` — no API key needed, runs on CPU.

### Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_AUTH_MODE` | `auto` | Auth strategy: `auto`, `env`, `db`, `dev`, `oidc`. |
| `ENGRAMIA_API_KEYS` | — | Comma-separated static API keys for `env` auth mode. |
| `ENGRAMIA_ALLOW_NO_AUTH` | — | Set to `true` for unauthenticated `dev` mode. **Never in production.** |
| `ENGRAMIA_ENVIRONMENT` | — | Deployment environment label. Blocks `dev` mode in non-local environments. |
| `ENGRAMIA_ENV_AUTH_ROLE` | `owner` | Role for requests via `env` auth mode. |
| `ENGRAMIA_BOOTSTRAP_TOKEN` | — | Token for `POST /v1/keys/bootstrap`. Min 32 characters. |

**Auth modes explained:**

| Mode | When to Use |
|------|-------------|
| `auto` | Default. Uses DB auth if `DATABASE_URL` is set, otherwise env-var keys. |
| `env` | Simple deployments with static keys (`ENGRAMIA_API_KEYS=key1,key2`). |
| `db` | Multi-tenant production with RBAC (owner/admin/editor/reader roles). |
| `dev` | Local development only. Requires explicit `ENGRAMIA_ALLOW_NO_AUTH=true`. |
| `oidc` | Enterprise SSO via JWT validation (Okta, Azure AD, Auth0, Keycloak). |

### Security & Networking

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_CORS_ORIGINS` | — | Comma-separated CORS origins. Disabled when unset. |
| `ENGRAMIA_RATE_LIMIT_DEFAULT` | `60` | Max req/min for standard endpoints (per IP). |
| `ENGRAMIA_RATE_LIMIT_EXPENSIVE` | `10` | Max req/min for LLM endpoints (per IP). |
| `ENGRAMIA_RATE_LIMIT_PER_KEY` | `120` | Max req/min per API key (all paths). |
| `ENGRAMIA_MAX_BODY_SIZE` | `1048576` | Max request body in bytes (default 1 MB). |
| `ENGRAMIA_REDACTION` | `true` | PII/secrets redaction. Only disable in dev. |
| `ENGRAMIA_MAINTENANCE` | — | Set to `true` for maintenance mode (503 on all endpoints except health). |

### Observability

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_JSON_LOGS` | `false` | Structured JSON log output. |
| `ENGRAMIA_TELEMETRY` | `false` | OpenTelemetry tracing. |
| `ENGRAMIA_METRICS` | `false` | Prometheus `/metrics` endpoint. |
| `ENGRAMIA_METRICS_TOKEN` | — | Bearer token for `/metrics` access. |
| `ENGRAMIA_OTEL_ENDPOINT` | `http://localhost:4317` | OTEL collector gRPC endpoint. |

### Billing (Cloud only)

| Variable | Default | Description |
|----------|---------|-------------|
| `STRIPE_SECRET_KEY` | — | Stripe API key. Without it, billing runs in no-op mode (all tenants get the Developer free tier). |
| `STRIPE_WEBHOOK_SECRET` | — | Stripe webhook signing secret. |
| `STRIPE_PRICE_PRO_MONTHLY` / `STRIPE_PRICE_PRO_YEARLY` | — | Stripe Price IDs for Pro tier. |
| `STRIPE_PRICE_TEAM_MONTHLY` / `STRIPE_PRICE_TEAM_YEARLY` | — | Stripe Price IDs for Team tier. |
| `STRIPE_PRICE_BUSINESS_MONTHLY` / `STRIPE_PRICE_BUSINESS_YEARLY` | — | Stripe Price IDs for Business tier. |

### Async Jobs

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_JOB_POLL_INTERVAL` | `2.0` | Worker poll interval in seconds. |
| `ENGRAMIA_JOB_MAX_CONCURRENT` | `3` | Max concurrent job executions. |

---

## 5. Core API — How to Use

All endpoints are under `/v1/`. Authentication is via `Authorization: Bearer YOUR_API_KEY` header.

**Base URL:**
- Cloud: `https://api.engramia.dev`
- Self-hosted: `http://localhost:8000`

### 5.1 Learn (Store a Pattern)

Records a successful agent run as a reusable pattern.

**`POST /v1/learn`**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task` | string | Yes | Natural language description of the task (max 10,000 chars). |
| `code` | string | Yes | Agent source code — the solution (max 500,000 chars). |
| `eval_score` | float | Yes | Quality score from 0.0 to 10.0. |
| `output` | string | No | Captured agent stdout (max 500,000 chars). |
| `run_id` | string | No | Caller-supplied run correlation ID. |
| `classification` | string | No | Data sensitivity: `public`, `internal` (default), `confidential`. |
| `source` | string | No | Pattern origin: `api` (default), `sdk`, `cli`, `import`. |

**curl example:**

```bash
curl -X POST http://localhost:8000/v1/learn \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Fetch stock price from Yahoo Finance API",
    "code": "import yfinance as yf\n\ndef get_price(ticker):\n    stock = yf.Ticker(ticker)\n    return stock.info[\"regularMarketPrice\"]",
    "eval_score": 9.0,
    "output": "AAPL: $185.50"
  }'
```

**Python example:**

```python
import requests

resp = requests.post(
    "http://localhost:8000/v1/learn",
    headers={"Authorization": f"Bearer {API_KEY}"},
    json={
        "task": "Fetch stock price from Yahoo Finance API",
        "code": "import yfinance as yf\n\ndef get_price(ticker):\n    stock = yf.Ticker(ticker)\n    return stock.info['regularMarketPrice']",
        "eval_score": 9.0,
        "output": "AAPL: $185.50",
    },
)
print(resp.json())
# {"stored": true, "pattern_count": 42}
```

**Response:**

```json
{
  "stored": true,
  "pattern_count": 42
}
```

- `stored: true` — the pattern was saved (false if it was deduplicated against an existing near-identical pattern).
- `pattern_count` — total number of patterns in the current project scope.

### 5.2 Recall (Search Patterns)

Finds stored patterns most relevant to a given task using semantic search.

**`POST /v1/recall`**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `task` | string | Yes | — | Task to find relevant patterns for. |
| `limit` | int | No | `5` | Max results (1-50). |
| `offset` | int | No | `0` | Skip N results (pagination). |
| `deduplicate` | bool | No | `true` | Group near-duplicate tasks, return only top per group. |
| `eval_weighted` | bool | No | `true` | Boost high-quality patterns in ranking. |
| `classification` | string | No | — | Filter: `public`, `internal`, `confidential`. |
| `source` | string | No | — | Filter: `api`, `sdk`, `cli`, `import`. |
| `min_score` | float | No | — | Minimum `success_score` filter (0.0-10.0). |

**curl example:**

```bash
curl -X POST http://localhost:8000/v1/recall \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Get current stock price for a given ticker symbol",
    "limit": 3,
    "min_score": 7.0
  }'
```

**Python example:**

```python
resp = requests.post(
    "http://localhost:8000/v1/recall",
    headers={"Authorization": f"Bearer {API_KEY}"},
    json={
        "task": "Get current stock price for a given ticker symbol",
        "limit": 3,
        "min_score": 7.0,
    },
)
for match in resp.json()["matches"]:
    print(f"  {match['similarity']:.2f} [{match['reuse_tier']}] {match['pattern']['task']}")
```

**Response:**

```json
{
  "matches": [
    {
      "similarity": 0.94,
      "reuse_tier": "duplicate",
      "pattern_key": "patterns/a1b2c3...",
      "pattern": {
        "task": "Fetch stock price from Yahoo Finance API",
        "code": "import yfinance as yf\n...",
        "success_score": 9.0,
        "reuse_count": 3
      }
    }
  ],
  "has_more": false,
  "next_offset": null
}
```

**How scoring works:**

- `similarity` — cosine similarity of task embeddings (0.0-1.0).
- When `eval_weighted=true`, similarity is multiplied by a quality factor [0.5, 1.0] derived from the pattern's eval history.
- `reuse_tier` classifies actionability:

| Tier | Similarity | What to Do |
|------|-----------|------------|
| `duplicate` | >= 0.92 | Use the pattern as-is. |
| `adapt` | 0.70 - 0.92 | Modify the code for your specific task. |
| `fresh` | < 0.70 | Write new code; pattern provides context only. |

**Pagination:**

```bash
# Page 1
curl -X POST .../v1/recall -d '{"task": "...", "limit": 10, "offset": 0}'
# Page 2
curl -X POST .../v1/recall -d '{"task": "...", "limit": 10, "offset": 10}'
```

Use `has_more` and `next_offset` from the response to determine if more pages exist.

### 5.3 Evaluate

Runs multi-LLM evaluation scoring on agent code. Requires an LLM provider to be configured.

**`POST /v1/evaluate`**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `task` | string | Yes | — | Task the code solves. |
| `code` | string | Yes | — | Agent source code. |
| `output` | string | No | — | Captured agent output. |
| `num_evals` | int | No | `3` | Number of independent evaluators (1-10). |

**curl example (synchronous):**

```bash
curl -X POST http://localhost:8000/v1/evaluate \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Parse CSV file and compute statistics",
    "code": "import csv\nimport statistics\n\ndef analyze(path):\n    with open(path) as f:\n        data = list(csv.DictReader(f))\n    values = [float(r[\"value\"]) for r in data]\n    return {\"mean\": statistics.mean(values)}",
    "output": "mean=42.3",
    "num_evals": 3
  }'
```

**curl example (asynchronous):**

```bash
# Submit async job
curl -X POST http://localhost:8000/v1/evaluate \
  -H "Authorization: Bearer $API_KEY" \
  -H "Prefer: respond-async" \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Parse CSV file and compute statistics",
    "code": "import csv\n...",
    "num_evals": 5
  }'
# Response: {"job_id": "abc-123", "status": "pending"}

# Poll for result
curl http://localhost:8000/v1/jobs/abc-123 \
  -H "Authorization: Bearer $API_KEY"
```

**Python example:**

```python
resp = requests.post(
    "http://localhost:8000/v1/evaluate",
    headers={"Authorization": f"Bearer {API_KEY}"},
    json={
        "task": "Parse CSV file and compute statistics",
        "code": code,
        "output": "mean=42.3",
        "num_evals": 3,
    },
)
result = resp.json()
print(f"Score: {result['median_score']}/10")
print(f"Variance: {result['variance']}")
print(f"Feedback: {result['feedback']}")
```

**Response:**

```json
{
  "median_score": 8.2,
  "variance": 0.8,
  "high_variance": false,
  "feedback": "Good implementation. Consider adding error handling for missing files.",
  "adversarial_detected": false,
  "scores": [
    {
      "task_alignment": 8.0,
      "code_quality": 8.5,
      "workspace_usage": 8.0,
      "robustness": 7.5,
      "overall": 8.0,
      "feedback": "..."
    }
  ]
}
```

- `median_score` — robust central tendency across all evaluators (0-10).
- `variance` — spread among evaluator scores. `high_variance: true` when variance > 1.5 (evaluators disagree significantly).
- `adversarial_detected` — true if hardcoded/faked output was detected.
- `scores` — individual evaluator breakdowns (task_alignment, code_quality, workspace_usage, robustness).

### 5.4 Compose (Experimental)

Decomposes a complex task into a multi-stage pipeline using stored patterns. Requires an LLM provider.

**`POST /v1/compose`**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task` | string | Yes | High-level task to decompose into a pipeline. |

**curl example:**

```bash
curl -X POST http://localhost:8000/v1/compose \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Fetch stock data, analyze trends, and generate a report"
  }'
```

**Response:**

```json
{
  "task": "Fetch stock data, analyze trends, and generate a report",
  "stages": [
    {
      "name": "fetch_data",
      "task": "Fetch stock price data from API",
      "reads": [],
      "writes": ["stock_data"],
      "reuse_tier": "duplicate",
      "similarity": 0.95,
      "code": "import yfinance as yf\n..."
    },
    {
      "name": "analyze",
      "task": "Analyze price trends",
      "reads": ["stock_data"],
      "writes": ["analysis"],
      "reuse_tier": "adapt",
      "similarity": 0.78,
      "code": "import pandas as pd\n..."
    }
  ],
  "valid": true,
  "contract_errors": []
}
```

- `valid: true` — all data-flow contracts are satisfied (reads/writes chain correctly).
- `contract_errors` — lists issues if data dependencies are broken or cycles detected.

### 5.5 Evolve (Experimental)

Generates an improved agent prompt based on recurring feedback patterns. Requires an LLM provider.

**`POST /v1/evolve`**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `role` | string | Yes | — | Agent role (e.g. `coder`, `eval`, `architect`). |
| `current_prompt` | string | Yes | — | Current system prompt to improve. |
| `num_issues` | int | No | `5` | Number of top issues to address (1-20). |

**curl example:**

```bash
curl -X POST http://localhost:8000/v1/evolve \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "role": "coder",
    "current_prompt": "You are a Python coding agent. Write clean, efficient code.",
    "num_issues": 5
  }'
```

**Response:**

```json
{
  "improved_prompt": "You are a Python coding agent. Write clean, efficient code. Always include error handling for file I/O...",
  "changes": ["Added error handling guidance", "Added input validation requirement"],
  "issues_addressed": ["Missing error handling in file operations", "No input validation"],
  "accepted": true,
  "reason": "Improvements address top recurring quality issues without over-constraining the agent."
}
```

### 5.6 Analyze Failures (Experimental)

Clusters failure patterns to identify systemic issues across your agent runs.

**`POST /v1/analyze-failures`**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `min_count` | int | No | `1` | Minimum occurrence count for a cluster to be included. |

**curl example:**

```bash
curl -X POST http://localhost:8000/v1/analyze-failures \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"min_count": 2}'
```

**Response:**

```json
{
  "clusters": [
    {
      "representative": "FileNotFoundError when reading input CSV",
      "members": ["FileNotFoundError: data.csv", "FileNotFoundError: input.csv"],
      "total_count": 5,
      "avg_score": 2.1
    }
  ]
}
```

### 5.7 Projects

Projects provide namespace isolation for patterns within a tenant. Each project has its own independent memory.

**How projects work:**
- Project scope is set via the API key's associated `project_id` (in DB auth mode) or via the `X-Project-Id` header.
- All operations (learn, recall, evaluate, etc.) are automatically scoped to the current project.
- Default project is `"default"` when no project is specified.

**Managing projects:**
- Create additional projects by issuing API keys with different `project_id` values via `POST /v1/keys`.
- Delete all data for a project: `DELETE /v1/governance/projects/{project_id}`.

### 5.8 Other Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/health` | GET | Basic health check — returns status, storage type, pattern count. |
| `/v1/health/deep` | GET | Deep health — probes storage, LLM, and embedding connectivity with latencies. |
| `/v1/metrics` | GET | Aggregate statistics: runs, success_rate, avg_eval_score, pattern_count, reuse_rate. |
| `/v1/feedback` | GET | Top recurring quality issues. Supports `?task_type=csv&limit=5&offset=0`. |
| `/v1/export` | GET | Export all patterns as JSON (for backup). |
| `/v1/import` | POST | Bulk-import patterns from an export. |
| `/v1/aging` | POST | Apply time-decay to patterns, prune stale ones below threshold. |
| `/v1/feedback/decay` | POST | Apply time-decay to feedback patterns. |
| `/v1/patterns/{key}` | DELETE | Permanently delete a stored pattern. |
| `/v1/skills/register` | POST | Tag a pattern with skill capabilities (e.g. `["csv_parsing"]`). |
| `/v1/skills/search` | POST | Find patterns by skill tags. |
| `/v1/version` | GET | Build metadata (no auth required). |

**Async job support:** The following endpoints accept the `Prefer: respond-async` header to run as background jobs: `/evaluate`, `/compose`, `/evolve`, `/aging`, `/feedback/decay`, `/import`. They return `202 Accepted` with a `job_id`:

```bash
# Submit
curl -X POST http://localhost:8000/v1/evaluate \
  -H "Prefer: respond-async" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"task": "...", "code": "...", "num_evals": 5}'

# Poll
curl http://localhost:8000/v1/jobs/{job_id} \
  -H "Authorization: Bearer $API_KEY"

# List all jobs
curl http://localhost:8000/v1/jobs \
  -H "Authorization: Bearer $API_KEY"

# Cancel a pending job
curl -X POST http://localhost:8000/v1/jobs/{job_id}/cancel \
  -H "Authorization: Bearer $API_KEY"
```

---

## 6. Billing (Cloud)

The Engramia cloud service uses Stripe-based billing with four plan tiers.

### Plan Tiers

| Feature | Developer | Pro | Team | Business | Enterprise |
|---------|-----------|-----|------|----------|------------|
| **Price** | $0/mo | $19/mo ($14/mo yearly) | $59/mo ($44/mo yearly) | $199/mo ($149/mo yearly) | Custom |
| **Projects** | 2 | 10 | 50 | 250 | Unlimited |
| **Eval Runs/mo** | 5,000 | 50,000 | 250,000 | 1,000,000 | Custom |
| **Patterns** | 10,000 | 100,000 | 1,000,000 | 10,000,000 | Unlimited |
| **Users** | 1 | 1 | 10 | 50 | Unlimited |
| **Overage** | — | +$5 / 5,000 runs (opt-in) | +$25 / 50,000 runs + cap | +$100 / 250,000 runs + cap | Pre-paid |
| **Async Jobs** | — | — | Yes (3 concurrent) | Yes (10 concurrent) | Yes |
| **Hosted MCP server** | — | — | Yes | Yes | Yes |
| **RBAC + audit log** | — | — | Yes | Yes | Yes |
| **SSO / OIDC** | — | — | — | Yes | Yes |
| **Cross-agent memory + role routing** | — | — | — | Yes | Yes |

Yearly billing saves 25 % on every paid tier.

### Developer

The Developer tier is the default for all new tenants (replaces the legacy "sandbox" tier name). No credit card required. Limits:
- 2 projects, 5,000 eval runs/month, 10,000 patterns.
- BYOK across OpenAI, Anthropic, Gemini, Ollama; local sentence-transformer embeddings included.
- When you hit the limit, the API returns HTTP 429 with a `reset_date` indicating when the quota resets (first day of next month).

### Upgrading to Pro, Team, or Business

```bash
# Create a Stripe Checkout session
curl -X POST https://api.engramia.dev/v1/billing/checkout \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "price_id": "price_...",
    "success_url": "https://your-app.com/billing/success",
    "cancel_url": "https://your-app.com/billing/cancel"
  }'
# Response: {"checkout_url": "https://checkout.stripe.com/..."}
```

Redirect the user to the `checkout_url`. After successful payment, Stripe sends a webhook and your plan is upgraded automatically.

### Checking Your Current Plan and Usage

```bash
curl https://api.engramia.dev/v1/billing/status \
  -H "Authorization: Bearer $API_KEY"
```

```json
{
  "plan_tier": "pro",
  "status": "active",
  "billing_interval": "month",
  "eval_runs_used": 12500,
  "eval_runs_limit": 50000,
  "patterns_used": 24000,
  "patterns_limit": 100000,
  "projects_used": 4,
  "projects_limit": 10,
  "period_end": "2026-06-01T00:00:00Z",
  "overage_enabled": false,
  "overage_budget_cap_cents": null
}
```

### Overage Charges

When your eval run quota is exhausted, you can opt in to overage billing instead of being blocked:

```bash
# Enable overage with a $50 budget cap
curl -X PATCH https://api.engramia.dev/v1/billing/overage \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "budget_cap_cents": 5000}'
```

- **Pro:** $5 per 5,000 additional eval runs.
- **Team:** $25 per 50,000 additional eval runs, with an optional budget cap.
- **Business:** $100 per 250,000 additional eval runs, with an optional budget cap.
- When the budget cap is reached, API returns HTTP 429 (`overage_budget_cap_reached`).
- Set `budget_cap_cents` to `null` to remove the cap (Team and Business only).

### Customer Portal

Manage your subscription, update payment methods, and view invoices:

```bash
curl https://api.engramia.dev/v1/billing/portal?return_url=https://your-app.com \
  -H "Authorization: Bearer $API_KEY"
# Response: {"portal_url": "https://billing.stripe.com/..."}
```

### Grace Period

If a payment fails:
1. Your subscription enters `past_due` status.
2. You have a **7-day grace period** — API continues to work normally.
3. From day 5, warning logs are emitted.
4. After 7 days without payment, API returns **HTTP 402 Payment Required**.
5. After all Stripe retry attempts (day 3, 5, 7, 14), the subscription is canceled and you are downgraded to the Developer free tier.

---

## 7. GDPR and Data

Engramia provides data governance features for GDPR compliance.

### Exporting Your Data (GDPR Art. 20 — Data Portability)

**Quick export (JSON):**

```bash
curl http://localhost:8000/v1/export \
  -H "Authorization: Bearer $API_KEY" \
  -o backup.json
```

**Governance export (NDJSON, streaming):**

```bash
curl http://localhost:8000/v1/governance/export \
  -H "Authorization: Bearer $API_KEY" \
  -o export.ndjson
```

### Deleting a Project (GDPR Art. 17 — Right to Erasure)

Permanently deletes all patterns, jobs, and API keys for a specific project:

```bash
curl -X DELETE http://localhost:8000/v1/governance/projects/{project_id} \
  -H "Authorization: Bearer $API_KEY"
```

**Response:**

```json
{
  "tenant_id": "your-tenant",
  "project_id": "the-project",
  "patterns_deleted": 150,
  "jobs_deleted": 3,
  "keys_revoked": 2,
  "projects_deleted": 1
}
```

### Deleting a Tenant

Permanently deletes ALL data across all projects for a tenant:

```bash
curl -X DELETE http://localhost:8000/v1/governance/tenants/{tenant_id} \
  -H "Authorization: Bearer $API_KEY"
```

### Self-service Account Deletion (cloud users only)

If you signed up via the cloud dashboard, you can delete your account end-to-end without contacting support. This is the GDPR Art. 17 right-to-erasure flow surfaced as a two-step double-opt-in:

1. In the dashboard, open **Settings → Account** and click **Delete account**. The dashboard calls `POST /auth/me/deletion-request` which generates a 24-hour confirmation token and emails the link to your verified address.
2. Open the email and click the link. The dashboard then calls `DELETE /auth/me?token=...`, which:
   - Cancels your active Stripe subscription (no refund for the unused period)
   - Cascades deletion of all patterns, embeddings, jobs, and API keys for your tenant
   - Anonymises your `cloud_users` row (email is rewritten to `deleted-<uuid>@deleted.engramia.dev`; password and name are nulled)
   - Final hard-delete happens after a 30-day grace window via the `engramia cleanup deleted-accounts` cron job

Idempotent: clicking the link a second time returns `410 Gone`. If you start the flow twice within 24 hours, the second `POST /auth/me/deletion-request` is rejected with `409 deletion_already_pending`.

Use `GET /v1/export` (Art. 20 portability) before triggering deletion if you want a backup of your patterns.

### Retention Policy

Configure automatic data expiration:

```bash
# View current retention policy
curl http://localhost:8000/v1/governance/retention \
  -H "Authorization: Bearer $API_KEY"

# Set 90-day retention (patterns older than 90 days are auto-purged)
curl -X PUT http://localhost:8000/v1/governance/retention \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"retention_days": 90}'

# Manually trigger retention cleanup (dry run first)
curl -X POST http://localhost:8000/v1/governance/retention/apply \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'
# Response: {"purged_count": 23, "dry_run": true}

# Actually purge
curl -X POST http://localhost:8000/v1/governance/retention/apply \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": false}'
```

### Data Classification

Classify individual patterns for sensitivity:

```bash
curl -X PUT http://localhost:8000/v1/governance/patterns/{pattern_key}/classify \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"classification": "confidential"}'
```

Classifications: `public`, `internal`, `confidential`.

### PII Redaction

Engramia automatically redacts PII and secrets from stored patterns by default (`ENGRAMIA_REDACTION=true`). This includes:
- API keys and tokens
- Email addresses
- Common secret patterns

Disable only in development environments: `ENGRAMIA_REDACTION=false`.

---

## 8. Limits and Rate Limiting

### Plan Limits

| Resource | Developer | Pro | Team | Business | Enterprise |
|----------|-----------|-----|------|----------|------------|
| Projects | 2 | 10 | 50 | 250 | Unlimited |
| Eval Runs / month | 5,000 | 50,000 | 250,000 | 1,000,000 | Custom |
| Stored Patterns | 10,000 | 100,000 | 1,000,000 | 10,000,000 | Unlimited |
| Overage | No | $5/5K runs | $25/50K runs + cap | $100/250K runs + cap | Pre-paid |

### Rate Limits

| Endpoint Type | Per-IP Limit | Per-Key Limit |
|---------------|-------------|---------------|
| Standard endpoints (`/learn`, `/recall`, `/feedback`, etc.) | 60 req/min | 120 req/min (all paths combined) |
| LLM-intensive endpoints (`/evaluate`, `/compose`, `/evolve`) | 10 req/min | 120 req/min (all paths combined) |

### Rate Limit Headers

When rate limited, the API returns:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 60
Content-Type: application/json

{"detail": "Rate limit exceeded. Max 60 requests per minute."}
```

The `Retry-After: 60` header indicates how many seconds to wait before retrying.

### Request Size Limit

Maximum request body size is **1 MB** by default (configurable via `ENGRAMIA_MAX_BODY_SIZE`). Exceeding this returns:

```
HTTP/1.1 413 Request Entity Too Large
{"detail": "Request body too large. Maximum allowed: 1048576 bytes."}
```

### What to Do When You Hit a Limit

| Error | Cause | Solution |
|-------|-------|----------|
| HTTP 429 `quota_exceeded` (eval_runs) | Monthly eval run quota exhausted. | Wait for `reset_date` (next month), enable overage, or upgrade your plan. |
| HTTP 429 `quota_exceeded` (patterns) | Pattern storage quota reached. | Delete old patterns (`DELETE /v1/patterns/{key}`), run aging (`POST /v1/aging`), or upgrade. |
| HTTP 429 `overage_budget_cap_reached` | Overage budget cap hit. | Increase your budget cap (`PATCH /v1/billing/overage`) or wait for next period. |
| HTTP 429 (rate limit) | Too many requests per minute. | Implement exponential backoff. Respect `Retry-After` header. |
| HTTP 413 | Request body too large. | Reduce payload size. Trim code/output fields. |

---

## 9. Troubleshooting

### Common Errors

#### HTTP 401 Unauthorized

```json
{"detail": "Invalid or missing API key."}
```

**Causes and fixes:**
- Missing `Authorization` header — add `Authorization: Bearer YOUR_KEY`.
- Invalid API key — verify the key is correct and has not been revoked.
- Key expired or rotated — get a new key from your admin (`POST /v1/keys/{id}/rotate`).

#### HTTP 402 Payment Required

```json
{"error": "payment_required", "message": "Your subscription payment is past due. Update your payment method to continue."}
```

**Fix:** Your payment has failed and the 7-day grace period has expired. Update your payment method via the Customer Portal (`GET /v1/billing/portal`) or contact your billing admin.

#### HTTP 429 Too Many Requests

```json
{"error": "quota_exceeded", "metric": "eval_runs", "current": 500, "limit": 500, "reset_date": "2026-05-01"}
```

**Fix:** See [What to Do When You Hit a Limit](#what-to-do-when-you-hit-a-limit) above. If the error has `"detail": "Rate limit exceeded..."`, implement backoff and retry after the `Retry-After` header value.

#### HTTP 413 Request Entity Too Large

```json
{"detail": "Request body too large. Maximum allowed: 1048576 bytes."}
```

**Fix:** Reduce the size of `code` or `output` fields. If you need larger payloads, set `ENGRAMIA_MAX_BODY_SIZE` to a higher value (self-hosted only).

#### HTTP 501 Not Implemented

```json
{"detail": "LLM provider not configured. evaluate() requires an LLM."}
```

**Fix:** The endpoint requires an LLM provider. Set `ENGRAMIA_LLM_PROVIDER=openai` and `OPENAI_API_KEY`, or use `anthropic` with `ANTHROPIC_API_KEY`.

#### HTTP 503 Service Unavailable

```json
{"detail": "Service is under scheduled maintenance. Please try again later."}
```

**Fix:** The server is in maintenance mode (`ENGRAMIA_MAINTENANCE=true`). Wait for the operator to complete maintenance. `/v1/health` remains available.

### Health Checks

**Basic health:**

```bash
curl http://localhost:8000/v1/health \
  -H "Authorization: Bearer $API_KEY"
```

**Deep health** (probes storage, LLM, and embedding connectivity):

```bash
curl http://localhost:8000/v1/health/deep \
  -H "Authorization: Bearer $API_KEY"
```

```json
{
  "status": "ok",
  "version": "0.6.5",
  "uptime_seconds": 3600.5,
  "checks": {
    "storage": {"status": "ok", "latency_ms": 2.1},
    "llm": {"status": "ok", "latency_ms": 450.3},
    "embedding": {"status": "ok", "latency_ms": 120.7}
  }
}
```

- `status: "ok"` — all systems operational.
- `status: "degraded"` — some systems have issues but core functionality works.
- `status: "error"` (HTTP 503) — critical systems unavailable.

### Viewing Logs

**Docker:**

```bash
docker compose logs -f engramia-api
```

Enable structured JSON logs for production:

```env
ENGRAMIA_JSON_LOGS=true
```

**Key log entries to watch:**
- `AUDIT` events — auth failures, rate limits, deletions.
- `DUNNING_EVENT` — payment-related warnings.
- `WARNING` / `ERROR` level — operational issues.

---

## 10. Integrations and SDK

### Python SDK Client (Zero Dependencies)

Engramia includes a lightweight HTTP client using only Python's standard library:

```python
from engramia.sdk.webhook import EngramiaWebhook

client = EngramiaWebhook(
    url="http://localhost:8000",
    api_key="sk_your-api-key",
)

# Store a pattern
client.learn(
    task="Parse CSV and compute statistics",
    code="import csv\n...",
    eval_score=8.5,
    output="mean=42.3",
)

# Find relevant patterns
matches = client.recall(task="Read CSV and calculate averages", limit=5)
for m in matches:
    print(f"{m['similarity']:.2f} [{m['reuse_tier']}] {m['pattern']['task']}")

# Run evaluation
result = client.evaluate(
    task="Parse CSV file",
    code="import csv\n...",
    num_evals=3,
)
print(f"Score: {result['median_score']}/10")

# Compose a pipeline
pipeline = client.compose(task="Fetch data, analyze, report")

# Get feedback
feedback = client.feedback(task_type="csv", limit=5)

# Get metrics
metrics = client.metrics()

# Health check
health = client.health()

# Delete a pattern
client.delete_pattern("patterns/abc123")

# Run maintenance
pruned = client.run_aging()
pruned = client.run_feedback_decay()

# Evolve a prompt
result = client.evolve_prompt(
    role="coder",
    current_prompt="You are a Python coder.",
    num_issues=5,
)

# Analyze failures
clusters = client.analyze_failures(min_count=2)

# Register and search by skills
client.register_skills("patterns/abc123", ["csv_parsing", "statistics"])
matches = client.find_by_skills(["csv_parsing"], match_all=True)
```

### Using the Python Library Directly

For self-hosted deployments, use the `Memory` class directly (no HTTP overhead):

```python
from engramia import Memory
from engramia.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage

mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)

# Learn
result = mem.learn(
    task="Parse CSV and compute statistics",
    code="import csv\nimport statistics\n...",
    eval_score=8.5,
    output="mean=42.3, stdev=7.1",
)

# Recall
matches = mem.recall(task="Read CSV and calculate averages", limit=5)
for m in matches:
    print(f"{m.similarity:.2f} [{m.reuse_tier}] {m.pattern.task}")

# Evaluate
result = mem.evaluate(task="Parse CSV", code="import csv\n...", num_evals=3)
print(f"Score: {result.median_score}/10, Variance: {result.variance}")

# Compose
pipeline = mem.compose(task="Fetch data, analyze, generate report")
for stage in pipeline.stages:
    print(f"  {stage.name}: {stage.task} [{stage.reuse_tier}]")

# Export / Import
records = mem.export()
mem.import_data(records, overwrite=False)
```

### Using with PostgreSQL

```python
from engramia import Memory
from engramia.providers import OpenAIProvider, OpenAIEmbeddings, PostgresStorage

storage = PostgresStorage(
    database_url="postgresql://user:pass@localhost:5432/engramia"
)
mem = Memory(
    llm=OpenAIProvider(),
    embeddings=OpenAIEmbeddings(),
    storage=storage,
)
```

### LangChain Integration

```python
pip install "engramia[langchain]"
```

```python
from engramia import Memory
from engramia.sdk.langchain import EngramiaCallback

mem = Memory(llm=..., embeddings=..., storage=...)
callback = EngramiaCallback(memory=mem)

# Use with any LangChain chain
chain.invoke({"input": "..."}, config={"callbacks": [callback]})
# Engramia automatically learns on chain completion
# and recalls relevant patterns before chain start.
```

### CrewAI Integration

```python
pip install "engramia[crewai]"
```

```python
from engramia import Memory
from engramia.sdk.crewai import EngramiaCrewCallback

mem = Memory(llm=..., embeddings=..., storage=...)
callback = EngramiaCrewCallback(memory=mem)

# Use with CrewAI
crew = Crew(agents=[...], tasks=[...], callbacks=[callback])
crew.kickoff()
# Engramia automatically learns and recalls during crew execution.
```

### Using `requests` or `httpx` Directly

If you prefer a standard HTTP client:

```python
import requests

BASE_URL = "http://localhost:8000"
HEADERS = {
    "Authorization": "Bearer sk_your-api-key",
    "Content-Type": "application/json",
}

# Learn
resp = requests.post(f"{BASE_URL}/v1/learn", headers=HEADERS, json={
    "task": "Parse CSV",
    "code": "import csv\n...",
    "eval_score": 8.5,
})
print(resp.json())

# Recall
resp = requests.post(f"{BASE_URL}/v1/recall", headers=HEADERS, json={
    "task": "Read CSV",
    "limit": 5,
})
for m in resp.json()["matches"]:
    print(f"  {m['similarity']:.2f} {m['pattern']['task']}")

# Health
resp = requests.get(f"{BASE_URL}/v1/health/deep", headers=HEADERS)
print(resp.json()["status"])
```

---

## 11. Monitoring

Engramia ships with a complete monitoring stack based on Prometheus, Grafana, Loki, and Uptime Kuma. All services are defined in `docker-compose.monitoring.yml`. An operator management wrapper (`monitoring.sh`) is maintained in the private [engramia-ops](https://github.com/engramia/engramia-ops) repository; self-hosters can invoke `docker compose -f docker-compose.monitoring.yml ...` directly as shown below.

### Architecture

```
┌─────────────────────────────────────────────────┐
│  engramia-net (shared with prod stack)          │
│    engramia-api:8000/metrics ← Prometheus       │
│    uptime-kuma (health checks)                  │
└─────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────┐
│  monitoring (internal bridge network)           │
│    Prometheus → Alertmanager → email            │
│    Promtail → Loki                              │
│    Grafana (queries Prometheus + Loki)           │
└─────────────────────────────────────────────────┘
```

| Service | Port | Purpose |
|---------|------|---------|
| **Grafana** | `localhost:3000` | Dashboards and visualization |
| **Prometheus** | `localhost:9090` | Metrics collection and alerting rules |
| **Alertmanager** | `localhost:9093` | Alert routing and email notifications |
| **Loki** | `localhost:3100` | Log aggregation |
| **Promtail** | — (internal) | Collects Docker container logs and pushes to Loki |
| **Uptime Kuma** | `localhost:3001` | Uptime monitoring with status pages |

All ports are bound to `127.0.0.1` only (not publicly accessible). Use SSH tunnel or a reverse proxy for remote access.

### 11.1 Starting the Monitoring Stack

**Prerequisites:** The production stack (`docker-compose.prod.yml`) must be running first, because the monitoring services connect to the shared `engramia-net` Docker network.

**Using Docker Compose directly:**

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.monitoring.yml up -d
```

After starting, the script prints the access URLs:

```
Grafana:      http://localhost:3000
Prometheus:   http://localhost:9090
Alertmanager: http://localhost:9093
Uptime Kuma:  http://localhost:3001
```

### 11.2 Grafana

#### Accessing Grafana

Open `http://localhost:3000` in your browser.

**Default credentials:**

| Field | Value |
|-------|-------|
| Username | `admin` |
| Password | value of `GRAFANA_ADMIN_PASSWORD` env var (default: `changeme`) |

Change the password immediately after first login.

#### Pre-provisioned Dashboard

Grafana comes with the **Engramia Overview** dashboard pre-loaded (folder: "Engramia"). It includes:

**Overview panels:**
- API Status (UP/DOWN)
- Pattern Count
- Average Eval Score (0-10, color-coded: red < 3, orange 3-5, green > 6)
- Success Rate (color-coded: red < 30%, orange 30-50%, green > 60%)
- Reuse Rate
- Total Runs

**HTTP Traffic panels:**
- Request Rate (total, 2xx, 4xx, 5xx breakdown)
- Error Rate (5xx / total percentage)

**Latency panels:**
- HTTP Request Latency (p50 / p90 / p99)
- LLM Call Latency (p50 / p90 / p99)

**Engramia Core panels:**
- Pattern Count over time
- Eval Score trend
- Recall Hits vs Misses (stacked)

**Infrastructure panels:**
- Storage Operation Latency (p90, per operation)
- Embedding Latency (p90, per provider)
- Async Jobs (submitted vs completed, by operation)
- Request Rate by Endpoint

The dashboard auto-refreshes every 30 seconds and shows the last 6 hours by default.

#### Data Sources

Two data sources are pre-configured (read-only):

| Name | Type | URL | UID |
|------|------|-----|-----|
| Prometheus | prometheus | `http://prometheus:9090` | `engramia-prometheus` |
| Loki | loki | `http://loki:3100` | `engramia-loki` |

#### Environment Variables for Grafana

Set these in your `.env` file:

```env
GRAFANA_ADMIN_PASSWORD=your-secure-password
GRAFANA_ROOT_URL=http://localhost:3000    # or your public URL
```

### 11.3 Email Alerts (SMTP Configuration)

Alert emails are sent by **Alertmanager** (for Prometheus alert rules) and optionally by **Grafana** (for dashboard-based alerts). Both need SMTP configuration.

#### Grafana SMTP

Set these environment variables in `.env`:

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=monitoring@engramia.dev
SMTP_PASSWORD=your-smtp-password
SMTP_FROM=monitoring@engramia.dev
```

Grafana reads these at startup via its `GF_SMTP_*` environment variables (mapped in `docker-compose.monitoring.yml`).

#### Alertmanager SMTP

Edit `monitoring/alertmanager.yml` and replace the placeholder values:

```yaml
global:
  smtp_smarthost: "smtp.example.com:587"       # ← your SMTP server
  smtp_from: "monitoring@engramia.dev"          # ← your sender address
  smtp_auth_username: "monitoring@engramia.dev" # ← your SMTP user
  smtp_auth_password: "smtp-password-here"      # ← your SMTP password
  smtp_require_tls: true

receivers:
  - name: "email-default"
    email_configs:
      - to: "ops@engramia.dev"                  # ← your ops email
        send_resolved: true

  - name: "email-critical"
    email_configs:
      - to: "ops@engramia.dev"                  # ← your ops email
        send_resolved: true
```

#### Free SMTP Providers

| Provider | Free Tier | SMTP Host |
|----------|-----------|-----------|
| Gmail | 500/day | `smtp.gmail.com:587` |
| Brevo | 300/day | `smtp-relay.brevo.com:587` |
| Mailgun | 100/day (sandbox) | requires domain verification |
| Resend | 100/day | `smtp.resend.com:465` |

#### Pre-configured Alert Rules

Prometheus evaluates these rules every 30 seconds. Alertmanager routes them to email:

**Critical alerts** (resent every 1 hour until resolved):

| Alert | Condition | Fires After |
|-------|-----------|-------------|
| EngramiaDown | API unreachable (`up == 0`) | 2 min |
| HighErrorRate | 5xx error rate > 10% | 5 min |
| ZeroPatterns | Pattern storage is empty | 5 min |

**Warning alerts** (resent every 4 hours):

| Alert | Condition | Fires After |
|-------|-----------|-------------|
| HighRequestLatency | p95 HTTP latency > 5s | 5 min |
| HighLLMLatency | p95 LLM call latency > 30s | 5 min |
| LowSuccessRate | Success rate < 50% | 10 min |
| LowEvalScore | Average eval score < 3/10 | 30 min |
| HighRecallMissRate | Recall miss rate > 80% | 1 hour |

Alert routing: critical alerts suppress matching warnings automatically (inhibit rules).

### 11.4 Logs with Loki

Loki aggregates container logs collected by Promtail. Logs are retained for **30 days**.

#### Which Containers Are Collected

Promtail is configured to collect logs only from these containers:
- `engramia-api` — application logs (JSON-parsed when `ENGRAMIA_JSON_LOGS=true`)
- `caddy` — reverse proxy access logs
- `pgvector` — PostgreSQL logs

#### Viewing Logs in Grafana

1. Open Grafana (`http://localhost:3000`).
2. Go to **Explore** (compass icon in the left sidebar).
3. Select **Loki** as the data source (top dropdown).
4. Use LogQL queries:

```logql
# All Engramia API logs
{container="engramia-api"}

# Only errors
{container="engramia-api"} |= "ERROR"

# Filter by log level (when JSON logs enabled)
{container="engramia-api"} | json | level="ERROR"

# Filter by tenant
{container="engramia-api"} | json | tenant_id="your-tenant"

# PostgreSQL logs
{container="pgvector"}

# Caddy access logs
{container="caddy"}

# Rate of error logs over time
rate({container="engramia-api"} |= "ERROR" [5m])
```

#### JSON Log Fields

When `ENGRAMIA_JSON_LOGS=true` is set, Promtail parses these fields from Engramia logs:

| Field | Label | Description |
|-------|-------|-------------|
| `level` | Yes | Log level (INFO, WARNING, ERROR) |
| `tenant_id` | Yes | Tenant ID for multi-tenant filtering |
| `request_id` | No | Request correlation ID |
| `project_id` | No | Project ID |
| `trace_id` | No | OpenTelemetry trace ID |
| `message` | No | Log message body |

Fields marked "Yes" under Label are indexed and can be used in `{label="value"}` selectors. Other fields are extracted with `| json` and filtered with `| field="value"`.

### 11.5 Uptime Kuma

Uptime Kuma provides external uptime monitoring with a status page and notifications.

#### Accessing Uptime Kuma

Open `http://localhost:3001` in your browser. On first launch, you will create an admin account through the setup wizard.

#### Recommended Monitors

After setup, add these HTTP monitors:

| Name | URL | Interval | Method |
|------|-----|----------|--------|
| Engramia Health | `http://engramia-api:8000/v1/health` | 60s | GET |
| Engramia Deep Health | `https://api.engramia.dev/v1/health/deep` | 300s | GET |
| Prometheus | `http://prometheus:9090/-/healthy` | 60s | GET |
| Grafana | `http://grafana:3000/api/health` | 60s | GET |

Use internal Docker hostnames (e.g. `engramia-api`, `prometheus`) for monitors within the Docker network. Use the public URL for external checks.

#### Notifications

Uptime Kuma supports 90+ notification providers. Configure via the web UI:
- **Settings** > **Notifications** > **Setup Notification**
- Common choices: Email (SMTP), Slack webhook, Telegram bot, Discord webhook, PagerDuty

#### Status Page

Create a public status page at **Status Pages** > **+ New Status Page**. Add your monitors to display uptime for your users.

### 11.6 Prometheus Metrics Exposed by Engramia

The Engramia API exposes a Prometheus-compatible `/metrics` endpoint (opt-in via `ENGRAMIA_METRICS=true`).

**Enable metrics in `.env`:**

```env
ENGRAMIA_METRICS=true
ENGRAMIA_METRICS_TOKEN=your-metrics-bearer-token   # protects the endpoint
```

**Available metrics:**

| Metric | Type | Description |
|--------|------|-------------|
| `engramia_pattern_count` | Gauge | Total stored patterns |
| `engramia_avg_eval_score` | Gauge | Rolling average eval score (0-10) |
| `engramia_total_runs` | Gauge | Total learn() calls |
| `engramia_success_rate` | Gauge | Fraction of successful runs (0-1) |
| `engramia_reuse_rate` | Gauge | Fraction of recall() with matches |
| `engramia_requests_total` | Counter | HTTP requests (labels: method, path, status_code) |
| `engramia_request_duration_seconds` | Histogram | HTTP request latency (labels: method, path, status_code) |
| `engramia_llm_call_duration_seconds` | Histogram | LLM call latency (labels: provider, model) |
| `engramia_embedding_duration_seconds` | Histogram | Embedding latency (labels: provider) |
| `engramia_storage_op_duration_seconds` | Histogram | Storage op latency (labels: backend, operation) |
| `engramia_recall_hits_total` | Counter | Recall operations with results |
| `engramia_recall_misses_total` | Counter | Recall operations without results |
| `engramia_jobs_submitted_total` | Counter | Async jobs submitted (labels: operation) |
| `engramia_jobs_completed_total` | Counter | Async jobs finished (labels: operation, status) |

If you set `ENGRAMIA_METRICS_TOKEN`, Prometheus must be configured with a bearer token to scrape. In `monitoring/prometheus.yml`, uncomment the authorization section:

```yaml
scrape_configs:
  - job_name: engramia-api
    authorization:
      credentials: "prom-scrape-secret-changeme"  # must match ENGRAMIA_METRICS_TOKEN
    static_configs:
      - targets: ["engramia-api:8000"]
```

### 11.7 Data Retention

| Component | Retention | Configurable In |
|-----------|-----------|-----------------|
| Prometheus | 90 days / 1 GB (whichever is reached first) | `docker-compose.monitoring.yml` (`--storage.tsdb.retention.*` flags) |
| Loki | 30 days | `monitoring/loki.yml` (`retention_period`) |
| Uptime Kuma | Unlimited (within disk) | Uptime Kuma web UI |
| Grafana | N/A (dashboards, not data) | — |

---

## Appendix: Complete Endpoint Reference

| Method | Path | Auth | LLM | Description |
|--------|------|------|-----|-------------|
| POST | `/v1/learn` | Yes | No | Store a pattern |
| POST | `/v1/recall` | Yes | No | Search patterns |
| POST | `/v1/evaluate` | Yes | Yes | Multi-LLM evaluation |
| POST | `/v1/compose` | Yes | Yes | Pipeline decomposition |
| POST | `/v1/evolve` | Yes | Yes | Prompt improvement |
| POST | `/v1/analyze-failures` | Yes | No | Failure clustering |
| POST | `/v1/aging` | Yes | No | Time-decay patterns |
| POST | `/v1/feedback/decay` | Yes | No | Time-decay feedback |
| GET | `/v1/feedback` | Yes | No | Top quality issues |
| GET | `/v1/metrics` | Yes | No | Aggregate statistics |
| GET | `/v1/health` | Yes | No | Basic health check |
| GET | `/v1/health/deep` | Yes | No | Deep health probe |
| GET | `/v1/export` | Yes | No | Export all patterns |
| POST | `/v1/import` | Yes | No | Bulk import patterns |
| DELETE | `/v1/patterns/{key}` | Yes | No | Delete a pattern |
| POST | `/v1/skills/register` | Yes | No | Tag pattern with skills |
| POST | `/v1/skills/search` | Yes | No | Find by skills |
| GET | `/v1/version` | No | No | Build metadata |
| POST | `/v1/keys/bootstrap` | Token | No | Create first owner key |
| POST | `/v1/keys` | Admin+ | No | Create API key |
| GET | `/v1/keys` | Admin+ | No | List API keys |
| DELETE | `/v1/keys/{id}` | Admin+ | No | Revoke API key |
| POST | `/v1/keys/{id}/rotate` | Admin+ | No | Rotate API key |
| GET | `/v1/jobs` | Yes | No | List async jobs |
| GET | `/v1/jobs/{id}` | Yes | No | Get job status |
| POST | `/v1/jobs/{id}/cancel` | Editor+ | No | Cancel pending job |
| GET | `/v1/billing/status` | Yes | No | Current plan & usage |
| POST | `/v1/billing/checkout` | Yes | No | Create checkout session |
| GET | `/v1/billing/portal` | Yes | No | Stripe Customer Portal URL |
| PATCH | `/v1/billing/overage` | Yes | No | Enable/disable overage |
| GET | `/v1/governance/retention` | Yes | No | Get retention policy |
| PUT | `/v1/governance/retention` | Yes | No | Set retention policy |
| POST | `/v1/governance/retention/apply` | Yes | No | Run retention cleanup |
| GET | `/v1/governance/export` | Yes | No | GDPR data export |
| PUT | `/v1/governance/patterns/{key}/classify` | Yes | No | Set data classification |
| DELETE | `/v1/governance/projects/{id}` | Yes | No | Delete project (GDPR) |
| DELETE | `/v1/governance/tenants/{id}` | Yes | No | Delete tenant (GDPR) |

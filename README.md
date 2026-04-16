# Engramia

Reusable execution memory and evaluation infrastructure for AI agent frameworks.

[![CI](https://github.com/engramia/engramia/actions/workflows/ci.yml/badge.svg)](https://github.com/engramia/engramia/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![License: BSL 1.1](https://img.shields.io/badge/license-BSL%201.1-orange)](LICENSE.txt)
[![Docs](https://img.shields.io/badge/docs-ReadTheDocs-blue)](https://engramia.readthedocs.io)

> **Status:** v0.6.5 — 1200+ tests / 80%+ coverage.
> Core library · REST API · 9 framework integrations · multi-tenancy · RBAC · async jobs · observability · data governance · ROI analytics.
> See [GitHub Issues](https://github.com/engramia/engramia/issues) for planned work and discussion.

---

## What it is

Engramia solves the problem every agent framework has: **agents don't learn from previous runs**.

LangChain, CrewAI, OpenAI Agents SDK, Pydantic AI, AutoGen, and similar frameworks are stateless — every run starts from scratch.
Engramia is a memory layer you add beneath any framework, and it:

- **Remembers** what worked (success patterns with time-decay)
- **Finds** relevant agents for a new task (semantic search + eval weighting)
- **Evaluates** code quality (multi-evaluator with variance detection)
- **Improves** automatically (feedback injection, pattern aging)
- **Composes** multi-agent pipelines from proven components *(Experimental)*

Extracted from Agent Factory V2 — a system that reached a 93% task success rate over 254 runs using Engramia as its memory layer.

---

## Who this is for

**Primary users:**
- AI platform teams building multi-agent pipelines
- Agent builders using LangChain, CrewAI, OpenAI Agents SDK, Pydantic AI, AutoGen, or custom frameworks
- Automation studios running repeated agentic workflows

**Not designed for:**
- End users without agent systems
- Pure ML/training workflows
- Single-run, one-shot LLM tasks

---

## Feature maturity

| Feature | Maturity |
|---------|----------|
| `learn` — store run results as success patterns | **Stable** |
| `recall` — semantic search over stored patterns | **Stable** |
| `evaluate` — multi-LLM scoring with variance detection | **Stable** |
| `get_feedback` — recurring quality issues for prompt injection | **Stable** |
| `run_aging` — time-decay + prune of stale patterns | **Stable** |
| `delete_pattern` — remove a stored pattern | **Stable** |
| `metrics` — aggregate run statistics | **Stable** |
| `export` / `import_data` — backup and migration | **Stable** |
| `register_skills` / `find_by_skills` — capability tagging | **Stable** |
| Tenant / project isolation (contextvars scope propagation) | **Stable** |
| RBAC (owner / admin / editor / reader) | **Stable** |
| DB API key management — bootstrap, create, rotate, revoke | **Stable** |
| OIDC SSO — JWT validation, JWKS, role + scope mapping | **Stable** |
| Async job layer — `Prefer: respond-async`, job status polling | **Stable** |
| Observability — OTel traces, Prometheus `/metrics`, JSON logs | **Stable** |
| Deep health — `GET /v1/health/deep` (storage + LLM + embeddings) | **Stable** |
| Data governance — PII redaction, retention, GDPR delete/export | **Stable** |
| ROI analytics — event collection, rollup API, composite score | **Stable** |
| Admin dashboard — separate app, see [engramia/dashboard](https://github.com/engramia/dashboard) | **Stable** |
| `compose` — LLM pipeline decomposition from patterns | **Experimental** |
| `evolve_prompt` — LLM-based prompt improvement | **Experimental** |
| `analyze_failures` — failure pattern clustering | **Experimental** |

---

## Installation

```bash
# Base (JSON storage, no LLM/embeddings provider)
pip install engramia

# With OpenAI provider (recommended to start)
pip install "engramia[openai]"

# REST API + PostgreSQL
pip install "engramia[openai,api,postgres]"
```

### Optional extras

| Extra | Contents | Status |
|-------|----------|--------|
| `openai` | OpenAI LLM + embeddings provider | ✅ |
| `postgres` | PostgreSQL + pgvector storage backend | ✅ |
| `api` | FastAPI REST server | ✅ |
| `anthropic` | Anthropic/Claude LLM provider | ✅ |
| `local` | sentence-transformers embeddings, no API key | ✅ |
| `langchain` | LangChain EngramiaCallback | ✅ |
| `crewai` | CrewAI EngramiaCrewCallback | ✅ |
| `openai-agents` | OpenAI Agents SDK RunHooks + dynamic instructions | ✅ |
| `anthropic-agents` | Anthropic Agent SDK query wrapper + hooks | ✅ |
| `pydantic-ai` | Pydantic AI Capability (before/after run) | ✅ |
| `autogen` | AutoGen Memory interface for AssistantAgent | ✅ |
| `cli` | CLI tool (Typer + Rich) | ✅ |
| `mcp` | MCP server (Claude Desktop, Cursor, Windsurf) | ✅ |
| `oidc` | SSO via OIDC JWT validation (Okta, Azure AD, Auth0, Keycloak) | ✅ |
| `dev` | pytest, coverage, development tools | ✅ |

---

## Quick start

```python
from engramia import Memory
from engramia.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage

mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)
```

---

## Python API Reference

### `mem.learn(task, code, eval_score, output=None) → LearnResult`

Records the result of a run. Stores the success pattern and updates metrics.

```python
result = mem.learn(
    task="Parse CSV file and compute statistics",
    code="import csv\nimport statistics\n...",
    eval_score=8.5,
    output="mean=42.3, std=7.1",  # optional: agent stdout
)
print(result.stored)        # True
print(result.pattern_count) # total number of patterns
```

- `eval_score` — number 0–10, how well the agent completed the task
- Pattern is automatically deduplicated against existing similar patterns (Jaccard > 0.7)

---

### `mem.recall(task, limit=5, deduplicate=True, eval_weighted=True) → list[Match]`

Finds relevant success patterns for a new task using semantic search.

```python
matches = mem.recall(task="Read CSV and calculate averages", limit=5)

for m in matches:
    print(f"{m.similarity:.2f} | score={m.pattern.success_score:.1f} | {m.pattern.task}")
    print(f"  key: {m.pattern_key}")   # use for delete_pattern()
```

Each `Match` contains:
- `similarity` — cosine similarity of embeddings (0.0–1.0)
- `reuse_tier` — `"duplicate"` / `"adapt"` / `"fresh"` based on similarity thresholds
- `pattern_key` — storage key for `delete_pattern()`
- `pattern` — `Pattern` object with `task`, `design`, `success_score`, `reuse_count`

Parameters:
- `deduplicate=True` — groups patterns of the same task (Jaccard > 0.7), returns only top-scoring per group
- `eval_weighted=True` — similarity is multiplied by a multiplier [0.5, 1.0] based on eval score; unrated patterns receive 0.75

---

### `mem.evaluate(task, code, output=None, num_evals=3) → EvalResult`

Runs N independent LLM evaluations and aggregates the results. Requires an `llm` provider.

```python
result = mem.evaluate(
    task="Parse CSV file",
    code="import csv\n...",
    output="done",    # optional
    num_evals=3,      # number of parallel LLM evaluations (min 1)
)

print(result.median_score)       # aggregated score (0–10)
print(result.variance)           # score variance across runs
print(result.high_variance)      # True if variance > 1.5
print(result.feedback)           # recommendation from the worst run
print(result.adversarial_detected)  # True if code contains hardcoded output
```

- Evaluations run in parallel (ThreadPoolExecutor)
- Feedback comes from the worst run (most relevant for improvement)
- Adversarial code detection (hardcoded output instead of computation)

---

### `mem.compose(task) → Pipeline` *(Experimental)*

Decomposes a task into a staged pipeline from existing success patterns. Requires an `llm` provider.

> **Experimental:** This feature works best as an assistive tool. Pipeline validity depends on pattern coverage and LLM output quality. Do not treat composed pipelines as guaranteed production-ready outputs.

```python
pipeline = mem.compose(task="Fetch stock data, compute moving average, write report")

print(f"valid={pipeline.valid}, errors={pipeline.contract_errors}")
for stage in pipeline.stages:
    print(f"[{stage.task}]  reads={stage.reads}  writes={stage.writes}")
```

- LLM decomposes the task into 2–4 stages
- Each stage is matched against success patterns via semantic search
- Contract validation verifies data flow consistency (reads/writes chain) including cycle detection
- Falls back to a single-stage pipeline if the LLM fails

---

### `mem.get_feedback(task_type=None, limit=5) → list[str]`

Returns recurring feedback patterns for injection into prompts.

```python
feedback = mem.get_feedback(limit=4)
# ["Add error handling for missing input files.",
#  "Validate CSV headers before processing.", ...]
```

- Returns only feedback with `count >= 2` (recurring issues)
- Sorted by frequency and recency (score × count)
- Suitable for automatic injection into the coder's system prompt

---

### `mem.delete_pattern(pattern_key) → bool`

Permanently deletes a stored pattern. Returns `True` if the pattern existed.

```python
matches = mem.recall(task="Parse CSV")
deleted = mem.delete_pattern(matches[0].pattern_key)
print(deleted)  # True
```

---

### `mem.run_aging() → int`

Applies time-decay to all success patterns. Returns the number of removed patterns.

```python
pruned = mem.run_aging()
print(f"Removed {pruned} outdated patterns")
```

- Decay: 2% per week (`success_score *= 0.98^weeks`)
- Pattern is removed if `success_score < 0.1`
- Recommended to run periodically (e.g., once a week)

---

### `mem.metrics → Metrics`

Current metrics of the memory instance.

```python
m = mem.metrics

print(m.runs)            # total number of recorded runs
print(m.success_rate)    # fraction of successful runs
print(m.avg_eval_score)  # average eval score (None if no evals)
print(m.pattern_count)   # current number of success patterns
print(m.pipeline_reuse)  # number of runs where an existing pattern was used
```

---

### `mem.evolve_prompt(role, current_prompt) → EvolutionResult` *(Experimental)*

Generates an improved prompt based on recurring quality issues.

> **Experimental:** Returns a candidate for manual review and A/B testing — not for direct automatic deployment.

```python
result = mem.evolve_prompt(role="coder", current_prompt="You are a coder...")
if result.accepted:
    print(result.improved_prompt)
    print(f"Changes: {result.changes}")
```

- Analyzes top feedback patterns from eval history
- LLM generates an improved version of the prompt
- Returns a candidate for manual/automated A/B testing

---

### `mem.analyze_failures(min_count=1) → list[FailureCluster]` *(Experimental)*

Groups recurring errors into clusters for identifying systemic issues.

> **Experimental:** Cluster quality depends on pattern volume and LLM classification accuracy.

```python
clusters = mem.analyze_failures(min_count=2)
for c in clusters:
    print(f"{c.representative} (count={c.total_count}, members={len(c.members)})")
```

---

### `mem.register_skills(pattern_key, skills)` / `mem.find_by_skills(required)`

Skill registry for capability-based pattern search.

```python
# Register
matches = mem.recall(task="Parse CSV")
mem.register_skills(matches[0].pattern_key, ["csv_parsing", "statistics"])

# Find
results = mem.find_by_skills(["csv_parsing"], match_all=True)
```

---

### `mem.export() → list[dict]` / `mem.import_data(records, overwrite=False) → int`

Backup and migration of patterns (JSON storage → PostgreSQL or vice versa).

```python
# Export all patterns to a JSONL file
import json

records = mem.export()
with open("backup.jsonl", "w") as f:
    for r in records:
        f.write(json.dumps(r) + "\n")

# Import from backup into a new instance
with open("backup.jsonl") as f:
    records = [json.loads(line) for line in f]

new_mem = Memory(embeddings=embeddings, storage=postgres_storage)
imported = new_mem.import_data(records)
print(f"Imported {imported} patterns")
```

---

### Exceptions

Engramia uses a custom exception hierarchy for precise error handling:

```python
from engramia import (
    EngramiaError, ProviderError, ValidationError,
    StorageError, QuotaExceededError, AuthorizationError,
)

try:
    result = mem.evaluate(task, code)
except ProviderError:
    # LLM provider is not configured
    pass
except ValidationError:
    # Invalid input (empty task, code too long, ...)
    pass
except QuotaExceededError:
    # Billing quota exceeded
    pass
except EngramiaError:
    # Any Engramia exception
    pass
```

---

### Framework integrations

Engramia integrates with every major agent framework. Each integration automatically
recalls relevant patterns before a run and learns from the result after.

#### OpenAI Agents SDK

```bash
pip install "engramia[openai-agents]"
```

```python
from agents import Agent, Runner
from engramia.sdk.openai_agents import EngramiaRunHooks, engramia_instructions

agent = Agent(
    name="coder",
    instructions=engramia_instructions(mem, base="You are a senior developer."),
)
result = await Runner.run(agent, "Build a CSV parser", hooks=EngramiaRunHooks(mem))
```

#### Anthropic Agent SDK

```bash
pip install "engramia[anthropic-agents]"
```

```python
from engramia.sdk.anthropic_agents import engramia_query

async for message in engramia_query(mem, prompt="Build a CSV parser"):
    print(message)
# Automatically recalls context → injects into system_prompt → learns from result.
```

#### Pydantic AI

```bash
pip install "engramia[pydantic-ai]"
```

```python
from pydantic_ai import Agent
from engramia.sdk.pydantic_ai import EngramiaCapability

agent = Agent('openai:gpt-4o', capabilities=[EngramiaCapability(mem)])
result = agent.run_sync("Build a CSV parser")
```

#### AutoGen

```bash
pip install "engramia[autogen]"
```

```python
from autogen_agentchat.agents import AssistantAgent
from engramia.sdk.autogen import EngramiaMemory, learn_from_result

agent = AssistantAgent(name="coder", model_client=client, memory=[EngramiaMemory(mem)])
result = await agent.run(task="Build a CSV parser")
learn_from_result(mem, task="Build a CSV parser", result=result)
```

#### LangChain

```bash
pip install "engramia[langchain]"
```

```python
from engramia.sdk.langchain import EngramiaCallback

callback = EngramiaCallback(mem, auto_learn=True, auto_recall=True)
chain.invoke(input, config={"callbacks": [callback]})
```

#### CrewAI

```bash
pip install "engramia[crewai]"
```

```python
from engramia.sdk.crewai import EngramiaCrewCallback

callback = EngramiaCrewCallback(mem, auto_learn=True, auto_recall=True)
result = callback.kickoff(crew)
```

#### REST API client (any language)

```python
from engramia.sdk.webhook import EngramiaWebhook

client = EngramiaWebhook(url="http://localhost:8000", api_key="sk-...")
client.learn(task="Parse CSV", code=code, eval_score=8.5)
matches = client.recall(task="Read CSV and compute averages")
```

#### Generic framework (EngramiaBridge)

```python
from engramia.sdk.bridge import EngramiaBridge

bridge = EngramiaBridge(data_path="./engramia_data")
context = bridge.before_run("Build a CSV parser")
result = my_agent(task, system_context=context)
bridge.after_run("Build a CSV parser", code=result, eval_score=8.0)
```

---

## REST API

### Starting up

```bash
# JSON storage (dev, no DB)
docker compose up

# PostgreSQL storage (prod)
ENGRAMIA_STORAGE=postgres \
ENGRAMIA_DATABASE_URL=postgresql://user:pass@localhost:5432/engramia \
OPENAI_API_KEY=sk-... \
docker compose up
```

After startup: Swagger UI at [http://localhost:8000/docs](http://localhost:8000/docs)

### Configuration (env vars)

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_STORAGE` | `json` | `json` or `postgres` |
| `ENGRAMIA_DATA_PATH` | `./engramia_data` | Path for JSON storage |
| `ENGRAMIA_DATABASE_URL` | — | PostgreSQL URL (only for `postgres`) |
| `ENGRAMIA_LLM_PROVIDER` | `openai` | LLM provider |
| `ENGRAMIA_LLM_MODEL` | `gpt-4.1` | Model ID |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `ENGRAMIA_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `ENGRAMIA_AUTH_MODE` | `auto` | Auth mode: `auto` / `env` / `db` / `dev` |
| `ENGRAMIA_API_KEYS` | *(empty)* | Bearer tokens — used when `AUTH_MODE=env` |
| `ENGRAMIA_ENVIRONMENT` | *(empty)* | `local` / `development` / `staging` / `production` — guards dev auth mode |
| `ENGRAMIA_PORT` | `8000` | Port |
| `ENGRAMIA_MAINTENANCE` | `false` | Maintenance mode (all endpoints → 503 except health) |

### Endpoints

All endpoints are available under the `/v1/` prefix:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/learn` | Stores a success pattern |
| `POST` | `/v1/recall` | Finds relevant patterns |
| `POST` | `/v1/compose` | Assembles a pipeline *(Experimental)* |
| `POST` | `/v1/evaluate` | Multi-eval scoring |
| `POST` | `/v1/aging` | Runs pattern aging (decay + prune) |
| `POST` | `/v1/feedback/decay` | Runs feedback decay |
| `POST` | `/v1/evolve` | Generates an improved prompt *(Experimental)* |
| `POST` | `/v1/analyze-failures` | Groups failure patterns *(Experimental)* |
| `POST` | `/v1/skills/register` | Registers skill tags on a pattern |
| `POST` | `/v1/skills/search` | Searches patterns by skill tags |
| `POST` | `/v1/import` | Bulk import patterns |
| `GET` | `/v1/feedback` | Top recurring feedback |
| `GET` | `/v1/metrics` | Statistics |
| `GET` | `/v1/health` | Health check + storage type |
| `GET` | `/v1/health/deep` | Deep probe: storage + LLM + embeddings latency |
| `GET` | `/v1/metrics` | Prometheus metrics (if `ENGRAMIA_METRICS=true`) |
| `DELETE` | `/v1/patterns/{key}` | Deletes a pattern |
| `POST` | `/v1/keys/bootstrap` | One-time owner key setup |
| `POST` | `/v1/keys` | Create API key (admin+) |
| `GET` | `/v1/keys` | List API keys (admin+) |
| `DELETE` | `/v1/keys/{id}` | Revoke key (admin+) |
| `POST` | `/v1/keys/{id}/rotate` | Rotate key (admin+) |
| `GET` | `/v1/jobs` | List async jobs |
| `GET` | `/v1/jobs/{id}` | Get job status + result |
| `POST` | `/v1/jobs/{id}/cancel` | Cancel pending job |
| `GET` | `/v1/governance/retention` | Get retention policy |
| `PUT` | `/v1/governance/retention` | Set retention policy |
| `POST` | `/v1/governance/retention/apply` | Run retention cleanup |
| `GET` | `/v1/governance/export` | NDJSON data export (GDPR Art. 20) |
| `PUT` | `/v1/governance/patterns/{key}/classify` | Set data classification |
| `DELETE` | `/v1/governance/projects/{id}` | Delete project data (GDPR Art. 17) |
| `DELETE` | `/v1/governance/tenants/{id}` | Delete tenant data (GDPR Art. 17) |
| `POST` | `/v1/analytics/rollup` | Trigger ROI rollup computation |
| `GET` | `/v1/analytics/rollup/{window}` | Fetch ROI snapshot (hourly/daily/weekly) |
| `GET` | `/v1/analytics/events` | Raw ROI events |

### Examples

```bash
# Learn
curl -X POST http://localhost:8000/v1/learn \
  -H "Content-Type: application/json" \
  -d '{"task": "Parse CSV", "code": "import csv", "eval_score": 8.5}'

# Recall
curl -X POST http://localhost:8000/v1/recall \
  -H "Content-Type: application/json" \
  -d '{"task": "Read CSV and compute averages", "limit": 3}'

# Metrics
curl http://localhost:8000/v1/metrics

# Health
curl http://localhost:8000/v1/health
```

### Authentication

```bash
# Set keys
ENGRAMIA_API_KEYS=my-secret-key docker compose up

# Use key
curl -H "Authorization: Bearer my-secret-key" http://localhost:8000/v1/metrics
```

### Security configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_CORS_ORIGINS` | *(empty)* | Allowed CORS origins (CORS disabled if empty) |
| `ENGRAMIA_RATE_LIMIT_DEFAULT` | `60` | Max requests/min for standard endpoints |
| `ENGRAMIA_RATE_LIMIT_EXPENSIVE` | `10` | Max requests/min for LLM-intensive endpoints |
| `ENGRAMIA_MAX_BODY_SIZE` | `1048576` | Max request body size in bytes (1 MB) |

### Observability configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_TELEMETRY` | `false` | Enable OpenTelemetry tracing |
| `ENGRAMIA_OTEL_ENDPOINT` | — | OTLP gRPC endpoint (e.g. `http://otel-collector:4317`) |
| `ENGRAMIA_METRICS` | `false` | Enable Prometheus `/metrics` endpoint |
| `ENGRAMIA_JSON_LOGS` | `false` | Emit structured JSON logs (request_id, trace_id, tenant_id) |

---

## PostgreSQL storage

Starting with pgvector backend:

```bash
# 1. Uncomment pgvector service in docker-compose.yml

# 2. Start
ENGRAMIA_STORAGE=postgres \
ENGRAMIA_DATABASE_URL=postgresql://engramia:engramia@pgvector:5432/engramia \
docker compose up

# 3. Apply migrations (first run)
docker compose exec engramia-api alembic upgrade head
```

Or without Docker:

```bash
pip install "engramia[openai,postgres]"

from engramia.providers.postgres import PostgresStorage
storage = PostgresStorage(database_url="postgresql://...")
mem = Memory(embeddings=OpenAIEmbeddings(), storage=storage, llm=OpenAIProvider())
```

---

## Provider configuration

### OpenAI (recommended)

```python
import os
os.environ["OPENAI_API_KEY"] = "sk-..."

from engramia.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage

mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(model="text-embedding-3-small"),
    storage=JSONStorage(path="./engramia_data"),
)
```

### Embeddings only, without LLM

```python
mem = Memory(
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
    llm=None,  # default
)

mem.learn(...)    # ✅ works
mem.recall(...)   # ✅ works
mem.evaluate(...) # ❌ ProviderError: evaluate() requires llm=...
```

---

## CLI

```bash
# Installation
pip install "engramia[cli]"

# Initialize
engramia init --path ./engramia_data

# Start REST API server
engramia serve --host 0.0.0.0 --port 8000

# Metrics and statistics
engramia status --path ./engramia_data

# Semantic search
engramia recall "Parse CSV and compute statistics" --limit 5

# Pattern aging (decay + prune)
engramia aging --path ./engramia_data
```

---

## MCP Server

Engramia can be run as an **MCP server** (Model Context Protocol) and connected
directly to Claude Desktop, Cursor, Windsurf, or VS Code Copilot.

### Installation

```bash
pip install "engramia[openai,mcp]"
```

### Starting up

```bash
engramia-mcp
```

The server runs via **stdio transport** — the MCP client starts it as a subprocess automatically.

### Client configuration

**Claude Desktop** (`~/.config/claude/claude_desktop_config.json` on Linux/macOS,
`%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "engramia": {
      "command": "engramia-mcp",
      "env": {
        "ENGRAMIA_DATA_PATH": "/path/to/engramia_data",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

**Cursor / Windsurf** — same JSON format in the MCP servers settings of the respective IDE.

### Available MCP tools

| Tool | Description |
|------|-------------|
| `engramia_learn` | Stores a run result as a success pattern |
| `engramia_recall` | Finds relevant patterns for a new task (semantic search) |
| `engramia_evaluate` | N independent LLM evaluations, median + variance |
| `engramia_compose` | Decomposes a task into a validated multi-agent pipeline *(Experimental)* |
| `engramia_feedback` | Returns recurring quality issues for injection into prompts |
| `engramia_metrics` | Statistics (runs, success rate, pattern count, reuse rate) |
| `engramia_aging` | Runs time-based decay + prune of outdated patterns |

### Configuration (env vars)

The MCP server uses the same env vars as the REST API:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_STORAGE` | `json` | `json` or `postgres` |
| `ENGRAMIA_DATA_PATH` | `./engramia_data` | Path for JSON storage |
| `ENGRAMIA_DATABASE_URL` | — | PostgreSQL URL (only for `postgres`) |
| `ENGRAMIA_LLM_PROVIDER` | `openai` | LLM provider |
| `ENGRAMIA_LLM_MODEL` | `gpt-4.1` | Model ID |
| `OPENAI_API_KEY` | — | OpenAI API key |

---

## Architecture

```
engramia/
├── memory.py            # Memory facade — thin delegator (~165 LOC)
├── types.py             # Pydantic models (Scope, AuthContext, Pattern, ...)
├── exceptions.py        # EngramiaError hierarchy (ProviderError, StorageError, ...)
├── _context.py          # Scope contextvar: get_scope / set_scope / reset_scope
├── _util.py             # Helpers (extract_json_from_llm, jaccard, reuse_tier)
├── _factory.py          # Provider factory from env vars
│
├── core/                # Pattern storage + evaluation
│   ├── services/             # Business logic (extracted from Memory god object)
│   │   ├── learning.py       # LearningService — store patterns, embeddings, ROI
│   │   ├── recall.py         # RecallService — semantic search, dedup, eval-weighted
│   │   ├── evaluation.py     # EvaluationService — multi-evaluator scoring + feedback
│   │   └── composition.py    # CompositionService — LLM pipeline decomposition
│   ├── success_patterns.py   # Aging, reuse boost
│   ├── eval_store.py         # Eval history + quality multiplier
│   ├── eval_feedback.py      # Feedback clustering + decay
│   ├── metrics.py            # Run statistics
│   └── skill_registry.py     # Capability-based pattern tagging
│
├── reuse/               # Reuse engine
│   ├── matcher.py            # Semantic search + eval weighting
│   ├── composer.py           # LLM pipeline decomposition (Experimental)
│   └── contracts.py          # Data-flow validation + cycle detection
│
├── eval/
│   └── evaluator.py          # MultiEvaluator (concurrent, median, variance)
│
├── providers/
│   ├── base.py               # ABC: LLMProvider, EmbeddingProvider, StorageBackend
│   ├── openai.py             # OpenAI LLM + embeddings
│   ├── anthropic.py          # Anthropic/Claude LLM provider
│   ├── local_embeddings.py   # sentence-transformers (no API key)
│   ├── json_storage.py       # JSON storage (thread-safe, atomic writes)
│   └── postgres.py           # PostgreSQL + pgvector (scope-aware queries)
│
├── api/                 # REST API
│   ├── app.py                # App factory, lifespan, startup/shutdown
│   ├── routes.py             # Core endpoints (learn, recall, evaluate, ...)
│   ├── auth.py               # Multi-mode auth (auto/env/db/dev)
│   ├── keys.py               # API key management router (/v1/keys)
│   ├── permissions.py        # RBAC: 4 roles, require_permission() factory
│   ├── deps.py               # Dependency injection (Memory singleton, AuthContext)
│   ├── schemas.py            # Request/response Pydantic models
│   ├── audit.py              # Structured audit logging
│   ├── middleware.py         # SecurityHeaders, RateLimit, BodySize, RequestID, Timing
│   └── prom_metrics.py       # Prometheus counter/histogram definitions
│
├── jobs/                # Async job queue
│   ├── service.py            # JobService — submit, poll, cancel, retry/backoff
│   ├── worker.py             # JobWorker — daemon thread, ThreadPoolExecutor
│   └── dispatch.py           # Operation → Memory method dispatcher
│
├── analytics/           # ROI analytics
│   ├── collector.py          # ROICollector — fire-and-ignore event recorder
│   ├── aggregator.py         # ROIAggregator — hourly/daily/weekly rollups
│   └── models.py             # ROIEvent, ROIRollup, RecallOutcome, LearnSummary
│
├── governance/          # Data governance (GDPR)
│   ├── redaction.py          # PII/secrets redaction pipeline
│   ├── retention.py          # RetentionManager — per-tenant/project TTL policies
│   ├── deletion.py           # ScopedDeletion — GDPR Art. 17 right to erasure
│   ├── export.py             # DataExporter — NDJSON export (GDPR Art. 20)
│   └── lifecycle.py          # Async lifecycle jobs (retention_cleanup, compact_audit)
│
├── telemetry/           # Observability (opt-in, zero overhead when disabled)
│   ├── tracing.py            # OTel init + @traced decorator
│   └── metrics.py            # Prometheus histogram/counter definitions
│
├── db/                  # Database
│   ├── models.py             # SQLAlchemy 2.x models (13 migrations applied)
│   └── migrations/           # Alembic (001_initial → 013_cloud_users)
│
├── evolution/           # Prompt evolution + failure clustering (Experimental)
│   ├── prompt_evolver.py
│   └── failure_cluster.py
│
├── sdk/                 # Framework integrations (9 adapters)
│   ├── openai_agents.py      # OpenAI Agents SDK — RunHooks + dynamic instructions
│   ├── anthropic_agents.py   # Anthropic Agent SDK — query wrapper + hooks
│   ├── pydantic_ai.py        # Pydantic AI — Capability (before/after run)
│   ├── autogen.py            # AutoGen — Memory ABC for AssistantAgent
│   ├── langchain.py          # LangChain — EngramiaCallback
│   ├── crewai.py             # CrewAI — EngramiaCrewCallback
│   ├── bridge.py             # EngramiaBridge — drop-in for any agent factory
│   └── webhook.py            # Lightweight HTTP SDK client (stdlib only)
│
├── cli/                 # CLI tool (Typer + Rich)
│
└── mcp/                 # MCP server (stdio transport)
    └── server.py             # 7 MCP tools (learn, recall, evaluate, ...)
```

---

## Implementation status

| Component | Status |
|-----------|--------|
| `mem.learn()` | ✅ Stable |
| `mem.recall()` | ✅ Stable |
| `mem.evaluate()` | ✅ Stable |
| `mem.compose()` | ✅ Experimental |
| `mem.get_feedback()` | ✅ Stable |
| `mem.run_aging()` | ✅ Stable |
| `mem.delete_pattern()` | ✅ Stable |
| `mem.evolve_prompt()` | ✅ Experimental |
| `mem.analyze_failures()` | ✅ Experimental |
| `mem.register_skills()` / `find_by_skills()` | ✅ Stable |
| `mem.metrics` | ✅ Stable |
| `mem.export()` / `mem.import_data()` | ✅ Stable |
| Custom exception hierarchy | ✅ Stable |
| OpenAI provider | ✅ Stable |
| Anthropic provider | ✅ Stable |
| Local embeddings (sentence-transformers) | ✅ Stable |
| JSON storage (thread-safe, concurrent) | ✅ Stable |
| PostgreSQL + pgvector (scope-aware) | ✅ Stable |
| Docker + docker-compose | ✅ Stable |
| Multi-tenancy + scope isolation (contextvars) | ✅ Stable |
| RBAC (4 roles, DB API key management) | ✅ Stable |
| Async job layer (SKIP LOCKED, retry, backoff) | ✅ Stable |
| Observability (OTel, Prometheus, JSON logs) | ✅ Stable |
| Data governance (PII redaction, retention, GDPR) | ✅ Stable |
| ROI analytics (collector, rollup, REST API) | ✅ Stable |
| Admin dashboard (separate repo: [engramia/dashboard](https://github.com/engramia/dashboard)) | ✅ Stable |
| Service layer (LearningService, RecallService, ...) | ✅ Stable |
| OpenAI Agents SDK integration (RunHooks + instructions) | ✅ Stable |
| Anthropic Agent SDK integration (query wrapper + hooks) | ✅ Stable |
| Pydantic AI integration (Capability) | ✅ Stable |
| AutoGen integration (Memory ABC) | ✅ Stable |
| LangChain EngramiaCallback | ✅ Stable |
| CrewAI EngramiaCrewCallback | ✅ Stable |
| EngramiaBridge (drop-in agent factory adapter) | ✅ Stable |
| Webhook SDK client | ✅ Stable |
| CLI (Typer + Rich) | ✅ Stable |
| MCP server (7 tools, stdio transport) | ✅ Stable |

---

## Development and testing

```bash
# Install for development
pip install -e ".[dev,openai]"

# Run tests
pytest

# With coverage report
pytest --cov=engramia --cov-report=term-missing
```

Tests do not require API keys — they use `FakeEmbeddings` (deterministic vectors from MD5 hash) and a mocked LLM. FastAPI tests use `TestClient` from httpx.

---

## Origin

Extracted from Agent Factory V2 — a self-improving AI agent factory.
Agent Factory V2 remains as an open-source reference implementation that demonstrates Engramia working in a production-grade multi-agent system.

---

## License

Engramia is licensed under Business Source License 1.1 (BUSL-1.1).

- ✅ Free for: personal use, evaluation, research
- ❌ Not allowed without a commercial license:
  - production use in commercial environments
  - SaaS / hosted services
  - integration into paid products
  - building competing products

On the Change Date specified in `LICENSE.txt`, the license automatically
converts to Apache 2.0.

See `LICENSE.txt` for full terms.

For commercial licenses: support@engramia.dev

### License FAQ

**Why does PyPI show "UNKNOWN" or no license classifier?**
BUSL-1.1 is not OSI-approved, so PyPI lacks a dedicated classifier.
Engramia ships the full BUSL-1.1 text in `LICENSE.txt` and declares it
via `license = {file = "LICENSE.txt"}` in `pyproject.toml`. Package
scanners that flag "Proprietary" for non-OSI licenses are technically
correct — BUSL-1.1 is **source-available**, not open source or
proprietary in the classical sense. On the Change Date, the license
converts to Apache 2.0 (OSI-approved).

**Can I use Engramia in my company's internal tools?**
Yes — internal, non-competing production use is permitted under the
Additional Use Grant in `LICENSE.txt`. Re-hosting Engramia as a paid
service, or embedding it in a competing commercial offering, requires
a commercial license.

**Can I fork and modify the code?**
Yes. Modifications and redistribution under BUSL-1.1 terms are allowed.
Any derivative work carries the same license until the Change Date.

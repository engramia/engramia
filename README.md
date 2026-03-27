# Engramia

Self-learning memory layer for AI agent frameworks.

[![CI](https://github.com/engramia/engramia/actions/workflows/ci.yml/badge.svg)](https://github.com/engramia/engramia/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![License: BSL 1.1](https://img.shields.io/badge/license-BSL%201.1-orange)](LICENSE.txt)

> **Status:** Phases 0–4.5 complete — core library + REST API + SDK plugins + prompt evolution + CLI + exceptions + export/import + security hardening (OWASP ASVS Level 2/3).
> See [roadmap.md](roadmap.md) for what's next.

---

## What it is

Engramia solves the problem every agent framework has: **agents don't learn from previous runs**.

LangChain, CrewAI, AutoGPT, and similar frameworks are stateless — every run starts from scratch.
Brain is a memory layer you add beneath any framework, and it:

- **Remembers** what worked (success patterns with time-decay)
- **Finds** relevant agents for a new task (semantic search + eval weighting)
- **Composes** multi-agent pipelines from proven components (contract validation)
- **Evaluates** code quality (multi-evaluator with variance detection)
- **Improves** automatically (feedback injection, pattern aging)

Extracted from Agent Factory V2 — a system that learned to achieve a 93% success rate over 254 runs.

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
| `cli` | CLI tool (Typer + Rich) | ✅ |
| `mcp` | MCP server (Claude Desktop, Cursor, Windsurf) | ✅ |
| `dev` | pytest, coverage, development tools | ✅ |

---

## Quick start

```python
from engramia import Memory
from engramia.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage

mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./brain_data"),
)
```

---

## Python API Reference

### `brain.learn(task, code, eval_score, output=None) → LearnResult`

Records the result of a run. Stores the success pattern and updates metrics.

```python
result = brain.learn(
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

### `brain.recall(task, limit=5, deduplicate=True, eval_weighted=True) → list[Match]`

Finds relevant success patterns for a new task using semantic search.

```python
matches = brain.recall(task="Read CSV and calculate averages", limit=5)

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

### `brain.evaluate(task, code, output=None, num_evals=3) → EvalResult`

Runs N independent LLM evaluations and aggregates the results. Requires an `llm` provider.

```python
result = brain.evaluate(
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

### `brain.compose(task) → Pipeline`

Decomposes a task into a staged pipeline from existing success patterns. Requires an `llm` provider.

```python
pipeline = brain.compose(task="Fetch stock data, compute moving average, write report")

print(f"valid={pipeline.valid}, errors={pipeline.contract_errors}")
for stage in pipeline.stages:
    print(f"[{stage.task}]  reads={stage.reads}  writes={stage.writes}")
```

- LLM decomposes the task into 2–4 stages
- Each stage is matched against success patterns via semantic search
- Contract validation verifies data flow consistency (reads/writes chain) including cycle detection
- Falls back to a single-stage pipeline if the LLM fails

---

### `brain.get_feedback(task_type=None, limit=5) → list[str]`

Returns recurring feedback patterns for injection into prompts.

```python
feedback = brain.get_feedback(limit=4)
# ["Add error handling for missing input files.",
#  "Validate CSV headers before processing.", ...]
```

- Returns only feedback with `count >= 2` (recurring issues)
- Sorted by frequency and recency (score × count)
- Suitable for automatic injection into the coder's system prompt

---

### `brain.delete_pattern(pattern_key) → bool`

Permanently deletes a stored pattern. Returns `True` if the pattern existed.

```python
matches = brain.recall(task="Parse CSV")
deleted = brain.delete_pattern(matches[0].pattern_key)
print(deleted)  # True
```

---

### `brain.run_aging() → int`

Applies time-decay to all success patterns. Returns the number of removed patterns.

```python
pruned = brain.run_aging()
print(f"Removed {pruned} outdated patterns")
```

- Decay: 2% per week (`success_score *= 0.98^weeks`)
- Pattern is removed if `success_score < 0.1`
- Recommended to run periodically (e.g., once a week)

---

### `brain.metrics → Metrics`

Current metrics of the brain instance.

```python
m = brain.metrics

print(m.runs)            # total number of recorded runs
print(m.success_rate)    # fraction of successful runs
print(m.avg_eval_score)  # average eval score (None if no evals)
print(m.pattern_count)   # current number of success patterns
print(m.pipeline_reuse)  # number of runs where an existing pattern was used
```

---

### `brain.evolve_prompt(role, current_prompt) → EvolutionResult`

Generates an improved prompt based on recurring quality issues.

```python
result = brain.evolve_prompt(role="coder", current_prompt="You are a coder...")
if result.accepted:
    print(result.improved_prompt)
    print(f"Changes: {result.changes}")
```

- Analyzes top feedback patterns from eval history
- LLM generates an improved version of the prompt
- Returns a candidate for manual/automated A/B testing

---

### `brain.analyze_failures(min_count=1) → list[FailureCluster]`

Groups recurring errors into clusters for identifying systemic issues.

```python
clusters = brain.analyze_failures(min_count=2)
for c in clusters:
    print(f"{c.representative} (count={c.total_count}, members={len(c.members)})")
```

---

### `brain.register_skills(pattern_key, skills)` / `brain.find_by_skills(required)`

Skill registry for capability-based pattern search.

```python
# Register
matches = brain.recall(task="Parse CSV")
brain.register_skills(matches[0].pattern_key, ["csv_parsing", "statistics"])

# Find
results = brain.find_by_skills(["csv_parsing"], match_all=True)
```

---

### `brain.export() → list[dict]` / `brain.import_data(records, overwrite=False) → int`

Backup and migration of patterns (JSON storage → PostgreSQL or vice versa).

```python
# Export all patterns to a JSONL file
import json

records = brain.export()
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

Brain uses a custom exception hierarchy for precise error handling:

```python
from engramia import MemoryError, ProviderError, ValidationError, StorageError

try:
    result = brain.evaluate(task, code)
except ProviderError:
    # LLM provider is not configured
    pass
except ValidationError:
    # Invalid input (empty task, code too long, ...)
    pass
except EngramiaError:
    # Any Brain exception
    pass
```

---

### LangChain integration

```python
from engramia.sdk.langchain import EngramiaCallback

callback = EngramiaCallback(brain, auto_learn=True, auto_recall=True)
chain = LLMChain(llm=llm, prompt=prompt, callbacks=[callback])
# Brain automatically learns from chain runs and recalls relevant context
```

---

### Webhook SDK client

```python
from engramia.sdk.webhook import EngramiaWebhook

hook = EngramiaWebhook(url="http://localhost:8000", api_key="sk-...")
hook.learn(task="Parse CSV", code=code, eval_score=8.5)
matches = hook.recall(task="Read CSV and compute averages")
```

---

## REST API

### Starting up

```bash
# JSON storage (dev, no DB)
docker compose up

# PostgreSQL storage (prod)
ENGRAMIA_STORAGE=postgres \
ENGRAMIA_DATABASE_URL=postgresql://user:pass@localhost:5432/brain \
OPENAI_API_KEY=sk-... \
docker compose up
```

After startup: Swagger UI at [http://localhost:8000/docs](http://localhost:8000/docs)

### Configuration (env vars)

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_STORAGE` | `json` | `json` or `postgres` |
| `ENGRAMIA_DATA_PATH` | `./brain_data` | Path for JSON storage |
| `ENGRAMIA_DATABASE_URL` | — | PostgreSQL URL (only for `postgres`) |
| `ENGRAMIA_LLM_PROVIDER` | `openai` | LLM provider |
| `ENGRAMIA_LLM_MODEL` | `gpt-4.1` | Model ID |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `ENGRAMIA_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `ENGRAMIA_API_KEYS` | *(empty)* | Bearer tokens (empty = dev mode, no auth) |
| `ENGRAMIA_PORT` | `8000` | Port |

### Endpoints

All endpoints are available under the `/v1/` prefix:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/learn` | Stores a success pattern |
| `POST` | `/v1/recall` | Finds relevant patterns |
| `POST` | `/v1/compose` | Assembles a pipeline |
| `POST` | `/v1/evaluate` | Multi-eval scoring |
| `POST` | `/v1/aging` | Runs pattern aging (decay + prune) |
| `POST` | `/v1/feedback/decay` | Runs feedback decay |
| `POST` | `/v1/evolve` | Generates an improved prompt |
| `POST` | `/v1/analyze-failures` | Groups failure patterns |
| `POST` | `/v1/skills/register` | Registers skill tags on a pattern |
| `POST` | `/v1/skills/search` | Searches patterns by skill tags |
| `GET` | `/v1/feedback` | Top recurring feedback |
| `GET` | `/v1/metrics` | Statistics |
| `GET` | `/v1/health` | Health check + storage type |
| `DELETE` | `/v1/patterns/{key}` | Deletes a pattern |

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

---

## PostgreSQL storage

Starting with pgvector backend:

```bash
# 1. Uncomment pgvector service in docker-compose.yml

# 2. Start
ENGRAMIA_STORAGE=postgres \
ENGRAMIA_DATABASE_URL=postgresql://brain:brain@pgvector:5432/brain \
docker compose up

# 3. Apply migrations (first run)
docker compose exec brain-api alembic upgrade head
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
    storage=JSONStorage(path="./brain_data"),
)
```

### Embeddings only, without LLM

```python
mem = Memory(
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./brain_data"),
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
engramia init --path ./brain_data

# Start REST API server
engramia serve --host 0.0.0.0 --port 8000

# Metrics and statistics
engramia status --path ./brain_data

# Semantic search
engramia recall "Parse CSV and compute statistics" --limit 5

# Pattern aging (decay + prune)
engramia aging --path ./brain_data
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
        "ENGRAMIA_DATA_PATH": "/path/to/brain_data",
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
| `brain_learn` | Stores a run result as a success pattern |
| `brain_recall` | Finds relevant patterns for a new task (semantic search) |
| `brain_evaluate` | N independent LLM evaluations, median + variance |
| `brain_compose` | Decomposes a task into a validated multi-agent pipeline |
| `brain_feedback` | Returns recurring quality issues for injection into prompts |
| `brain_metrics` | Statistics (runs, success rate, pattern count, reuse rate) |
| `brain_aging` | Runs time-based decay + prune of outdated patterns |

### Configuration (env vars)

The MCP server uses the same env vars as the REST API:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_STORAGE` | `json` | `json` or `postgres` |
| `ENGRAMIA_DATA_PATH` | `./brain_data` | Path for JSON storage |
| `ENGRAMIA_DATABASE_URL` | — | PostgreSQL URL (only for `postgres`) |
| `ENGRAMIA_LLM_PROVIDER` | `openai` | LLM provider |
| `ENGRAMIA_LLM_MODEL` | `gpt-4.1` | Model ID |
| `OPENAI_API_KEY` | — | OpenAI API key |

---

## Architecture

```
engramia/
├── brain.py             # Brain facade (public API)
├── types.py             # Pydantic models
├── _util.py             # Shared utility
│
├── core/                # Internal stores
│   ├── success_patterns.py   # Aging, reuse boost
│   ├── eval_store.py         # Eval history + quality multiplier
│   ├── eval_feedback.py      # Feedback clustering + decay
│   ├── metrics.py            # Run statistics
│   └── skill_registry.py     # Capability-based pattern tagging
│
├── reuse/               # Reuse engine
│   ├── matcher.py            # Semantic search + eval weighting
│   ├── composer.py           # LLM pipeline decomposition
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
│   └── postgres.py           # PostgreSQL + pgvector
│
├── api/                 # REST API (Phase 2)
│   ├── app.py                # App factory, env var configuration
│   ├── routes.py             # Endpoints
│   ├── auth.py               # Bearer token middleware
│   ├── deps.py               # Dependency injection
│   └── schemas.py            # API models
│
├── db/                  # Database (Phase 2)
│   ├── models.py             # SQLAlchemy models
│   └── migrations/           # Alembic
│
├── evolution/           # Prompt evolution + failure clustering (Phase 3)
│   ├── prompt_evolver.py    # LLM-based prompt improvement
│   └── failure_cluster.py   # Failure pattern clustering
│
├── sdk/                 # Framework integrations (Phase 3)
│   ├── langchain.py         # LangChain EngramiaCallback
│   └── webhook.py           # Lightweight HTTP SDK client
│
├── exceptions.py        # Custom exception hierarchy (EngramiaError, ProviderError, ...)
├── _factory.py          # Shared Brain provider factory (REST API + MCP)
│
├── cli/                 # CLI tool (Typer + Rich)
│
└── mcp/                 # MCP server (Phase 4.6.9)
    └── server.py            # stdio MCP server — 7 Brain tools
```

---

## Implementation status

| Component | Status |
|-----------|--------|
| `brain.learn()` | ✅ |
| `brain.recall()` | ✅ |
| `brain.evaluate()` | ✅ |
| `brain.compose()` | ✅ |
| `brain.get_feedback()` | ✅ |
| `brain.run_aging()` | ✅ |
| `brain.delete_pattern()` | ✅ |
| `brain.evolve_prompt()` | ✅ Phase 3 |
| `brain.analyze_failures()` | ✅ Phase 3 |
| `brain.register_skills()` / `find_by_skills()` | ✅ Phase 3 |
| `brain.metrics` | ✅ |
| `brain.export()` / `brain.import_data()` | ✅ Phase 4 |
| Custom exception hierarchy | ✅ Phase 4 |
| OpenAI provider | ✅ |
| Anthropic provider | ✅ Phase 3 |
| Local embeddings (sentence-transformers) | ✅ Phase 3 |
| JSON storage (thread-safe) | ✅ |
| REST API (FastAPI) — 14 endpoints | ✅ Phase 2+3+4 |
| PostgreSQL + pgvector | ✅ Phase 2 |
| Docker + docker-compose | ✅ Phase 2 |
| LangChain EngramiaCallback | ✅ Phase 3 |
| Webhook SDK client | ✅ Phase 3 |
| CLI (Typer + Rich) | ✅ Phase 4 |
| MCP server (7 tools, stdio transport) | ✅ Phase 4.6.9 |
| CrewAI EngramiaCrewCallback | ✅ Phase 4.6.8 |

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
Factory remains as an open-source reference implementation that proves Brain works in practice.

---

## License

Engramia is licensed under Business Source License 1.1 (BSL 1.1).

- ✅ Free for: personal use, evaluation, research
- ❌ Not allowed without a commercial license:
  - production use in commercial environments
  - SaaS / hosted services
  - integration into paid products
  - building competing products

See LICENSE.txt for full terms.

For commercial licenses: support@engramia.dev

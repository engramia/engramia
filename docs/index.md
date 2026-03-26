# Engramia

**Self-learning memory layer for AI agent frameworks.**

Engramia solves a problem every agent framework has: **agents don't learn from previous runs**.

LangChain, CrewAI, AutoGPT and similar frameworks are static — every run starts from scratch.
Engramia is a memory layer you add under any framework that:

- **Remembers** what worked (success patterns with time-decay)
- **Finds** relevant agents for new tasks (semantic search + eval weighting)
- **Composes** multi-agent pipelines from proven components (contract validation)
- **Evaluates** code quality (multi-evaluator with variance detection)
- **Improves** automatically (feedback injection, prompt evolution, pattern aging)

Extracted from Agent Factory V2 — a system that learned to achieve **93% success rate over 254 runs**.

## Quick example

```python
from engramia import Memory
from engramia.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage

mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./brain_data"),
)

# Learn from a successful run
mem.learn(task="Parse CSV and compute stats", code=code, eval_score=8.5)

# Recall relevant patterns for a new task
matches = mem.recall(task="Read CSV and calculate averages", limit=5)

# Compose a multi-step pipeline
pipeline = mem.compose(task="Fetch data, analyze, write report")
```

## Features

| Feature | Description |
|---------|-------------|
| **Learn & Recall** | Store successful agent runs, find relevant patterns via semantic search |
| **Multi-eval scoring** | N independent LLM evaluations, median aggregation, variance detection |
| **Pipeline composition** | LLM decomposes tasks into stages, matches with existing patterns, validates data flow |
| **Feedback injection** | Recurring quality issues auto-injected into prompts |
| **Prompt evolution** | LLM generates improved prompts based on failure analysis |
| **Pattern aging** | 2%/week time-decay, automatic pruning of stale patterns |
| **Skill registry** | Capability-based pattern tagging and search |
| **Export/Import** | JSONL-compatible backup and migration |

## Provider-agnostic

Engramia is **model-agnostic** and **storage-agnostic**:

- **LLM**: OpenAI, Anthropic, or any provider implementing `LLMProvider` ABC
- **Embeddings**: OpenAI, local models (sentence-transformers, no API key needed)
- **Storage**: JSON files (dev) or PostgreSQL + pgvector (production)

## Multiple interfaces

- **Python library** — `pip install engramia`
- **REST API** — FastAPI with Swagger UI, Bearer auth, rate limiting
- **CLI** — `engramia init / serve / status / recall / aging`
- **MCP Server** — Claude Desktop, Cursor, Windsurf integration
- **LangChain callback** — auto-learn and auto-recall
- **Webhook SDK** — lightweight HTTP client (no dependencies)

## License

[Business Source License 1.1 (BSL 1.1)](https://github.com/engramia/engramia/blob/main/LICENSE.txt) — source code is publicly readable, commercial use requires a license.

| Use case | Status |
|----------|--------|
| Personal projects, testing, academic research | Free |
| Commercial use (production, SaaS) | Requires commercial license |
| After 2030 | Apache 2.0 (free for everyone) |

Contact: support@engramia.dev

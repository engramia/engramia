# Concepts & Architecture

## Overview

Engramia is a **memory layer** that sits under any AI agent framework. It provides a closed-loop learning system where agents improve over time by learning from past runs.

```
┌─────────────────────────────────────┐
│         Your Agent Framework        │
│    (LangChain, CrewAI, custom...)   │
└──────────────┬──────────────────────┘
               │
       ┌───────▼───────┐
       │   Engramia    │
       │   Memory      │
       └───────┬───────┘
               │
    ┌──────────┼──────────┐
    ▼          ▼          ▼
 ┌──────┐ ┌────────┐ ┌────────┐
 │ LLM  │ │Embed-  │ │Storage │
 │      │ │dings   │ │        │
 └──────┘ └────────┘ └────────┘
```

## Core loop

The fundamental Engramia loop is:

1. **Learn** — After an agent run, store the task, code, eval score, and output as a success pattern
2. **Recall** — Before a new run, find relevant past patterns via semantic search
3. **Evaluate** — Score the output with multiple independent LLM evaluators
4. **Improve** — Inject recurring feedback into prompts, evolve prompts automatically

Over time, patterns with high eval scores float to the top, while stale patterns decay and get pruned.

## Key concepts

### Success patterns

A **pattern** is a record of a successful agent run:

- **task** — what the agent was asked to do
- **design** — the code/solution produced
- **success_score** — quality rating (0–10)
- **reuse_count** — how many times this pattern has been recalled
- **timestamp** — when it was stored

Patterns are the primary unit of memory. They are stored with embeddings for semantic search and subject to time-based decay.

### Pattern aging

Patterns lose relevance over time. Engramia applies **2% decay per week** to success scores:

```
score *= 0.98 ^ weeks_since_creation
```

When a score drops below 0.1, the pattern is pruned. This ensures the memory stays fresh — new, high-quality patterns naturally replace old ones.

### Reuse boost

When a pattern is recalled and used, its reuse count increments and its effective score gets a **+0.1 boost** (capped at 10.0). Frequently useful patterns survive longer.

### Eval-weighted search

When recalling patterns, similarity scores are multiplied by an **eval quality multiplier** in the range [0.5, 1.0]:

- Patterns with consistently high eval scores get a multiplier close to 1.0
- Patterns with low or no eval history get 0.75 (neutral)
- This means high-quality patterns rank higher even if their embedding similarity is slightly lower

### Feedback clustering

Engramia tracks recurring quality issues from evaluations. Feedback strings are clustered using **Jaccard similarity** (threshold > 0.4). When a feedback cluster reaches count >= 2, it becomes available for injection into prompts.

Feedback also decays at **10% per week**, so transient issues fade while persistent problems stay visible.

### Contract validation

When composing multi-stage pipelines, each stage declares what data it **reads** and **writes**. Engramia validates:

- Every input a stage reads must be produced by a prior stage (or be an initial input)
- No circular dependencies exist in the data flow
- The pipeline forms a valid DAG

### Multi-eval scoring

Instead of a single LLM evaluation, Engramia runs **N independent evaluations** in parallel:

- Results are aggregated using the **median** (robust to outliers)
- **Variance > 1.5** triggers a warning — evaluators disagree significantly
- Feedback comes from the **worst run** (most useful for improvement)
- Adversarial detection catches hardcoded outputs

## Architecture

```
engramia/
├── memory.py                 # Memory facade (public API)
├── types.py                 # Pydantic models (Pattern, Match, EvalResult, ...)
├── exceptions.py            # EngramiaError hierarchy
├── _util.py                 # Shared utilities
├── _factory.py              # Provider factory (REST API + MCP)
│
├── core/                    # Internal stores
│   ├── success_patterns.py  # Pattern storage, aging, reuse tracking
│   ├── eval_store.py        # Eval results, quality multiplier
│   ├── eval_feedback.py     # Feedback clustering + decay
│   ├── metrics.py           # Run statistics
│   └── skill_registry.py    # Capability-based tagging
│
├── reuse/                   # Reuse engine
│   ├── matcher.py           # Semantic search + eval weighting
│   ├── composer.py          # LLM pipeline decomposition
│   └── contracts.py         # Data-flow validation + cycle detection
│
├── eval/
│   └── evaluator.py         # MultiEvaluator (concurrent, median, variance)
│
├── providers/               # Pluggable backends
│   ├── base.py              # ABC: LLMProvider, EmbeddingProvider, StorageBackend
│   ├── openai.py            # OpenAI LLM + embeddings
│   ├── anthropic.py         # Anthropic/Claude LLM
│   ├── local_embeddings.py  # sentence-transformers (no API key)
│   ├── json_storage.py      # JSON storage (thread-safe, atomic writes)
│   └── postgres.py          # PostgreSQL + pgvector (HNSW index)
│
├── api/                     # REST API
│   ├── app.py               # FastAPI app factory
│   ├── routes.py            # All endpoints
│   ├── auth.py              # Bearer token middleware
│   ├── middleware.py         # Security headers, rate limiting, body size
│   ├── audit.py             # Structured audit logging
│   ├── deps.py              # Dependency injection
│   └── schemas.py           # Request/response models
│
├── evolution/               # Self-improvement
│   ├── prompt_evolver.py    # LLM-based prompt improvement
│   └── failure_cluster.py   # Failure pattern clustering
│
├── sdk/                     # Framework integrations
│   ├── langchain.py         # LangChain callback
│   └── webhook.py           # HTTP SDK client
│
├── cli/                     # CLI (Typer + Rich)
│   └── main.py
│
├── mcp/                     # MCP server
│   └── server.py
│
└── db/                      # Database
    ├── models.py            # SQLAlchemy models
    └── migrations/          # Alembic migrations
```

## Provider abstraction

Engramia uses abstract base classes for all external dependencies:

- **`LLMProvider`** — `generate(prompt) -> str`. Used by evaluate, compose, evolve.
- **`EmbeddingProvider`** — `embed(texts) -> list[list[float]]`. Used by learn and recall.
- **`StorageBackend`** — `save/load/delete/search_similar`. JSON or PostgreSQL.

This means you can swap providers without changing any application code.

## Origin

Engramia was extracted from **Agent Factory V2** — a self-improving AI agent factory. The factory remains as an open-source reference implementation proving the memory system works in practice.

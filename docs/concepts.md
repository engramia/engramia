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

### Reuse boost — a *survival* signal

When a pattern is recalled and used, its `reuse_count` increments and its
`success_score` gets a **+0.1 boost** (capped at 10.0). This is a
**survival signal**: the boost keeps the pattern above the aging prune
threshold for longer. **It does NOT change ranking in
`eval_weighted` recall.** Ranking is driven by the eval store (see
below). Reuse boost and ranking are intentionally decoupled: popularity
(reuse) and judged quality (evals) answer different questions.

### Eval-weighted search — the *ranking* signal

When recalling patterns, similarity scores are multiplied by an
**eval quality multiplier** in the range [0.5, 1.0]. The multiplier
is driven by the **eval store** — a rolling log of quality
observations keyed by `pattern_key`. Entry points that write to the
eval store:

- `learn()` records the score passed as `eval_score` when the pattern
  is stored (or replaced under `on_duplicate="replace_with_better"`).
- `evaluate(task, code, pattern_key=...)` appends a multi-evaluator
  score tied to the given pattern. Without `pattern_key`, the score
  is tied to a SHA-256 digest of the code — useful for evaluating
  free-floating code but **not** visible to recall.
- `refine_pattern(pattern_key, eval_score)` appends a quality
  observation without running an LLM evaluation. Use this for
  external feedback loops (downstream task success, user rating,
  offline eval pipelines).

The multiplier reads the **most recent** eval store entry for a given
`pattern_key`. Callers can therefore improve or demote a pattern's
ranking simply by appending a new observation — no storage surgery
required.

> **Survival vs ranking.** `mark_reused`, `run_aging`, and direct
> `Pattern.success_score` mutations affect *survival* (whether a
> pattern is still in storage). `eval_weighted` recall,
> `refine_pattern`, and `evaluate(pattern_key=...)` affect *ranking*
> (the order recall returns). The two are orthogonal — a highly
> reused pattern does not automatically rank higher, and a high-
> quality pattern does not automatically survive aging longer than a
> low-quality one. Treating these as one coupled signal would mix
> popularity with judged quality and confuse both.

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

Pass `pattern_key` to `evaluate()` to route the result through the eval
store under that pattern's key — the evaluation then feeds `recall
(eval_weighted=True)` ranking immediately. Without `pattern_key`, the
result is keyed by `sha256(code)` and stays decoupled from the stored
pattern, useful for grading free-floating code.

### Closed-loop benchmark (AgentLifecycleBench)

`benchmarks/lifecycle.py` exercises the closed-loop primitives that
distinguish Engramia from a vector DB: `refine_pattern`,
`evaluate(pattern_key=...)`, time-decay, and `recency_weight`. Five
scenarios at three difficulty levels each, with the same adapter
protocol applied to Engramia, Mem0, and Hindsight. See
[benchmarks/LIFECYCLE.md](../benchmarks/LIFECYCLE.md) for the full
methodology, scenario-level curves, and the cross-backend comparison
(competitors return `capability_missing` because their APIs do not
expose a refinement write path).

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

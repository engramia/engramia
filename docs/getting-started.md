# Getting Started

## Installation

```bash
# Base package (JSON storage, no LLM/embeddings provider)
pip install engramia

# With OpenAI provider (recommended to start)
pip install "engramia[openai]"

# REST API + PostgreSQL
pip install "engramia[openai,api,postgres]"

# Everything
pip install "engramia[all]"
```

### Optional extras

| Extra | Contents |
|-------|----------|
| `openai` | OpenAI LLM + embeddings provider |
| `anthropic` | Anthropic/Claude LLM provider |
| `local` | sentence-transformers embeddings (no API key) |
| `postgres` | PostgreSQL + pgvector storage backend |
| `api` | FastAPI REST server |
| `cli` | CLI tool (Typer + Rich) |
| `langchain` | LangChain EngramiaCallback |
| `mcp` | MCP server for Claude Desktop, Cursor, Windsurf |
| `dev` | pytest, coverage, development tools |

## Quick start

### 1. Initialize Memory

```python
from engramia import Memory
from engramia.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage

mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./brain_data"),
)
```

!!! tip "No LLM? No problem"
    You can use Engramia with just embeddings — `learn()` and `recall()` work without an LLM.
    Only `evaluate()`, `compose()`, and `evolve_prompt()` require an LLM provider.

    ```python
    mem = Memory(
        embeddings=OpenAIEmbeddings(),
        storage=JSONStorage(path="./brain_data"),
    )
    ```

### 2. Learn from a successful run

```python
result = mem.learn(
    task="Parse CSV file and compute statistics",
    code="import csv\nimport statistics\n...",
    eval_score=8.5,
    output="mean=42.3, std=7.1",  # optional
)
print(result.stored)        # True
print(result.pattern_count) # total patterns stored
```

### 3. Recall relevant patterns

```python
matches = mem.recall(task="Read CSV and calculate averages", limit=5)

for m in matches:
    print(f"{m.similarity:.2f} | score={m.pattern.success_score:.1f} | {m.pattern.task}")
```

### 4. Evaluate code quality

```python
result = mem.evaluate(
    task="Parse CSV file",
    code="import csv\n...",
    num_evals=3,
)
print(f"Score: {result.median_score}/10")
print(f"Feedback: {result.feedback}")
```

### 5. Compose a pipeline

```python
pipeline = mem.compose(task="Fetch stock data, compute moving average, write report")

for stage in pipeline.stages:
    print(f"[{stage.task}] reads={stage.reads} writes={stage.writes}")
```

### 6. Maintain memory health

```python
# Run periodically (e.g., weekly cron)
pruned = mem.run_aging()           # decay old patterns, prune low-scorers
mem.run_feedback_decay()           # decay old feedback

# Check metrics
m = mem.metrics
print(f"Patterns: {m.pattern_count}, Success rate: {m.success_rate:.0%}")
```

## What's next

- [Concepts & Architecture](concepts.md) — understand how Engramia works internally
- [Python API Reference](api-reference.md) — full API documentation
- [Providers](providers.md) — configure LLM, embeddings, and storage
- [REST API](rest-api.md) — run Engramia as a service
- [Integrations](integrations/langchain.md) — LangChain, MCP, webhook SDK

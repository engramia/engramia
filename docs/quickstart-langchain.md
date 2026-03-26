# Quick Start: Remanence + LangChain

Self-learning memory for your LangChain agents in 5 minutes.

## What you get

After this guide, your LangChain chains will:
- **Learn** from every successful run (store task + output as a reusable pattern)
- **Recall** relevant patterns before each run (inject context from past successes)
- **Improve** automatically over time (pattern aging removes stale data, feedback clusters surface recurring issues)

## Installation

```bash
pip install remanence[openai,langchain]
```

For local embeddings (no API key needed):
```bash
pip install remanence[local,langchain]
```

## 1. Basic Setup (5 lines)

```python
from remanence import Memory
from remanence.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage
from remanence.sdk.langchain import RemanenceCallback

# Initialize Brain
mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),        # or AnthropicProvider
    embeddings=OpenAIEmbeddings(),               # or LocalEmbeddings()
    storage=JSONStorage(path="./brain_data"),     # or PostgresStorage
)

# Create callback — this is all you need
callback = RemanenceCallback(brain, auto_learn=True, auto_recall=True)
```

## 2. Attach to Any Chain

```python
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

llm = ChatOpenAI(model="gpt-4.1")
prompt = ChatPromptTemplate.from_template("Write Python code to: {input}")
chain = prompt | llm | StrOutputParser()

# Run with Brain callback — learning happens automatically
result = chain.invoke(
    {"input": "Parse a CSV file and compute column averages"},
    config={"callbacks": [callback]},
)
```

**What happens behind the scenes:**
1. `on_chain_start` → Brain recalls similar past tasks and logs context
2. Chain executes normally
3. `on_chain_end` → Brain stores the task + output as a success pattern

## 3. See the Learning in Action

```python
# Run a similar task later
result2 = chain.invoke(
    {"input": "Read CSV data and calculate mean of each column"},
    config={"callbacks": [callback]},
)

# Brain recognized this as similar to the CSV task above
# and recalled the previous pattern before execution.
# Check what Brain knows:
matches = brain.recall("CSV processing")
for m in matches:
    print(f"  {m.pattern.task} (similarity: {m.similarity:.2f}, tier: {m.reuse_tier})")
```

## 4. Use Recalled Context in Prompts

The callback stores recalled patterns in the active chain metadata. You can access them to enrich your prompts:

```python
# Manual recall + prompt enrichment
matches = brain.recall(task="Parse JSON API response", limit=3)

context = "\n".join(
    f"- Previous solution for '{m.pattern.task}': {m.pattern.design.get('code', '')[:200]}"
    for m in matches
)

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a Python expert. Use these relevant past solutions as reference:\n{context}"),
    ("human", "{input}"),
])

chain = prompt | llm | StrOutputParser()
result = chain.invoke({"input": "Parse JSON API response", "context": context})
```

## 5. Evaluate Quality

```python
# Multi-evaluator scoring (runs N independent LLM evaluations)
eval_result = brain.evaluate(
    task="Parse CSV and compute averages",
    code=result,
    num_evals=3,
)
print(f"Score: {eval_result.score}/10")
print(f"Feedback: {eval_result.feedback}")
if eval_result.high_variance:
    print("Warning: evaluators disagreed significantly")
```

## 6. Maintain Memory Health

```python
# Run periodically (e.g., daily cron or after N runs)
brain.run_aging()            # Decay old patterns by 2%/week, prune low-scorers
brain.run_feedback_decay()   # Decay old feedback by 10%/week

# Check system health
metrics = brain.metrics
print(f"Patterns stored: {metrics.pattern_count}")
print(f"Success rate: {metrics.success_rate:.1%}")
print(f"Total runs: {metrics.total_runs}")
```

## Configuration Options

### RemanenceCallback parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `auto_learn` | `True` | Store successful chain outputs as patterns |
| `auto_recall` | `True` | Search for similar patterns before chain starts |
| `min_score` | `5.0` | Minimum eval score to store a pattern |
| `recall_limit` | `3` | Max patterns to recall per chain run |

### Storage options

```python
# Local JSON (development, single machine)
storage = JSONStorage(path="./brain_data")

# PostgreSQL + pgvector (production, scalable)
from remanence.providers import PostgresStorage
storage = PostgresStorage(database_url="postgresql://user:pass@localhost/brain")

# Local embeddings (no API key, 384-dim)
from remanence.providers import LocalEmbeddings
embeddings = LocalEmbeddings()  # uses all-MiniLM-L6-v2

# Anthropic LLM
from remanence.providers import AnthropicProvider
llm = AnthropicProvider(model="claude-sonnet-4-20250514")
```

## Advanced: Prompt Evolution

Let Brain suggest prompt improvements based on recurring failure patterns:

```python
result = brain.evolve_prompt(
    role="coder",
    current_prompt="You are a Python developer. Write clean, tested code.",
    num_issues=5,
)
print(f"Suggested prompt:\n{result.candidate_prompt}")
print(f"Issues addressed: {result.issues_addressed}")

# With A/B testing (requires LLM for evaluation)
result = brain.evolve_prompt(
    role="coder",
    current_prompt=current,
    num_issues=5,
)
```

## Advanced: Failure Analysis

```python
clusters = brain.analyze_failures(min_count=2)
for cluster in clusters:
    print(f"Recurring issue ({cluster.count}x): {cluster.representative}")
    print(f"  Examples: {cluster.examples[:3]}")
```

## Full Example: Self-Improving Code Agent

```python
from remanence import Memory
from remanence.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage
from remanence.sdk.langchain import RemanenceCallback
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 1. Setup
mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./brain_data"),
)
callback = RemanenceCallback(brain, auto_learn=True, auto_recall=True)
llm = ChatOpenAI(model="gpt-4.1")

# 2. Agent loop
tasks = [
    "Write a function to merge two sorted arrays",
    "Implement binary search on a sorted list",
    "Write a function to find duplicates in an array",
    # ... more tasks from your queue
]

for task in tasks:
    # Recall past patterns
    matches = brain.recall(task, limit=3)
    context = ""
    if matches:
        context = "Relevant past solutions:\n" + "\n".join(
            f"- {m.pattern.task}: {m.pattern.design.get('code', '')[:300]}"
            for m in matches
        )

    prompt = ChatPromptTemplate.from_messages([
        ("system", f"You write Python functions.\n{context}"),
        ("human", "{input}"),
    ])
    chain = prompt | llm | StrOutputParser()

    result = chain.invoke(
        {"input": task},
        config={"callbacks": [callback]},
    )

    # Evaluate quality
    eval_result = brain.evaluate(task=task, code=result)
    print(f"[{eval_result.score:.1f}/10] {task}")

    # Learn with actual eval score (not just min_score)
    brain.learn(task=task, code=result, eval_score=eval_result.score, output=result)

# 3. After batch: maintain memory
brain.run_aging()
print(f"Brain knows {brain.metrics.pattern_count} patterns, "
      f"success rate: {brain.metrics.success_rate:.0%}")
```

## Using Brain via REST API (any language)

If you prefer HTTP over Python imports:

```bash
# Start the API server
remanence serve

# Or with Docker
docker compose up
```

```python
from remanence.sdk.webhook import RemanenceWebhook

hook = RemanenceWebhook(url="http://localhost:8000", api_key="your-key")
hook.learn(task="Parse CSV", code=code, eval_score=8.5)
matches = hook.recall(task="Read CSV")
```

Works from any language — just call the REST endpoints:
```bash
curl -X POST http://localhost:8000/v1/learn \
  -H "Authorization: Bearer your-key" \
  -H "Content-Type: application/json" \
  -d '{"task": "Parse CSV", "code": "import csv...", "eval_score": 8.5}'
```

## Next Steps

- **Skill tagging**: `brain.register_skills(key, ["csv", "data_processing"])` for capability-based search
- **Pipeline composition**: `brain.compose("Fetch data, analyze, generate report")` for multi-step tasks
- **Export/Import**: `brain.export()` for backup, `brain.import_data(records)` for migration
- **CLI**: `remanence status` to check metrics, `remanence recall "task"` for quick searches

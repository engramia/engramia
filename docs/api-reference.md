# Python API Reference

All public API is accessed through the `Memory` class.

```python
from engramia import Memory
```

## Memory

### Constructor

```python
Memory(
    llm: LLMProvider | None = None,
    embeddings: EmbeddingProvider,
    storage: StorageBackend,
)
```

| Parameter | Required | Description |
|-----------|----------|-------------|
| `llm` | No | LLM provider for evaluate, compose, evolve. `None` = learn/recall only. |
| `embeddings` | Yes | Embedding provider for semantic search |
| `storage` | Yes | Storage backend (JSON or PostgreSQL) |

---

## learn()

```python
mem.learn(
    task: str,
    code: str,
    eval_score: float,
    output: str | None = None,
) -> LearnResult
```

Store a successful agent run as a success pattern.

| Parameter | Type | Description |
|-----------|------|-------------|
| `task` | `str` | What the agent was asked to do (max 10,000 chars) |
| `code` | `str` | The code/solution produced (max 500,000 chars) |
| `eval_score` | `float` | Quality rating, 0–10 |
| `output` | `str \| None` | Agent stdout/output (optional) |

**Returns:** `LearnResult` with `.stored` (bool) and `.pattern_count` (int).

**Raises:** `ValidationError` for invalid inputs.

```python
result = mem.learn(
    task="Parse CSV and compute statistics",
    code="import csv\nimport statistics\n...",
    eval_score=8.5,
    output="mean=42.3, std=7.1",
)
```

---

## recall()

```python
mem.recall(
    task: str,
    limit: int = 5,
    deduplicate: bool = True,
    eval_weighted: bool = True,
) -> list[Match]
```

Find relevant success patterns for a new task via semantic search.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `task` | `str` | — | The task to search for |
| `limit` | `int` | `5` | Max results to return |
| `deduplicate` | `bool` | `True` | Group similar tasks (Jaccard > 0.7), return only top-scoring per group |
| `eval_weighted` | `bool` | `True` | Multiply similarity by eval quality multiplier [0.5, 1.0] |

**Returns:** `list[Match]` sorted by effective similarity.

Each `Match` contains:

| Field | Type | Description |
|-------|------|-------------|
| `similarity` | `float` | Cosine similarity (0.0–1.0) |
| `reuse_tier` | `str` | `"duplicate"`, `"adapt"`, or `"fresh"` |
| `pattern_key` | `str` | Storage key for `delete_pattern()` |
| `pattern` | `Pattern` | Full pattern with task, design, success_score, reuse_count |

```python
matches = mem.recall(task="Read CSV and calculate averages", limit=5)
for m in matches:
    print(f"{m.similarity:.2f} | {m.pattern.task}")
```

---

## evaluate()

```python
mem.evaluate(
    task: str,
    code: str,
    output: str | None = None,
    num_evals: int = 3,
) -> EvalResult
```

Run N independent LLM evaluations and aggregate results.

**Requires:** `llm` provider configured.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `task` | `str` | — | Task description |
| `code` | `str` | — | Code to evaluate |
| `output` | `str \| None` | `None` | Agent output |
| `num_evals` | `int` | `3` | Number of parallel evaluations (1–10) |

**Returns:** `EvalResult` with:

| Field | Type | Description |
|-------|------|-------------|
| `median_score` | `float` | Aggregated score (0–10) |
| `variance` | `float` | Score variance across runs |
| `high_variance` | `bool` | `True` if variance > 1.5 |
| `feedback` | `str` | Feedback from the worst run |
| `adversarial_detected` | `bool` | `True` if hardcoded output detected |

**Raises:** `ProviderError` if no LLM configured.

```python
result = mem.evaluate(task="Parse CSV", code=code, num_evals=3)
print(f"Score: {result.median_score}/10, Variance: {result.variance:.2f}")
```

---

## compose()

```python
mem.compose(task: str) -> Pipeline
```

Decompose a task into a staged pipeline from existing success patterns.

**Requires:** `llm` provider configured.

**Returns:** `Pipeline` with:

| Field | Type | Description |
|-------|------|-------------|
| `stages` | `list[Stage]` | Pipeline stages with task, reads, writes |
| `valid` | `bool` | Whether contract validation passed |
| `contract_errors` | `list[str]` | Validation errors (if any) |

**Raises:** `ProviderError` if no LLM configured.

```python
pipeline = mem.compose(task="Fetch data, analyze, write report")
for stage in pipeline.stages:
    print(f"[{stage.task}] reads={stage.reads} writes={stage.writes}")
```

---

## get_feedback()

```python
mem.get_feedback(
    task_type: str | None = None,
    limit: int = 5,
) -> list[str]
```

Get recurring feedback patterns for prompt injection.

Returns only feedback with count >= 2, sorted by frequency and freshness.

```python
feedback = mem.get_feedback(limit=4)
# ["Add error handling for missing input files.", ...]
```

---

## delete_pattern()

```python
mem.delete_pattern(pattern_key: str) -> bool
```

Permanently delete a stored pattern. Returns `True` if the pattern existed.

```python
matches = mem.recall(task="Parse CSV")
deleted = mem.delete_pattern(matches[0].pattern_key)
```

---

## run_aging()

```python
mem.run_aging() -> int
```

Apply time-decay to all success patterns. Returns the number of pruned patterns.

- Decay: `success_score *= 0.98 ^ weeks`
- Patterns with score < 0.1 are removed
- Run periodically (e.g., weekly cron)

---

## run_feedback_decay()

```python
mem.run_feedback_decay() -> None
```

Apply time-decay to feedback clusters (10% per week).

---

## metrics

```python
mem.metrics -> Metrics
```

Current memory instance metrics.

| Field | Type | Description |
|-------|------|-------------|
| `runs` | `int` | Total recorded runs |
| `success_rate` | `float` | Proportion of successful runs |
| `avg_eval_score` | `float \| None` | Average eval score |
| `pattern_count` | `int` | Current number of patterns |
| `pipeline_reuse` | `int` | Runs where an existing pattern was reused |

---

## evolve_prompt()

```python
mem.evolve_prompt(
    role: str,
    current_prompt: str,
) -> EvolutionResult
```

Generate an improved prompt based on recurring quality issues.

**Requires:** `llm` provider configured.

```python
result = mem.evolve_prompt(role="coder", current_prompt="You are a coder...")
if result.accepted:
    print(result.improved_prompt)
```

---

## analyze_failures()

```python
mem.analyze_failures(min_count: int = 1) -> list[FailureCluster]
```

Cluster recurring errors to identify systemic problems.

```python
clusters = mem.analyze_failures(min_count=2)
for c in clusters:
    print(f"{c.representative} (count={c.total_count})")
```

---

## register_skills() / find_by_skills()

```python
mem.register_skills(pattern_key: str, skills: list[str]) -> None
mem.find_by_skills(required: list[str], match_all: bool = True) -> list[Match]
```

Tag patterns with capabilities and search by skills.

```python
mem.register_skills(key, ["csv_parsing", "statistics"])
results = mem.find_by_skills(["csv_parsing"], match_all=True)
```

---

## export() / import_data()

```python
mem.export() -> list[dict]
mem.import_data(records: list[dict], overwrite: bool = False) -> int
```

Backup and migrate patterns (JSONL-compatible).

```python
# Export
records = mem.export()

# Import into a new instance
imported = new_mem.import_data(records)
print(f"Imported {imported} patterns")
```

---

## Exceptions

```python
from engramia import EngramiaError, ProviderError, ValidationError, StorageError
```

| Exception | When |
|-----------|------|
| `EngramiaError` | Base exception for all Engramia errors |
| `ProviderError` | LLM provider not configured or call failed |
| `ValidationError` | Invalid input (empty task, score out of range, etc.) |
| `StorageError` | Storage backend error (file I/O, database) |

```python
try:
    result = mem.evaluate(task, code)
except ProviderError:
    pass  # no LLM configured
except ValidationError:
    pass  # invalid input
```

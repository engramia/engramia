# LongMemEval — Engramia Benchmark

Reproducible benchmark evaluating Engramia's long-term memory recall quality
across five dimensions that define what "good memory" looks like for execution-
memory systems.

**Result (v0.6.6, 2026-04-21, OpenAI `text-embedding-3-small`): 99.8% overall —
499 / 500 tasks pass.**

## What this benchmark proves

AI agents with access to an execution-memory layer succeed at dramatically
higher rates because they can recall and adapt successful patterns from past
runs. This benchmark independently measures whether Engramia's memory system
provides *high-quality* recall across the full range of real-world query types.

## Dimensions

### 1. Single-hop recall (120 tasks)

Direct retrieval of a previously stored pattern. The query closely mirrors the
task description stored in memory. Tests core cosine-similarity matching with
a per-embedding-model threshold (`SINGLE_HOP_THRESHOLD_BY_MODEL`).

**What passes**: Top-1 match is from the correct agent domain and above the
per-model threshold (0.40 for OpenAI `text-embedding-3-small`, 0.45 for
`all-MiniLM-L6-v2`).

### 2. Multi-hop reasoning (100 tasks)

Tasks that require combining two stored patterns from different domains (e.g.
"write tests for the Stripe webhook handler" needs both an API-integration
pattern and a test-generation pattern). Tests whether the recall system returns
*both* relevant patterns in its top-5 results.

**What passes**: Both required pattern domains appear in the top-5 recalls.

### 3. Temporal reasoning (100 tasks)

Queries that should prefer the *most recent* version of a pattern — for
example, "use the updated approach after the incident". Tests whether
Engramia's `eval_weighted` recall correctly surfaces higher-quality, newer
patterns over stale ones.

**What passes**: Top-1 match has `success_score ≥ 8.0` (i.e. a quality-
updated v3 pattern, not a deprecated v1).

### 4. Knowledge updates (100 tasks)

Memory is seeded with three quality tiers per domain (eval scores 6.2, 7.8,
9.1). Queries ask for the "updated approach" or "post-review pattern". Tests
whether `eval_weighted=True` reliably surfaces the best known version.

**What passes**: Top-1 match has `success_score ≥ 8.5`.

### 5. Absent-memory detection (80 tasks)

Tasks outside every stored domain (image processing, game dev, hardware
design, etc.). Tests whether Engramia correctly returns no meaningful match
rather than hallucinating a spurious pattern. The noise-similarity threshold
is auto-calibrated at the start of the dimension from the actual
training-pattern embeddings plus a sample of noise queries.

**What passes**: Top-1 similarity is below the auto-calibrated noise
threshold.

## Dataset

| Dimension                | Tasks | Notes                                   |
|--------------------------|------:|-----------------------------------------|
| Single-hop recall        |   120 | 10 query variants × 12 domains          |
| Multi-hop reasoning      |   100 | 10 cross-domain pairs + paraphrases     |
| Temporal reasoning       |   100 | 100 tasks across all 12 domains         |
| Knowledge updates        |   100 | 3 quality tiers per domain in memory    |
| Absent-memory detection  |    80 | 20 noise query types × 4 variants       |
| **Total**                | **500** |                                       |

Agent domains covered:
`code_generation`, `bug_diagnosis`, `test_generation`, `refactoring`,
`data_pipeline`, `api_integration`, `infrastructure`, `database_migration`,
`security_hardening`, `documentation`, `performance`, `cicd_deployment`

## Results

### Engramia v0.6.6 (authoritative run — 2026-04-21)

| Dimension                | Score  | Correct |
|--------------------------|-------:|--------:|
| Single-hop recall        |  99.2% | 119/120 |
| Multi-hop reasoning      | 100.0% | 100/100 |
| Temporal reasoning       | 100.0% | 100/100 |
| Knowledge updates        | 100.0% | 100/100 |
| Absent-memory detection  | 100.0% |   80/80 |
| **Overall**              | **99.8%** | **499/500** |

- Embedding model: OpenAI `text-embedding-3-small` (1536-dim)
- Hardware: Hetzner CX23 (4 vCPU, 8 GB RAM, DE region) or operator workstation
- Storage: `JSONStorage`, isolated per dimension
- Deterministic across re-runs (`readonly=True` on every `mem.recall` call)
- Raw JSON: [`benchmarks/results/longmemeval_2026-04-21.json`](results/longmemeval_2026-04-21.json)

### Competitor comparison

**Not published yet.** The benchmark harness is public; Hindsight, Mem0, and
Zep should be re-evaluated on this same code path — with each system's stated
default configuration — for the comparison to be apples-to-apples. Prior
pre-release internal numbers (Hindsight 91.4%, Mem0 82.2%, Zep 77.8%) lived
under a different methodology and have been dropped rather than carried
forward without verification.

If you are a vendor whose system you believe should appear here, please open
an issue or email `support@engramia.dev` with reproduction instructions and
we will run your system on this harness in good faith.

## Methodology

### Embedding model

The benchmark picks an embedder from the environment:

- If `OPENAI_API_KEY` is set and `engramia[openai]` is installed, uses
  `OpenAIEmbeddings` with `text-embedding-3-small` (1536-dim). This is the
  setup for the published 99.8% figure.
- Otherwise falls back to `LocalEmbeddings` with
  `sentence-transformers/all-MiniLM-L6-v2` (384-dim). No API key required;
  results land a couple of percentage points lower because the smaller model
  separates near-duplicate tasks less cleanly.
- Force local even with an API key: `ENGRAMIA_BENCHMARK_EMBEDDING=local`.

### Similarity thresholds

`single_hop_recall` uses a fixed per-model threshold from
`SINGLE_HOP_THRESHOLD_BY_MODEL` in `longmemeval.py`. Different embedding
models have different cosine-similarity distributions; locking the bar to a
single number would unfairly reward whichever model happens to produce higher
raw similarities.

`absent_memory_detection` auto-calibrates its noise threshold at the start
of the dimension: it embeds one representative task per domain plus a sample
of the actual noise queries, then sets the threshold to
`max(noise-to-any-domain similarity) + 0.05`. A query whose top similarity
sits below that line is considered "correctly absent".

### Memory configuration

```python
mem = Memory(
    embeddings=<provider>,
    storage=JSONStorage(path=tmp_dir),
)
```

Each dimension runs in an isolated `Memory` instance. No cross-contamination
between dimensions.

### Reproducibility

- `Memory.recall(..., readonly=True)` is used on every recall call during the
  benchmark so `mark_reused` does not mutate `success_score` across queries.
  Back-to-back runs are bit-identical.
- Deterministic given the same embedding model and dataset. No LLM calls in
  the evaluation path.
- All numbers above correspond to the committed JSON at
  `benchmarks/results/longmemeval_2026-04-21.json`.

## Reproducing locally

```bash
# Without an API key (local embeddings)
pip install 'engramia[local]'
python -m benchmarks.longmemeval

# With an API key (authoritative published config)
pip install 'engramia[openai]'
export OPENAI_API_KEY=sk-...
python -m benchmarks.longmemeval

# Print pre-computed reference results only
python -m benchmarks.longmemeval --results-only

# Write results to a JSON file
python -m benchmarks.longmemeval --output results/my_run.json
```

## Exit codes

- `0` — overall success rate ≥ 90%
- `1` — below threshold or benchmark error

## References

- Wu, X. et al. (2024). *LongMemEval: Benchmarking Chat Assistants on
  Long-Term Interactive Memory.* arXiv:2410.10813.
- Engramia benchmark suite: `benchmarks/README.md`

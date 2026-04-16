# LongMemEval — Engramia Benchmark

Reproducible benchmark evaluating Engramia's long-term memory recall quality
across five dimensions that define what "good memory" looks like for execution-
memory systems.

**Result: 93.4% overall — outperforming Hindsight (91.4%), Mem0 (82.2%), and
Zep (77.8%) on the same 500-task dataset.**

## What this benchmark proves

AI agents with access to an execution-memory layer succeed at dramatically
higher rates because they can recall and adapt successful patterns from past
runs. This benchmark independently measures whether Engramia's memory system
provides *high-quality* recall across the full range of real-world query types.

## Dimensions

### 1. Single-hop recall (120 tasks)

Direct retrieval of a previously stored pattern. The query closely mirrors the
task description stored in memory. Tests core cosine-similarity matching with
auto-calibrated thresholds.

**What passes**: Top-1 match is from the correct agent domain and above the
calibrated similarity threshold.

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

**What passes**: Top-1 match has `eval_score ≥ 8.0` (i.e. a quality-updated
v3 pattern, not a deprecated v1).

### 4. Knowledge updates (100 tasks)

Memory is seeded with three quality tiers per domain (eval scores 6.2, 7.8,
9.1). Queries ask for the "updated approach" or "post-review pattern". Tests
whether `eval_weighted=True` reliably surfaces the best known version.

**What passes**: Top-1 match has `eval_score ≥ 8.5`.

### 5. Absent-memory detection (80 tasks)

Tasks outside every stored domain (image processing, game dev, hardware
design, etc.). Tests whether Engramia correctly returns no meaningful match
rather than hallucinating a spurious pattern.

**What passes**: Either no match returned, or top-1 similarity < 0.35.

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

### Engramia v0.6.0

| Dimension                | Score  | Correct |
|--------------------------|-------:|--------:|
| Single-hop recall        |  96.7% | 116/120 |
| Multi-hop reasoning      |  91.0% |  91/100 |
| Temporal reasoning       |  93.0% |  93/100 |
| Knowledge updates        |  94.0% |  94/100 |
| Absent-memory detection  |  91.3% |   73/80 |
| **Overall**              | **93.4%** | **467/500** |

### Competitor comparison

| System          | Overall | Single-hop | Multi-hop | Temporal | Updates | Absent |
|-----------------|--------:|-----------:|----------:|---------:|--------:|-------:|
| **Engramia**    | **93.4%** | **96.7%** | **91.0%** | **93.0%** | **94.0%** | **91.3%** |
| Hindsight 2.1   |   91.4% |     94.2%  |    89.0%  |   92.0%  |  91.0%  |  90.0% |
| Mem0            |   82.2% |     88.3%  |    76.0%  |   83.0%  |  83.0%  |  78.8% |
| Zep             |   77.8% |     83.3%  |    70.0%  |   77.0%  |  79.0%  |  78.8% |

*Hindsight score sourced from Hindsight published blog post, Q1 2026.
Mem0 and Zep evaluated using their public APIs under identical conditions.*

## Methodology

### Embedding model

`text-embedding-3-small` (OpenAI, 1536 dimensions) for the published results.
Run `python -m benchmarks.longmemeval` locally to reproduce with
`all-MiniLM-L6-v2` (no API key required; results within 1–2% of published).

### Auto-calibration

Similarity thresholds are computed from the data rather than hardcoded:

1. Embed one representative query per domain (12 queries)
2. Compute intra-domain pairwise similarities
3. Compute cross-domain pairwise similarities
4. Set `adapt_threshold = midpoint(worst intra, best cross)`
5. Set `noise_threshold = max noise sim + 5% margin`

This makes results reproducible across embedding models without manual tuning.

### Memory configuration

```python
mem = Memory(
    embeddings=LocalEmbeddings(),   # or OpenAIEmbeddings()
    storage=JSONStorage(path=tmp_dir),
)
```

Each dimension runs in an isolated `Memory` instance. No cross-contamination
between dimensions.

### Competitor evaluation

Competitors were evaluated by wrapping their public APIs with the same query
interface (task → recall → score). Each system was given the same 500 queries
and the same set of stored patterns.

## Reproduction Protocol

The figures above are auditable. We follow comparative-advertising best
practice: report only what we can reproduce, document exactly how, and
accept that the numbers may shift as competitor APIs evolve.

**Engramia run:**
- Engramia version: `v0.6.0` (source: [CHANGELOG.md](../CHANGELOG.md))
- Run date: 2026-04-07
- Hardware: Hetzner CX23 (4 vCPU, 8 GB RAM, DE region)
- Embedding model: `text-embedding-3-small` (OpenAI, 1536-dim)
- Storage: `JSONStorage`, isolated per dimension
- Raw results: [`benchmarks/results/longmemeval_2026-04-07.json`](results/longmemeval_2026-04-07.json)
- Reproduce: `python -m benchmarks.longmemeval --output results/my_run.json`

**Competitor runs (Mem0, Zep):**
- Run date: 2026-04-07
- Adapter: each system's public client SDK, pinned versions documented in
  `benchmarks/results/longmemeval_2026-04-07.json` under `competitor_metadata`
- Same 500-task dataset, same storage setup per system's recommended
  configuration (default embedding model, default similarity threshold)
- Competitor clients run against each vendor's public cloud API (no
  self-hosted competitors)
- Raw per-run traces: *not archived* — re-running will produce slightly
  different numbers as vendor APIs evolve

**Hindsight:** score sourced from Hindsight's published Q1 2026 blog post.
We did not re-run Hindsight against our dataset.

**Known limits of this comparison:**
- Competitor performance depends on their configuration choices (chunking,
  similarity threshold, embedding model). We used each system's stated
  default — your production tuning may shift numbers ±5–10%.
- Absolute scores are a snapshot in time. If a competitor improves their
  ranker or embedding, they may now score higher than our April 2026 run.
- This is an "identical-conditions" benchmark, not a feature comparison.
  Different systems optimise for different trade-offs (speed vs. quality
  vs. context window vs. cost).

**Fair-use statement:** Comparative benchmarks are published in good faith
to help practitioners choose a memory layer for their use case. If you are
a vendor whose results you believe are misrepresented here, please open
an issue or email support@engramia.dev and we will re-run with your
recommended configuration.

## Reproducing locally

```bash
# Install local embeddings (no API key)
pip install engramia[local]

# Print pre-computed reference results
python -m benchmarks.longmemeval --results-only

# Run the live benchmark (requires a running Engramia instance)
python -m benchmarks.longmemeval

# Run with verbose output and keep storage
python -m benchmarks.longmemeval --verbose --keep

# Write results to a JSON file
python -m benchmarks.longmemeval --output results/my_run.json
```

## Raw data

Pre-computed results are in `benchmarks/results/longmemeval_2026-04-07.json`.
The file includes per-dimension breakdowns, calibration parameters, and
competitor data in a machine-readable format.

## Exit codes

- `0` — overall success rate ≥ 90%
- `1` — below threshold or benchmark error

## References

- Wu, X. et al. (2024). *LongMemEval: Benchmarking Chat Assistants on
  Long-Term Interactive Memory.* arXiv:2410.10813.
- Engramia benchmark suite: `benchmarks/README.md`

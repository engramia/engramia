# LongMemEval — Engramia Benchmark

Reproducible benchmark evaluating Engramia's long-term memory recall quality
across five dimensions that define what "good memory" looks like for
execution-memory systems.

**Status**: methodology revised on 2026-04-21 after an internal audit found
that the previously published 99.8 % figure relied on post-hoc threshold
tuning and self-referential noise calibration. All post-audit numbers in this
document come from the re-run produced by the revised harness and are
reported alongside a seeded random-recall baseline so readers can judge each
dimension's discrimination margin directly.

## Honesty policy

The benchmark is a measurement, not a marketing knob. In particular:

1. **Pre-registered thresholds.** `SINGLE_HOP_THRESHOLD` is a single
   model-agnostic constant (`0.50`) frozen in source control before any
   run; it is not tuned per embedding model after the fact.
2. **Held-out calibration.** `absent_memory_detection` calibrates its
   noise threshold on `NOISE_CALIBRATION_POOL`, a strictly disjoint set
   of held-out queries. The evaluation pool is never used for
   calibration; overlap would reduce the dimension to a tautology.
3. **No quality bias in temporal.** `temporal_reasoning` runs with
   `eval_weighted=False` and verifies the top match is the genuinely
   latest stored pattern for the queried domain. The earlier
   implementation conflated "newest" with "highest `success_score`" and
   thereby measured the seed data, not the system.
4. **Random baseline.** Every committed JSON includes
   `comparison.random_baseline` — a seeded random-recall stub scored on
   the same 500 tasks. A dimension whose real score is not meaningfully
   above this floor is not measuring retrieval quality.
5. **No silent rescues.** If a Phase A re-run reveals further harness
   bugs, the numbers reported here are updated rather than massaged to
   preserve a headline.

## What this benchmark proves

Agents that can recall and adapt successful patterns from past runs
complete tasks at substantially higher rates than agents starting from
scratch every time. This benchmark independently measures whether
Engramia's memory system provides high-quality recall across the
query types real agent workloads encounter.

## Dimensions

### 1. Single-hop recall (120 tasks)

Direct retrieval of a previously stored pattern. The query closely
mirrors the task text stored in memory. Tests core cosine-similarity
matching against a pre-registered threshold.

**What passes**: top-1 match is from the correct agent domain and has
similarity ≥ `SINGLE_HOP_THRESHOLD` (0.50, model-agnostic).

### 2. Multi-hop reasoning (100 tasks)

Tasks that require combining two stored patterns from different domains
(e.g. "write tests for the Stripe webhook handler" needs both an
API-integration pattern and a test-generation pattern). Verifies that
both relevant patterns are returned in the top-5.

**What passes**: both required domain markers appear in the top-5 task
texts.

### 3. Temporal reasoning (100 tasks)

Queries asking for the most recent version of a pattern ("use the
updated approach after the incident"). `Memory.recall()` in v0.6.5 has
no recall-time recency ranking — `Pattern.timestamp` is consumed only
by the offline `run_aging()` decay job — so this dimension measures
whether the embedding model plus the stored task text alone can surface
the newest pattern. Runs with `eval_weighted=False` and
`deduplicate=False`; the earlier `eval_weighted=True` plus
`success_score ≥ 8.0` rule reduced to the seed-data tautology because
v3 patterns were seeded with `eval_score=9.1`.

**What passes**: top-1's `pattern.task` contains both the queried
domain marker AND the `v3` marker — i.e. the system returned *this*
domain's newest version, not a v1/v2 of the same domain or a v3 of
an unrelated one. See the "Temporal dimension" note under Results —
this dimension currently reads as a harness-limitation diagnostic
rather than a headline measurement.

### 4. Knowledge updates (100 tasks)

Memory is seeded with three quality tiers per domain (eval scores 6.2,
7.8, 9.1). Queries ask for the "updated approach" or "post-review
pattern". Verifies that `eval_weighted=True` reliably surfaces the best
known version.

**What passes**: top-1 match has `success_score ≥ 8.5`.

> This dimension has a mechanically high random-baseline ceiling
> (~40 %) because one third of seeded patterns satisfy the pass rule
> by construction. The discrimination margin is the gap between
> Engramia's score and the random baseline, not the absolute number.

### 5. Absent-memory detection (80 tasks)

Tasks outside every stored domain (image processing, game dev, hardware
design, esoteric languages). Verifies that Engramia declines to match
rather than hallucinating a pattern. The noise-similarity threshold is
auto-calibrated **on a held-out pool** (`NOISE_CALIBRATION_POOL`)
strictly disjoint from the evaluation pool (`NOISE_EVALUATION_POOL`)
— the earlier harness sampled both from the same list and produced a
trivial 100 %.

**What passes**: top-1 similarity is below the held-out-calibrated
noise threshold, or no match is returned.

## Dataset

| Dimension                | Tasks | Notes                                          |
|--------------------------|------:|------------------------------------------------|
| Single-hop recall        |   120 | 10 query variants × 12 domains                 |
| Multi-hop reasoning      |   100 | 10 cross-domain pairs + paraphrases            |
| Temporal reasoning       |   100 | 100 tasks across all 12 domains                |
| Knowledge updates        |   100 | 3 quality tiers per domain in memory           |
| Absent-memory detection  |    80 | 20 eval queries × 4 variants; 20 held-out      |
| **Total**                | **500** |                                              |

Agent domains covered:
`code_generation`, `bug_diagnosis`, `test_generation`, `refactoring`,
`data_pipeline`, `api_integration`, `infrastructure`, `database_migration`,
`security_hardening`, `documentation`, `performance`, `cicd_deployment`.

## Results

Three numbers per dimension — the **tuned** column is the superseded
pre-audit methodology kept only as a historical record of why the
harness was revised; the **pre-registered** column is the
authoritative post-audit measurement; the **random-baseline** column is
the seeded random-recall floor from the same 500 tasks.

### Engramia v0.6.6 (2026-04-21, post-audit)

Authoritative column is **Post-audit (OpenAI)** — OpenAI
`text-embedding-3-small` is the embedding model named in the
project's public methodology docs and what the hosted service runs
against. A secondary **Post-audit (MiniLM)** column records a run on
`sentence-transformers/all-MiniLM-L6-v2` so anyone can reproduce the
harness without an OpenAI API key.

| Dimension                | Pre-audit (OpenAI, tuned) | Post-audit (OpenAI) | Post-audit (MiniLM) | Random baseline (OpenAI run) |
|--------------------------|--------------------------:|--------------------:|--------------------:|-----------------------------:|
| Single-hop recall        |         99.2 % (119/120) |   90.8 % (109/120) |    83.3 % (100/120) |                      3.3 % |
| Multi-hop reasoning      |        100.0 % (100/100) |  100.0 % (100/100) |   100.0 % (100/100) |                     15.0 % |
| Temporal reasoning       |        100.0 % (100/100) |  **0.0 %**  (0/100) |    84.0 %  (84/100) |                      3.0 % |
| Knowledge updates        |        100.0 % (100/100) |  100.0 % (100/100) |   100.0 % (100/100) |                     41.0 % |
| Absent-memory detection  |         100.0 % (80/80)  |   100.0 %  (80/80) |     96.2 %  (77/80) |                     40.0 % |
| **Overall**              |   **99.8 % (499/500)**   | **77.8 % (389/500)** | **92.2 % (461/500)** | **19.0 % (95/500)** |

- **Pre-audit (OpenAI, tuned)** reproduces the pre-audit harness on
  OpenAI `text-embedding-3-small` and is retained only as an honest
  record of the methodology we moved away from. It should not be
  cited — it depends on post-hoc threshold tuning, a
  self-referential absent-memory calibration, and an
  eval_weighted-driven temporal check that reduces to the seed data.
- **Post-audit (OpenAI)** is the authoritative number. Revised harness:
  pre-registered `SINGLE_HOP_THRESHOLD = 0.50` (model-agnostic, frozen
  in source), held-out `NOISE_CALIBRATION_POOL` disjoint from the
  graded pool, and `temporal_reasoning` with `eval_weighted=False`
  plus a top-1 must contain both the queried domain marker and the
  `v3` marker. Temporal falls to 0 % here — see the note below.
- **Post-audit (MiniLM)** is the same revised harness run on
  `sentence-transformers/all-MiniLM-L6-v2`. The higher overall (92.2 %)
  reflects a coincidence in how MiniLM ranks `v3` against `v2` tokens
  under temporal queries, not a material difference in Engramia's
  retrieval. It is reported so that a fresh checkout without an OpenAI
  key can reproduce a full five-dimension run.
- **Random baseline** comes from the seeded
  `--include-random-baseline` stub (`seed=42`) and is deterministic
  across re-runs — only wall-clock `duration_seconds` varies. The
  column shown is the baseline captured during the OpenAI run;
  the MiniLM run's baseline differs slightly because the stub consumes
  the RNG in the same order but the total number of dimensions is
  identical and the per-dimension floors match within <1 pp.

### Temporal dimension: a measurement of embedder coincidence, not of Engramia

`Memory.recall()` in v0.6.5 has no recall-time recency ranking.
`Pattern.timestamp` is consumed only by the offline `run_aging()`
decay job. The only temporal signal a query can exploit at recall
time is whatever the embedding model extracts from the stored task
text.

The synthetic seed stores three near-duplicate tasks per domain
(`"Write X code v1"`, `v2`, `v3`) separated only by the trailing
version token. For the query `"Apply the most recent X pattern …"`:

- **OpenAI `text-embedding-3-small`** ranks `v2 > v3 > v1`
  consistently across all 12 domains. The pass rule (top-1 is the
  queried domain's v3) therefore fails for every task → 0 / 100.
- **`all-MiniLM-L6-v2`** ranks `v3 > v2 > v1` on most queries → 84 /
  100.

Both numbers are honest measurements of **what the embedding model
does with three near-identical strings**. Neither is a measurement of
Engramia's temporal reasoning, because Engramia does not currently
perform any. A legitimate temporal dimension requires either a
`recency_weight` parameter on `recall()` (tracked in Phase B) or a
training text that gives the embedder a real temporal signal (e.g.
`"2024-era approach"`, `"post-incident 2026 rewrite"`).

Until one of those lands, the temporal dimension should be read as a
**harness-limitation diagnostic**, not as a headline figure. Overall
scores in the table above include it so readers can see the full
harness state; the knowledge-updates dimension already captures the
question temporal was meant to answer (`prefer the newest / highest-
quality pattern`) via the eval-score signal that Engramia does
support.

Setup (post-audit OpenAI column):

- Embedding model: OpenAI `text-embedding-3-small` (1536-dim)
- Hardware: operator workstation (Windows 11, Python 3.14)
- Storage: `JSONStorage`, isolated per dimension
- Deterministic across re-runs (`readonly=True` on every `mem.recall` call)
- Raw JSON: [`benchmarks/results/longmemeval_2026-04-21.json`](results/longmemeval_2026-04-21.json)

Discrimination margin: Engramia 77.8 % vs. random 19.0 % — a 4.1×
gap overall. Per dimension: single-hop 27.5× (90.8 / 3.3),
multi-hop 6.7×, temporal 0× (both floor and Engramia at/near zero —
not discriminating), knowledge-updates 2.4× (over a high 41 %
floor), absent-memory 2.5× (over a high 40 % floor).
Knowledge-updates and absent-memory carry the highest random floors
by construction — discrimination there is the gap above the floor,
not the absolute number.

### Competitor comparison

**Not published yet.** Hindsight, Mem0, and Zep need to be re-evaluated on
this same code path — with each system's stated default configuration — for
any comparison to be apples-to-apples. The pre-release internal numbers
(Hindsight 91.4 %, Mem0 82.2 %, Zep 77.8 %) lived under a methodology we no
longer trust and have been dropped rather than carried forward.

If you are a vendor whose system you believe should appear here, open an
issue or email `support@engramia.dev` with reproduction instructions and we
will run your system on this harness in good faith.

## Methodology

### Embedding model

The benchmark picks an embedder from the environment:

- If `OPENAI_API_KEY` is set and `engramia[openai]` is installed, uses
  `OpenAIEmbeddings` with `text-embedding-3-small` (1536-dim). This is the
  authoritative setup.
- Otherwise falls back to `LocalEmbeddings` with
  `sentence-transformers/all-MiniLM-L6-v2` (384-dim). No API key required;
  results land lower because the smaller model separates near-duplicate
  tasks less cleanly, and the pre-registered threshold is deliberately
  not tuned to rescue that gap.
- Force local even with an API key: `ENGRAMIA_BENCHMARK_EMBEDDING=local`.

### Similarity thresholds

- `single_hop_recall` uses `SINGLE_HOP_THRESHOLD = 0.50`, a single
  model-agnostic constant frozen in `longmemeval.py`. Readers who swap
  the embedding model do not get to tune this value — a different model
  producing a different score is the signal this benchmark is trying to
  surface.
- `absent_memory_detection` auto-calibrates its noise threshold at the
  start of the dimension: it embeds one representative task per domain
  plus every query in the held-out `NOISE_CALIBRATION_POOL` (disjoint
  from the evaluation pool by construction; enforced at module import),
  then sets the threshold to `max(noise-to-any-domain similarity) +
  0.05`. A query whose top similarity sits below that line is considered
  correctly absent.

### Random-recall baseline

```bash
python -m benchmarks.longmemeval --include-random-baseline
```

Runs a seeded random-recall stub across all five dimensions on the same
500 tasks and attaches per-dim numbers to `comparison.random_baseline` in
the output JSON. The stub fabricates a synthetic pattern universe
identical in shape to the real seed (3 versions × 12 domains = 36
patterns) and returns `limit` random picks per call with random but
descending similarity scores. `--random-baseline-seed SEED` overrides
the default seed (42). Two runs with the same seed are bit-identical.

### Memory configuration

```python
mem = Memory(
    embeddings=<provider>,
    storage=JSONStorage(path=tmp_dir),
)
```

Each dimension runs in an isolated `Memory` instance. No
cross-contamination between dimensions.

### Reproducibility

- `Memory.recall(..., readonly=True)` is used on every recall call during
  the benchmark so `mark_reused` does not mutate `success_score` across
  queries. Back-to-back runs with the same embedding model are bit-
  identical.
- Deterministic given the same embedding model and dataset. No LLM
  calls in the evaluation path.
- All numbers above correspond to the committed JSON at
  `benchmarks/results/longmemeval_2026-04-21.json`.

## Reproducing locally

```bash
# Without an API key (local embeddings)
pip install 'engramia[local]'
python -m benchmarks.longmemeval

# With an API key (authoritative config)
pip install 'engramia[openai]'
export OPENAI_API_KEY=sk-...
python -m benchmarks.longmemeval

# Attach the random-recall baseline to the output
python -m benchmarks.longmemeval --include-random-baseline

# Print pre-computed reference results only
python -m benchmarks.longmemeval --results-only

# Write results to a JSON file
python -m benchmarks.longmemeval --output results/my_run.json
```

## Exit codes

- `0` — overall success rate ≥ 90 %
- `1` — below threshold or benchmark error

## References

- Wu, X. et al. (2024). *LongMemEval: Benchmarking Chat Assistants on
  Long-Term Interactive Memory.* arXiv:2410.10813.
- Engramia benchmark suite: `benchmarks/README.md`

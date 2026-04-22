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

### Engramia v0.6.7 (2026-04-21, post-audit + recency-aware recall)

Authoritative column is **Post-audit (OpenAI)** — OpenAI
`text-embedding-3-small` is the embedding model named in the project's
public methodology docs and what the hosted service runs against.

| Dimension                | Pre-audit (OpenAI, tuned) | Post-audit (OpenAI) | Random baseline |
|--------------------------|--------------------------:|--------------------:|----------------:|
| Single-hop recall        |         99.2 % (119/120) |   90.8 % (109/120) |          3.3 % |
| Multi-hop reasoning      |        100.0 % (100/100) |  100.0 % (100/100) |         15.0 % |
| Temporal reasoning       |        100.0 % (100/100) |  100.0 % (100/100) |          3.0 % |
| Knowledge updates        |        100.0 % (100/100) |  100.0 % (100/100) |         41.0 % |
| Absent-memory detection  |         100.0 % (80/80)  |   100.0 %  (80/80) |         40.0 % |
| **Overall**              |   **99.8 % (499/500)**   | **97.8 % (489/500)** | **19.0 % (95/500)** |

- **Pre-audit (OpenAI, tuned)** reproduces the pre-audit harness on
  OpenAI `text-embedding-3-small` and is retained only as an honest
  record of the methodology we moved away from. It should not be
  cited — it depended on post-hoc threshold tuning, a self-referential
  absent-memory calibration, and an eval_weighted-driven temporal
  check that reduced to the seed data.
- **Post-audit (OpenAI)** is the authoritative number. Revised harness:
  pre-registered `SINGLE_HOP_THRESHOLD = 0.50` (model-agnostic, frozen
  in source), held-out `NOISE_CALIBRATION_POOL` disjoint from the
  graded pool, and `temporal_reasoning` now exercises
  `Memory.recall(recency_weight=1.0)` (new in 0.6.7) against
  back-dated seed timestamps (v1 = 90 days old, v2 = 45 days old,
  v3 = now) so the recency knob is tested well above the similarity
  noise floor.
- **Random baseline** comes from the seeded
  `--include-random-baseline` stub (`seed=42`) and is deterministic
  across re-runs — only wall-clock `duration_seconds` varies.

### Temporal dimension: now a legitimate measurement (since 0.6.7)

Pre-0.6.7, `Memory.recall()` had no recall-time recency signal, and
`Pattern.timestamp` was consumed only by the offline `run_aging()`
decay job. The temporal dimension therefore reduced to whatever the
embedding model extracted from near-duplicate stored task texts — an
implicit embedder lottery. OpenAI `text-embedding-3-small` scored
0 / 100 (ranked v2 above v3 on raw cosine); `all-MiniLM-L6-v2`
scored 84 / 100 coincidentally. Neither was a measurement of Engramia.

Release 0.6.7 added `recall(recency_weight=..., recency_half_life_days=...)`
as an explicit query-time recency signal. The benchmark now:

1. Back-dates each stored pattern at seed time so v1 is 90 days old,
   v2 is 45 days old, v3 is fresh. This mirrors how patterns actually
   accumulate in production (hours / days / weeks apart) rather than
   the microseconds between sequential `mem.learn()` calls, and places
   v1 / v2 / v3 at recency factors of 1/8, 1/2, and 1.0 respectively
   under the default 30-day half-life.
2. Calls `recall(task, recency_weight=1.0, eval_weighted=False,
   deduplicate=False)`.
3. Passes when top-1's task text contains the queried domain marker
   AND the ``v3`` marker.

Under this protocol OpenAI scores **100 / 100** — the recency signal
consistently promotes v3 above the ±0.02 cosine noise between the
three versions. The dimension is therefore no longer an embedder
lottery; it directly tests whether the system under test ranks
recent patterns above stale ones.

Setup (post-audit OpenAI column):

- Embedding model: OpenAI `text-embedding-3-small` (1536-dim)
- Hardware: operator workstation (Windows 11, Python 3.14)
- Storage: `JSONStorage`, isolated per dimension
- Deterministic across re-runs (`readonly=True` on every `mem.recall` call)
- Raw JSON: [`benchmarks/results/longmemeval_2026-04-21.json`](results/longmemeval_2026-04-21.json)

Discrimination margin: Engramia 97.8 % vs. random 19.0 % — a 5.1×
gap overall. Per dimension: single-hop 27.5× (90.8 / 3.3),
multi-hop 6.7×, temporal 33.3× (100.0 / 3.0), knowledge-updates 2.4×
(over a high 41 % floor), absent-memory 2.5× (over a high 40 %
floor). Knowledge-updates and absent-memory carry the highest random
floors by construction — discrimination there is the gap above the
floor, not the absolute number.

### Competitor comparison

Re-produced on this exact harness via ``benchmarks/longmemeval_competitors.py``
and the adapter protocol in ``benchmarks/adapters/``. Every competitor
carries a ``forced_mapping_note`` in its emitted JSON because
competitors' semantics rarely overlap Engramia's 1:1 — a single number
without context is misleading.

Three backends benchmarked to date — Engramia 0.6.7 (native), Mem0
OSS (local Qdrant), Hindsight (Docker server). All three columns
use OpenAI `text-embedding-3-small` for embeddings / LLM work and
the same 500-task synthetic suite. Pass rules loosened vs the
Engramia-native harness (no SINGLE_HOP_THRESHOLD check;
knowledge_updates substitutes a text-level "v3" check for the
`success_score ≥ 8.5` check — competitors don't all expose a
quality multiplier). Rule table: see
[`benchmarks/longmemeval_competitors.py`](longmemeval_competitors.py)
module docstring.

| Dimension                | Engramia 0.6.7 | Mem0 v2.0.0 | Hindsight 0.5.4 | Random baseline |
|--------------------------|---------------:|------------:|----------------:|----------------:|
| Single-hop recall        |  90.8 % (109/120) | 97.5 % (117/120) |   95.0 % (114/120) |          3.3 % |
| Multi-hop reasoning      | 100.0 % (100/100) |  81.0 % (81/100) |    97.0 %  (97/100) |         15.0 % |
| Temporal reasoning       | 100.0 % (100/100) |  26.0 % (26/100) |    59.0 %  (59/100) |          3.0 % |
| Knowledge updates        | 100.0 % (100/100) |   8.0 %  (8/100) |    41.0 %  (41/100) |         41.0 % |
| Absent-memory detection  |  100.0 %  (80/80) |  97.5 %  (78/80) |     0.0 %   (0/80) |         40.0 % |
| **Overall**              | **97.8 % (489/500)** | **62.0 % (310/500)** | **62.2 % (311/500)** | **19.0 %** |

#### Cross-system notes

* **Single-hop high scores need context.** Mem0 (97.5 %) and
  Hindsight (95.0 %) appear to top Engramia here, but the
  Engramia-native harness also enforces
  `similarity ≥ SINGLE_HOP_THRESHOLD = 0.50` on raw cosine. The
  competitor harness drops that check because competitor score
  distributions are not on the same scale — Hindsight exposes no
  similarity at all. Straight apples-to-apples with Engramia's
  threshold included, both competitors would land lower.

* **Multi-hop** (second-best after Engramia): Hindsight's graph
  retrieval strategy helps here (97.0 %); Mem0 is pure vector so
  it loses more often on the two-domains-in-one-query pattern
  (81.0 %).

* **Temporal** is where the architectural difference is starkest.
  Engramia 100 % because `recall(recency_weight=1.0)` (0.6.7
  feature) promotes the newest version under back-dated seed
  timestamps. Hindsight 59 % from its "temporal" retrieval
  strategy alone (no explicit caller knob; the server's internal
  temporal reasoning fires automatically). Mem0 26 % — close to
  its single_hop floor, no recency signal whatsoever.

* **Knowledge updates**: Engramia 100 % (quality-weighted path
  promotes v3). Hindsight 41 % — exactly matches the random-recall
  floor, which means its retrieval is not preferring v3 over
  v1/v2 on these queries. Mem0 8 % — *below* the random floor, a
  Qdrant HNSW tie-break artefact (identical-embedding patterns
  return in insertion order, so v1 wins).

* **Absent-memory detection** exposes a fundamental architectural
  mismatch for Hindsight: **0.0 %** because its recall always
  fuses results from four strategies (semantic + keyword + graph
  + temporal) and returns *something* for every query. Without a
  numeric similarity to threshold on, the competitor harness
  treats "any match returned" as a failure. This is not a
  retrieval-quality deficiency — it is an API-shape mismatch, and
  it is surfaced explicitly in Hindsight's
  `forced_mapping_note`. For workloads where "should we answer
  this at all?" needs to be inferable, Hindsight callers have to
  reason about it out-of-band.

Raw JSON:

* Mem0: [`benchmarks/results/longmemeval_competitor_mem0_2026-04-22.json`](results/longmemeval_competitor_mem0_2026-04-22.json)
* Hindsight: [`benchmarks/results/longmemeval_competitor_hindsight_2026-04-22.json`](results/longmemeval_competitor_hindsight_2026-04-22.json)

Reproduce:

```bash
# Mem0 (no Docker needed, reuses your OPENAI_API_KEY)
pip install 'mem0ai'
python -m benchmarks.longmemeval_competitors \
    --adapter mem0 \
    --output results/longmemeval_competitor_mem0_YYYY-MM-DD.json

# Hindsight (requires Docker running)
docker run --rm -d --name hindsight-bench \
    -p 8888:8888 -p 9999:9999 \
    -e HINDSIGHT_API_LLM_API_KEY=$OPENAI_API_KEY \
    ghcr.io/vectorize-io/hindsight:latest
pip install hindsight-client
python -m benchmarks.longmemeval_competitors \
    --adapter hindsight \
    --output results/longmemeval_competitor_hindsight_YYYY-MM-DD.json
docker stop hindsight-bench
```

**Zep (deferred).** Chat-session memory with knowledge-graph
extraction, farther from execution-memory than Mem0 or Hindsight.
Adapter will be added when pilot outreach demands it.

If you are a vendor whose system should appear here, open an issue or
email `support@engramia.dev` with reproduction instructions and we
will run your system on this harness in good faith.

## LongMemEval (Wu 2024) real-dataset port

Separate harness at `benchmarks/longmemeval_real.py` runs Engramia
against the actual [LongMemEval](https://arxiv.org/abs/2410.10813)
dataset (Wu et al. 2024). The synthetic 500-task suite above is
Engramia-native and controls the ranking variables we want to
isolate (similarity, quality, recency); the Wu 2024 port is the
established external reference point the pilot-outreach docs can
cite.

**Variant.** Oracle (15 MB, only evidence sessions per question).
Oracle supplies a pruned haystack — it is NOT a scale-out
retrieval test. Engramia's storage scale-out story (`PostgresStorage`
+ pgvector + HNSW) runs the Wu 2024 S (115 k tokens) and M (1.5 M
tokens) variants; those runs will land when we have wall-clock
numbers worth publishing.

**Protocol (per question).** Seed a fresh `Memory` with every
`haystack_session` as one pattern per user/assistant turn pair
(session dates written to `Pattern.timestamp`). Recall top-5 on the
question, synthesize a hypothesis with `gpt-4o-mini` given the
recalled context, judge the hypothesis against the ground-truth
`answer` with another `gpt-4o-mini` call. Two metrics:

* **Retrieval hit rate** — does the top-5 recall include any session
  listed in `answer_session_ids`? Objective, cheap.
* **Q&A correct rate** — does the LLM judge rate the synthesized
  hypothesis as matching the reference answer? Subjective, captures
  both retrieval quality AND the reasoner's ability to extract the
  answer from the recalled context.

**Results (temporal-reasoning category, 133 questions, 2026-04-22)**:

| Metric | Score | Notes |
|---|--:|---|
| Retrieval hit rate | **100.0 %** (133/133) | Top-5 always includes at least one evidence session under Oracle. |
| Q&A correct rate | **29.3 %** (39/133) | gpt-4o-mini judge against gpt-4o-mini synthesizer output. Mostly gated by the synthesizer's temporal-reasoning ability, not by recall. |

Setup: OpenAI `text-embedding-3-small` (embeddings), `gpt-4o-mini`
(synthesizer + judge), Oracle variant. Cost $0.029 per full temporal
run. Paper uses `gpt-4o` as judge — expected minor divergence from
the paper's reported numbers. Raw JSON:
[`benchmarks/results/longmemeval_real_temporal_2026-04-22.json`](results/longmemeval_real_temporal_2026-04-22.json).

**Interpretation.** The 100 % retrieval rate is a valid but
not-very-discriminating measurement under Oracle — the haystack is
tiny (average 2.2 evidence sessions per question), so any reasonable
semantic retriever will find at least one. The S and M variants of
Wu 2024, which bury the needles in 30+ and 500+ sessions of noise
respectively, are where retrieval quality becomes discriminating;
those runs are tracked separately.

Other LongMemEval categories (multi-session, knowledge-update,
single-session-*) will land in follow-up commits.

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

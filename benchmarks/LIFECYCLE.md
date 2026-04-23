# AgentLifecycleBench — Engramia closed-loop memory benchmark

A benchmark that measures what Engramia exists to do on top of
recall: learn from evaluations, deprecate failed patterns, resolve
quality-vs-recency conflicts, absorb concept drift, and reject
adversarial signal noise.

Where [LongMemEval](LONGMEMEVAL.md) measures single-shot recall
quality — a problem commodity vector DBs also solve — this benchmark
measures the closed-loop primitives that distinguish an execution-
memory system from a vector DB.

## Why a separate benchmark

Running the LongMemEval synthetic suite against Mem0 and Hindsight
produced suspiciously clean numbers because competitors can do
semantic recall. On **lifecycle** scenarios (refine-pattern feedback,
timestamp-aware conflict resolution, quality-weighted deprecation),
the competitors return `capability_missing` on all 15 scenario-
difficulty combinations because their public APIs do not expose a
refinement write path. The distinction between "score 0 %" and
"cannot participate" is the honest framing marketing copy needs —
a backend is either missing the feature or performing poorly at it,
and readers deserve to know which.

## Honesty policy

1. **Difficulty levels are published, not selected.** Every scenario
   runs at `easy / medium / hard` and all three columns appear in
   every result JSON. Picking the easy number for marketing would
   leave a public audit trail pointing at the medium-difficulty
   column.
2. **Continuous metrics alongside headline numbers.** Each scenario
   reports a curve (convergence over iterations, precision@K,
   recency sharpness, classification F1) so a reader can see
   degradation shape and not just whether the binary pass rule fired.
3. **Capability flags, not zero placeholders.** Backends without the
   required capability return `capability_missing`, not 0 %. The
   JSON has a boolean field readers can check before citing numbers.
4. **Adapter code is public.** Competitor runs use the same
   `benchmarks/adapters/` protocol Engramia uses. A vendor who
   believes their adapter should score higher can read the code,
   correct our mapping, and PR the fix.
5. **Decoupling regression tests pin the mental model.**
   `tests/test_ranking_feedback.py` asserts that `mark_reused` and
   direct `Pattern.success_score` mutations do NOT change recall
   ranking, because survival signals are intentionally orthogonal
   to ranking. A future refactor that accidentally couples them
   fails the tests.

## The five scenarios

Each scenario has a pre-registered pass rule, a random baseline,
and the Engramia feature under test. Difficulty knobs shift the
signal magnitude or the noise level; they do not change the
discriminability of the test.

### L1 — Improvement curve

Does repeated quality-evidence refinement converge on the
designed-best approach over iterations?

- **Feature tested**: `refine_pattern` writing to the eval store,
  consumed by `recall(eval_weighted=True)`.
- **Curve**: `convergence` = fraction of 12 tasks whose current
  top-1 is the ground-truth best after each of N iterations.
- **Difficulty knob**: noise probability on feedback observations
  (0 % / 20 % / 40 % uniform-random).
- **Random baseline**: 1/3 (three candidate approaches per task).
- **Pass rule**: ≥ 80 % correct after N iterations.

### L2 — Deprecation speed

Does quality-weighted recall rank failed patterns below good ones
once failure feedback is recorded?

- **Feature tested**: `refine_pattern` downgrade demotes patterns
  out of top-K under `eval_weighted=True`.
- **Curve**: `precision@K` for K ∈ {1, 3, 5, 10}.
- **Difficulty knob**: quality score gap (0.5 vs 7.0 / 3.0 vs 7.0 /
  4.0 vs 6.0).
- **Random baseline**: 0.5 (50 / 50 good / failed mix).
- **Pass rule**: ≥ 80 % of top-5 from the non-deprecated set.

### L3 — Conflict resolution

Does `recency_weight` cleanly tune ranking between old high-quality
and fresh medium-quality patterns?

- **Feature tested**: `recency_weight` knob on `recall()` +
  timestamp-aware ranking.
- **Curve**: `new_fraction_by_weight` at 11 steps of `recency_weight`
  from 0.0 to 1.0, plus a `crossover_weight` — the first weight at
  which the fresh cohort wins the top-1 majority.
- **Difficulty knob**: age gap + quality gap (180 d / 9.0 vs 7.0;
  60 d / 8.5 vs 7.5; 15 d / 8.0 vs 7.5).
- **Random baseline**: 0.5.
- **Pass rule**: average of (old wins at `w=0`, new wins at `w=1`)
  ≥ 80 %.

### L4 — Concept drift

Does `refine_pattern` + `recency_weight` stacking make a small fresh
cohort dominate an older, larger stale one?

- **Feature tested**: both knobs composed.
- **Curve**: `precision@K` for K ∈ {1, 3, 5, 10}.
- **Difficulty knob**: population imbalance and v3 refined score
  (20 vs 10 / 9.5; 30 vs 10 / 8.5; 40 vs 10 / 8.0).
- **Random baseline**: `n_v3 / (n_v2 + n_v3)`.
- **Pass rule**: ≥ 60 % of top-5 from the fresh v3 cohort.

### L5 — Signal-to-noise floor

Does one round of `refine_pattern` re-grading demote adversarial
(spoofed high-score) patterns below the honest cohort?

- **Feature tested**: `refine_pattern` re-grading → multiplier shift
  → recall re-order.
- **Curve**: classification metrics (precision / recall / F1 treating
  "honest pattern in top-10" as positive) pre- and post-refine, plus
  `f1_improvement` delta.
- **Difficulty knob**: size of the correction (9.5 → 1.0 / 8.0 → 3.0 /
  7.5 → 5.0).
- **Random baseline**: 0.5.
- **Pass rule**: ≤ 20 % red herrings in top-10 after one re-eval.

## Results (2026-04-23)

All three backends exercise the **same** scenario code through the
`MemoryAdapter` / `LifecycleAdapter` protocol. Engramia runs on local
`all-MiniLM-L6-v2` embeddings; Mem0 uses its own OpenAI pipeline;
Hindsight uses its Docker server. Adapter code:
[`benchmarks/adapters/`](adapters/).

### Score matrix — easy / medium / hard

| Scenario                 | Engramia | Mem0    | Hindsight | Random |
|--------------------------|----------|---------|-----------|--------|
| L1 improvement_curve     | 100 / 33 / 58 % | — / — / — | — / — / — | 33.3 % |
| L2 deprecation_speed     | 100 / 100 / 100 % | — / — / — | — / — / — | 50.0 % |
| L3 conflict_resolution   | 100 / 100 / 100 % | — / — / — | — / — / — | 50.0 % |
| L4 concept_drift         | 100 / 100 / 100 % | — / — / — | — / — / — | 33.3 % |
| L5 noise_rejection       | 100 / 100 / 100 % | — / — / — | — / — / — | 50.0 % |
| **Mean per difficulty**  | **100 / 86.7 / 91.7 %** | missing | missing | 43.3 % |

`—` = `capability_missing`. Both competitors return missing on all 15
scenario-difficulty combinations — neither `mem0ai` nor
`hindsight-client` exposes a refine-pattern-equivalent.

### What the curves reveal

#### L1 convergence — honest diagnostic

```
easy    [0.67, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00]
medium  [0.67, 0.83, 0.83, 0.67, 0.58, 0.58, 0.50, 0.58, 0.50, 0.33, 0.33]
hard    [0.67, 0.92, 0.92, 0.67, 0.33, 0.33, 0.42, 0.50, 0.58]
```

The medium curve is a real architectural finding: under 20 %
uniform-random noisy feedback, Engramia briefly converges then
**decays back to random baseline**. Root cause: `EvalStore.
get_agent_score` returns the LATEST observation, so a single bad
refinement overwrites the accumulated correct evidence. A future
`median-over-last-N` aggregator would likely flatten the decay —
the curve is the diagnostic this benchmark exists to surface.

#### L3 recency sharpness

All three difficulty levels show an essentially binary flip at
`recency_weight = 0.1` (top-1 fraction goes 0.0 → 1.0 at the first
non-zero weight). Marketing takeaway: the recency knob is sharp.
Diagnostic takeaway: there is no continuous mid-range; workloads
wanting a gentle blend have no native knob for it.

#### L5 F1 improvement

Pre-refine the top-10 is 100 % red herrings (their spoofed 9.5
eval score beats honest 7.0). Post-refine (herrings corrected to
1.0) top-10 is 100 % honest. F1 delta = +1.0 at every difficulty
level. The sharp improvement is because the test uses shared task
text — it is a clean demonstration that the refine path reaches
recall, not a real-world noisy signal.

#### L2 / L4 precision@K

All 1.0 across K ∈ {1, 3, 5, 10} and every difficulty level. The
quality multiplier alone decisively orders the cohorts; there is no
depth-of-ranking degradation to surface here. These scenarios
remain feature-correctness tests, not diagnostic probes, until a
future variant breaks the shared-task-text assumption.

## How to read these numbers for marketing

**Do not cite the "easy" column as the headline number.** Use the
**medium-difficulty mean** as the realistic-workload estimate.

For the 2026-04-23 run that is **86.7 %** (over 5 scenarios on
Engramia, local MiniLM). Competitors cannot produce a comparable
number — they return `capability_missing` on every scenario.

A defensible public claim:

> On the AgentLifecycleBench medium-difficulty profile, Engramia
> scores 86.7 % on five closed-loop memory scenarios. Mem0 and
> Hindsight return `capability_missing` on all fifteen scenario-
> difficulty combinations because their APIs do not expose a
> refinement write path. Raw JSON published alongside every run.

Do NOT say "Engramia beats Mem0 by X %" on these scenarios —
there is nothing to beat; the competitors aren't in the race. The
accurate framing is that Engramia measurably performs the task
these scenarios define, while the tested competitors cannot
attempt it.

## Reproducing locally

```bash
# Engramia with local embeddings (zero API cost)
pip install 'engramia[local]'
python -m benchmarks.lifecycle --adapter engramia --local \
    --output benchmarks/results/lifecycle_engramia_$(date +%Y-%m-%d).json

# Mem0 (self-hosted, reuses OPENAI_API_KEY)
pip install mem0ai
python -m benchmarks.lifecycle --adapter mem0 \
    --output benchmarks/results/lifecycle_mem0_$(date +%Y-%m-%d).json

# Hindsight (requires Docker + ghcr.io/vectorize-io/hindsight image)
docker run --rm -d --name hindsight-bench -p 8888:8888 -p 9999:9999 \
    -e HINDSIGHT_API_LLM_API_KEY=$OPENAI_API_KEY \
    ghcr.io/vectorize-io/hindsight:latest
pip install hindsight-client
python -m benchmarks.lifecycle --adapter hindsight \
    --output benchmarks/results/lifecycle_hindsight_$(date +%Y-%m-%d).json
docker stop hindsight-bench
```

Each run is deterministic given the same adapter + embedding
configuration; scenario `rng_seed` defaults to 42 and can be
overridden via the CLI.

## Files

- `benchmarks/lifecycle.py` — the harness. Scenario functions L1–L5,
  difficulty tuning tables, runner, CLI.
- `benchmarks/adapters/base.py` — `MemoryAdapter` + `LifecycleAdapter`
  protocols.
- `benchmarks/adapters/engramia_adapter.py` — canonical adapter;
  `supports_refine=True`, `supports_timestamp_patch=True`.
- `benchmarks/adapters/mem0_adapter.py`,
  `benchmarks/adapters/hindsight_adapter.py` — competitor adapters
  declaring `supports_refine=False` with module docstrings explaining
  why their APIs cannot honour the contract.
- `benchmarks/results/lifecycle_*_2026-04-23.json` — the raw JSON
  cited in this document.
- `tests/test_ranking_feedback.py` — regression guard that pins the
  decoupling of survival vs ranking signals.

## Glossary

- **Survival signal** — updates `Pattern.success_score`,
  `reuse_count`, or the pattern's persistence state. Drives
  `run_aging` / pruning decisions. Does NOT drive recall ranking.
- **Ranking signal** — writes to the eval store keyed by
  `pattern_key`. Drives `eval_weighted` recall's quality multiplier
  and, combined with `recency_weight`, the top-K ordering.
- **`refine_pattern`** — the public write path for ranking signals.
  Added in 0.6.7 to close the learn → recall → refine loop.
- **`evaluate(pattern_key=...)`** — alternative write path that runs
  a multi-evaluator LLM grading and writes the result to the eval
  store under the given pattern's key.
- **Capability missing** — an adapter returns this when the backend's
  public API cannot honour a scenario's required write path. It is
  a distinct state from "scored 0 %".

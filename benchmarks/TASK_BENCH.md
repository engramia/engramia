# AgentTaskBench — agent pass-rate with vs without Engramia

Third layer of the benchmark suite. Where
[LongMemEval](LONGMEMEVAL.md) measures recall quality and
[AgentLifecycleBench](LIFECYCLE.md) exercises closed-loop primitives,
this benchmark answers the buyer-level question: **does an agent
actually complete more work with Engramia than without?**

## Design

- **Dataset**: HumanEval+ (164 Python coding problems with
  test-based correctness checks). Loaded via the upstream `evalplus`
  package.
- **Agent**: `gpt-4o-mini` at `temperature=0`. One generation per
  task per iteration. Agent receives a prompt plus an optional
  memory context (empty for the baseline).
- **Scoring**: agent-generated completion is executed in a
  subprocess with a 30-second timeout, then the task's `check(...)`
  test harness is appended and asserted. Non-zero exit = fail.
- **Configurations**: two, run back-to-back in one session:
  - `baseline-no-memory` — stateless; `recall_context = ""` every
    iteration.
  - `engramia` — wraps `engramia.Memory`; after each passing task,
    `Memory.learn(task, code, eval_score=9.0,
    on_duplicate="replace_with_better")` preserves the best-scored
    completion. Repeat successes append a `refine_pattern` record to
    keep the eval-store evidence current.
- **Iterations per config**: 20 (default). Configurable via
  `--iterations`.
- **Concurrency**: agent + scoring calls run through a ThreadPool
  (default 5 workers, cranked up to 15 for full-dataset runs).
  Backend writes (`remember_success`) are serialised after each
  iteration so Engramia's JSONStorage isn't raced.

## Headline metric

**Pass-rate improvement slope** over iterations:

- `engramia_improvement` = pass-rate at iter N minus pass-rate at
  iter 1.
- `baseline_improvement` = same metric for the stateless config.
- `engramia_vs_baseline_delta` = terminal pass-rate difference.

A healthy result looks like: baseline stays flat (no memory, no
learning), Engramia ramps up as the pattern pool grows and `refine_
pattern` keeps the best completions at the top of recall.

## Not in CI

D6 of the scope doc: **AgentTaskBench does not run on every push**.
Full-dataset runs cost money and take ~45–60 minutes on
`gpt-4o-mini`. Operators trigger it per release candidate. Results
land in `benchmarks/results/task_bench_<engramia_version>_<date>.json`
so cross-release comparison is a git diff of committed JSON.

## Reproducing

```bash
# Install HumanEval+
pip install evalplus

# Full run — one JSON covers baseline + engramia
python -m benchmarks.agent_task_bench \
    --iterations 20 \
    --concurrency 15

# Smoke run — first N tasks, few iterations
python -m benchmarks.agent_task_bench \
    --tasks-limit 30 --iterations 5 --concurrency 10

# Local embeddings for the Engramia backend (zero API cost for
# embeds; agent calls still cost)
python -m benchmarks.agent_task_bench \
    --iterations 20 --engramia-local-embeddings
```

A full 164 × 20 × 2-config run emits roughly 6,560 gpt-4o-mini
calls. At `$0.15`/1M input + `$0.60`/1M output, expected cost
**≈ $1.35**. Wall-clock time at concurrency=15 is ~45–60 min.

## Expected shape of results

Based on the scenarios AgentLifecycleBench has already validated:

- Baseline pass-rate is effectively flat across iterations — no
  mechanism for the agent to improve with repeated exposure.
  Whatever pass-rate gpt-4o-mini achieves on iteration 1 is what it
  achieves on iteration 20.
- Engramia pass-rate is a **monotone-growing curve** in its healthy
  regime. The rate of growth depends on how often prompts from
  iteration K match a prior-passing pattern retrievable from
  iteration K-1's stored memory.

The curves' shapes matter more than the absolute terminal number:
a steep slope is evidence that closed-loop feedback pays off per
unit of usage. Marketing copy should quote the slope plus the
plateau, not just the maximum.

## Files

- `benchmarks/agent_task_bench/__init__.py` — module root.
- `benchmarks/agent_task_bench/dataset.py` — HumanEval+ loader
  producing `TaskSpec` records.
- `benchmarks/agent_task_bench/agent.py` — gpt-4o-mini wrapper
  with token accounting.
- `benchmarks/agent_task_bench/scoring.py` — subprocess-isolated
  test execution.
- `benchmarks/agent_task_bench/memory_backends.py` —
  `NoMemoryBackend` and `EngramiaBackend` implementations of the
  local `MemoryBackend` protocol.
- `benchmarks/agent_task_bench/runner.py` — orchestration, CLI,
  JSON output, summary printer.
- `benchmarks/agent_task_bench/__main__.py` — `python -m
  benchmarks.agent_task_bench` entry.
- `benchmarks/results/task_bench_<version>_<date>.json` — per-run
  output.

## First demo run (2026-04-23, N=3 iterations, abbreviated)

A short 3-iteration run was executed as a smoke test and a first
honest data point. Full N=20 runs are operator-triggered outside
Claude Code's 10-minute Bash budget.

```
Config                     Iter 1   Iter 3   d (pp)    Secs
----------------------    --------  -------- -------- -------
baseline-no-memory          88.4%    87.8%    -0.6     125
engramia                    89.0%    87.2%    -1.8     349
```

Cost: **$0.18** for 3 × 164 × 2 = 984 agent calls + ~200 embedding
calls + ~200 learn/refine calls.

### Per-task pattern analysis

Over three iterations of all 164 tasks:

| Outcome pattern | Baseline | Engramia |
|---|--:|--:|
| All three iterations passed | 140 | 138 |
| All three iterations failed | 16 | **13** |
| Flaky (at least one flip) | 8 | 13 |

Engramia **recovered three tasks** that baseline failed on every
attempt (`HumanEval/32`, `/83`, `/108`) — these are the signal that
recalled prior context helped the agent produce a passing solution.

Engramia also **regressed four tasks** that baseline passed
consistently (`/91`, `/116`, `/118`, `/142`). The pattern is
context confusion: for some prompts the recall returned 3 prior
completions whose similarity was enough to rank high but whose
content nudged the agent toward the wrong approach.

Net at N=3: roughly a wash. The two configs differ by less than
the OpenAI-side drift we'd expect on a single-run comparison.

### Honest interpretation

On HumanEval+ with `gpt-4o-mini`:

- **HumanEval+ tasks are mostly independent** of each other —
  there is little intra-suite semantic overlap for memory to
  exploit. Three iterations on the same task reduce to "did the
  agent produce the same (or better) completion when shown its
  prior completion?" which is a weak feature lift.
- **`gpt-4o-mini` is already near-ceiling on these problems at
  88 %.** The 12 % it struggles with are tasks whose difficulty
  isn't addressed by prior completions of OTHER tasks, so
  memory's leverage is limited.
- **N=3 is too short** to amortise per-task OpenAI drift.
  Differences under a couple of percentage points are noise.

A workload that would better differentiate the two configs:

- **Tasks with intra-suite overlap** — SWE-bench Lite's bug-fix
  tickets across the same repository exhibit recurring patterns.
- **Weaker agents** where context genuinely adds signal.
- **N=20 or higher** so per-task drift averages out.

Planned follow-up: operator triggers a full N=20 run against the
HumanEval+ harness (wall-clock ~45–60 min, cost ~$1.35) and
commits the JSON. A SWE-bench Lite extension is tracked in the
scope doc for when pilot outreach pulls for the stronger
differentiation story.

## Honesty notes

- Pass-rate is scored by a real test suite bundled with HumanEval+.
  We did not write the tests; EvalPlus did.
- Results are NOT strictly deterministic even at `temperature=0` —
  OpenAI reserves the right to return minor drift. Reported pass-
  rate numbers should be interpreted with ±1–2 pp variance until a
  multi-run audit is performed. The scope doc deliberately budgets
  `single run per config` for the initial build (D2); variance
  audits are operator-triggered when a headline number is about to
  be published.
- Engramia's advantage is expected on tasks where similar-phrased
  prior problems exist. HumanEval+ has some intra-domain overlap
  (arithmetic, list operations, string manipulation), so the recall
  path can actually surface relevant prior completions. On a task
  suite with 164 completely unrelated problems the ramp would be
  shallower — a real-world benefit is workload-shape-dependent, and
  this benchmark surfaces that shape rather than hiding it.
- The Engramia config is ~2.7× slower per run than baseline at the
  default concurrency: recall + learn + refine calls dominate the
  extra wall-clock time. On a cheap-per-call agent like
  `gpt-4o-mini` this is a meaningful overhead; on a more expensive
  agent (Claude 3.5 Sonnet, GPT-4o) the agent call itself is the
  bottleneck and the memory overhead disappears into the noise.

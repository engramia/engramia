# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""AgentTaskBench — end-to-end agent workload comparison.

Runs the same task suite (HumanEval+ by default, 164 Python coding
problems with test-based correctness checks) through two
configurations per session:

- **baseline** — stateless agent, no memory. pass-rate floor.
- **engramia** — agent with Engramia memory: learn on pass, recall
  before each run, refine_pattern after each attempt.

Primary metric: **pass-rate improvement slope** over N=20 iterations.
Secondary metrics: absolute terminal pass-rate, cost per successful
pass, time-to-convergence.

This benchmark is deliberately **not in CI** — it costs ~$1.35 for
a full pair of runs (164 tasks × 20 iter × 2 configs on
gpt-4o-mini) and takes ~45 minutes wall-clock. Operator triggers it
per release candidate. Results go to
``benchmarks/results/task_bench_<engramia_version>_<date>.json`` so
cross-release comparison is a diff of committed JSON.

See ``benchmarks/TASK_BENCH.md`` for methodology and result
interpretation.
"""

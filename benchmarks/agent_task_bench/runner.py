# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""AgentTaskBench runner — orchestrates the per-config iteration loop
over the HumanEval+ task suite.

One session = one full (config × tasks × iterations) sweep. Two
configs are run back-to-back (baseline then engramia) so the
timestamps + token counts in the result JSON come from a single
wall-clock window.

Cost + determinism notes:
- Agent calls use ``temperature=0``; repeat runs are typically
  bit-identical but OpenAI reserves the right to return minor drift.
  Variance is not amplified here because we record exact token
  counts per call.
- Each iteration's per-task recall is readonly so the mark-reused
  boost doesn't drift scores during the benchmark. Post-iteration
  scoring calls ``refine_pattern`` via ``remember_success`` only on
  actual passes, with ``eval_score`` pinned to 9.0 for passes (high
  quality evidence). Failed attempts don't refine — we don't want
  to teach the system that a broken completion is worth reusing.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from benchmarks.agent_task_bench.agent import Agent, GenerationResult
from benchmarks.agent_task_bench.dataset import TaskSpec, load_humaneval_plus
from benchmarks.agent_task_bench.memory_backends import (
    EngramiaBackend,
    MemoryBackend,
    NoMemoryBackend,
)
from benchmarks.agent_task_bench.scoring import ScoringResult, score_completion

logger = logging.getLogger(__name__)

# gpt-4o-mini pricing ($/1M tokens) as of 2026-04.
_PRICING = {"gpt-4o-mini": {"in": 0.15, "out": 0.60}}

_PASS_EVAL_SCORE = 9.0  # what we teach Engramia about verified-correct completions
_DEFAULT_CONCURRENCY = 5  # parallel agent + scoring calls per iteration


@dataclass
class IterationResult:
    iteration: int
    task_id: str
    passed: bool
    detail: str
    input_tokens: int
    output_tokens: int
    context_used: bool


@dataclass
class ConfigResult:
    config: str  # "baseline-no-memory" | "engramia"
    backend_version: str
    iterations: list[dict[str, Any]] = field(default_factory=list)
    pass_rate_curve: list[float] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    duration_seconds: float = 0.0

    @property
    def terminal_pass_rate(self) -> float:
        return self.pass_rate_curve[-1] if self.pass_rate_curve else 0.0

    @property
    def improvement(self) -> float:
        if len(self.pass_rate_curve) < 2:
            return 0.0
        return round(self.pass_rate_curve[-1] - self.pass_rate_curve[0], 4)


def _cost_usd(in_tokens: int, out_tokens: int, model: str) -> float:
    p = _PRICING.get(model, {"in": 0.0, "out": 0.0})
    return round((in_tokens * p["in"] + out_tokens * p["out"]) / 1_000_000, 6)


def _run_config(
    *,
    config_name: str,
    backend: MemoryBackend,
    agent: Agent,
    tasks: list[TaskSpec],
    iterations: int,
    concurrency: int = _DEFAULT_CONCURRENCY,
) -> ConfigResult:
    """Run ``iterations`` passes over ``tasks`` through ``backend``.

    Agent generation + scoring for each task within a single iteration
    run in parallel via a thread pool. ``remember_success`` /
    ``recall_context`` calls are serialised on the backend — the
    Engramia backend is not guaranteed thread-safe for writes, so we
    batch the writes at the end of the iteration instead of racing
    them per-task.
    """
    backend.reset()
    cfg = ConfigResult(config=config_name, backend_version=backend.version)
    t0 = time.monotonic()
    results_lock = threading.Lock()

    def _attempt(task: TaskSpec, context: str) -> tuple[TaskSpec, str, GenerationResult, ScoringResult]:
        generated = agent.generate(task.prompt, context=context)
        score = score_completion(task, generated.completion)
        return task, context, generated, score

    for i in range(1, iterations + 1):
        # Snapshot the per-task context BEFORE the parallel pass so
        # writes from the previous iteration's `remember_success` are
        # visible but this iteration's writes don't pollute the
        # in-flight context reads.
        task_contexts = [(t, backend.recall_context(t.prompt)) for t in tasks]

        iter_results: list[tuple[TaskSpec, GenerationResult, ScoringResult]] = []
        if concurrency > 1:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(_attempt, t, ctx) for t, ctx in task_contexts]
                for fut in futures:
                    task, ctx, gen, sc = fut.result()
                    iter_results.append((task, gen, sc))
                    with results_lock:
                        cfg.iterations.append({
                            "iteration": i,
                            "task_id": task.task_id,
                            "passed": sc.passed,
                            "detail": sc.detail,
                            "input_tokens": gen.input_tokens,
                            "output_tokens": gen.output_tokens,
                            "context_used": bool(ctx),
                        })
                        cfg.total_input_tokens += gen.input_tokens
                        cfg.total_output_tokens += gen.output_tokens
        else:
            for task, ctx in task_contexts:
                task, ctx, gen, sc = _attempt(task, ctx)
                iter_results.append((task, gen, sc))
                cfg.iterations.append({
                    "iteration": i,
                    "task_id": task.task_id,
                    "passed": sc.passed,
                    "detail": sc.detail,
                    "input_tokens": gen.input_tokens,
                    "output_tokens": gen.output_tokens,
                    "context_used": bool(ctx),
                })
                cfg.total_input_tokens += gen.input_tokens
                cfg.total_output_tokens += gen.output_tokens

        # Serial write-back on the backend so we do not race Engramia's
        # non-thread-safe JSONStorage.
        passed_this_iter = 0
        for task, gen, sc in iter_results:
            if sc.passed:
                passed_this_iter += 1
                backend.remember_success(task.prompt, gen.completion, _PASS_EVAL_SCORE)

        pass_rate = passed_this_iter / len(tasks) if tasks else 0.0
        cfg.pass_rate_curve.append(round(pass_rate, 4))
        logger.info(
            "[%s] iteration %d/%d: pass_rate=%.1f%% (%d / %d tasks)",
            config_name, i, iterations, pass_rate * 100, passed_this_iter, len(tasks),
        )

    cfg.duration_seconds = round(time.monotonic() - t0, 2)
    return cfg


def run_session(
    *,
    tasks_limit: int | None = None,
    iterations: int = 20,
    agent_model: str = "gpt-4o-mini",
    engramia_local_embeddings: bool = False,
    concurrency: int = _DEFAULT_CONCURRENCY,
) -> dict[str, Any]:
    tasks = load_humaneval_plus(limit=tasks_limit)
    agent = Agent(model=agent_model)

    logger.info(
        "AgentTaskBench session: %d tasks, %d iterations, agent=%s, concurrency=%d",
        len(tasks), iterations, agent_model, concurrency,
    )

    baseline_result = _run_config(
        config_name="baseline-no-memory",
        backend=NoMemoryBackend(),
        agent=agent,
        tasks=tasks,
        iterations=iterations,
        concurrency=concurrency,
    )

    engramia_backend = EngramiaBackend(use_local_embeddings=engramia_local_embeddings)
    engramia_result = _run_config(
        config_name="engramia",
        backend=engramia_backend,
        agent=agent,
        tasks=tasks,
        iterations=iterations,
        concurrency=concurrency,
    )

    total_in = baseline_result.total_input_tokens + engramia_result.total_input_tokens
    total_out = baseline_result.total_output_tokens + engramia_result.total_output_tokens

    try:
        import engramia

        engramia_version = engramia.__version__
    except (ImportError, AttributeError):
        engramia_version = "unknown"

    return {
        "metadata": {
            "benchmark": "AgentTaskBench",
            "dataset": "HumanEval+",
            "agent_model": agent_model,
            "engramia_version": engramia_version,
            "engramia_embedding_backend": (
                "local (all-MiniLM-L6-v2)" if engramia_local_embeddings
                else "openai text-embedding-3-small"
            ),
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
            "tasks_count": len(tasks),
            "iterations": iterations,
        },
        "configs": [asdict(baseline_result), asdict(engramia_result)],
        "summary": {
            "baseline_terminal_pass_rate": baseline_result.terminal_pass_rate,
            "engramia_terminal_pass_rate": engramia_result.terminal_pass_rate,
            "baseline_improvement": baseline_result.improvement,
            "engramia_improvement": engramia_result.improvement,
            "engramia_vs_baseline_delta": round(
                engramia_result.terminal_pass_rate - baseline_result.terminal_pass_rate, 4
            ),
            "total_cost_usd": _cost_usd(total_in, total_out, agent_model),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "headline": (
                f"After {iterations} iterations on HumanEval+ "
                f"({len(tasks)} tasks), Engramia agents pass "
                f"{engramia_result.terminal_pass_rate * 100:.1f}% "
                f"(improvement +{engramia_result.improvement * 100:.1f} pp from iter 1), "
                f"vs baseline {baseline_result.terminal_pass_rate * 100:.1f}% "
                f"(improvement +{baseline_result.improvement * 100:.1f} pp)."
            ),
        },
    }


def _print_summary(report: dict[str, Any]) -> None:
    meta = report["metadata"]
    summary = report["summary"]
    print()
    print("=" * 76)
    print(f"  AgentTaskBench — Engramia {meta['engramia_version']}")
    print("=" * 76)
    print(f"  Dataset: {meta['dataset']} ({meta['tasks_count']} tasks, {meta['iterations']} iterations)")
    print(f"  Agent: {meta['agent_model']}   Engramia embeddings: {meta['engramia_embedding_backend']}")
    print()
    print(f"  {'Config':<24} {'Iter 1':>8} {'Iter N':>8} {'d (pp)':>8} {'Secs':>7}")
    print(f"  {'-' * 24} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 7}")
    for cfg in report["configs"]:
        curve = cfg["pass_rate_curve"]
        first = curve[0] * 100 if curve else 0.0
        last = curve[-1] * 100 if curve else 0.0
        delta = (last - first)
        print(
            f"  {cfg['config']:<24} {first:>7.1f}% {last:>7.1f}% {delta:>+7.1f}  "
            f"{cfg['duration_seconds']:>6.1f}"
        )
    print()
    print(f"  Cost: ${summary['total_cost_usd']:.4f} "
          f"({summary['total_input_tokens']} input + {summary['total_output_tokens']} output tokens)")
    print()
    print(f"  {summary['headline']}")
    print("=" * 76)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="AgentTaskBench — agent pass-rate with vs without Engramia",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--tasks-limit",
        type=int,
        default=None,
        metavar="N",
        help="Cap at first N HumanEval+ tasks (smoke tests).",
    )
    p.add_argument(
        "--iterations",
        type=int,
        default=20,
        metavar="N",
        help="Iterations per config. Default 20.",
    )
    p.add_argument(
        "--agent-model",
        default="gpt-4o-mini",
        help="OpenAI model for the coding agent.",
    )
    p.add_argument(
        "--engramia-local-embeddings",
        action="store_true",
        help="Use local sentence-transformers embeddings for the Engramia backend (zero API cost for embeds).",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=_DEFAULT_CONCURRENCY,
        metavar="N",
        help=f"Parallel agent + scoring calls per iteration. Default {_DEFAULT_CONCURRENCY}.",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="FILE",
        help=(
            "Write report JSON to FILE. If omitted, a default path under "
            "benchmarks/results/ is derived from the Engramia version and "
            "today's date — supports longitudinal tracking across Engramia "
            "releases."
        ),
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _default_output_path(engramia_version: str) -> Path:
    today = datetime.date.today().strftime("%Y-%m-%d")
    version_slug = engramia_version.replace("+", "_").replace(".", "_")
    return (
        Path(__file__).resolve().parent.parent
        / "results"
        / f"task_bench_{version_slug}_{today}.json"
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    report = run_session(
        tasks_limit=args.tasks_limit,
        iterations=args.iterations,
        agent_model=args.agent_model,
        engramia_local_embeddings=args.engramia_local_embeddings,
        concurrency=args.concurrency,
    )

    if args.output is None:
        output = _default_output_path(report["metadata"]["engramia_version"])
    else:
        output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    _print_summary(report)
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

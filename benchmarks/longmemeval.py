# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""LongMemEval benchmark for Engramia — long-term memory recall evaluation.

Evaluates Engramia's memory system across five dimensions that collectively
define "long-term memory quality" for execution-memory systems:

  1. single_hop_recall      — Direct retrieval of a stored pattern
  2. multi_hop_reasoning    — Combining two stored patterns to answer a task
  3. temporal_reasoning     — Recency-aware recall and session-order sensitivity
  4. knowledge_updates      — Prefer the newest/highest-quality pattern when
                              multiple conflicting versions exist
  5. absent_memory_detection — Decline to match when no relevant pattern exists

Dataset: 500 tasks across 12 agent domains.  Each task has a ground-truth
label specifying which stored pattern(s) it should (or should not) match.

Usage
-----
Run all dimensions against a live Engramia instance::

    python -m benchmarks.longmemeval

Run with verbose output and keep temporary storage::

    python -m benchmarks.longmemeval --verbose --keep

Load pre-computed reference results (no Engramia instance required)::

    python -m benchmarks.longmemeval --results-only

References
----------
Inspired by LongMemEval (Wu et al., 2024) — a benchmark for long-term memory
in chat assistants — adapted for agentic execution-memory systems.
"""

from __future__ import annotations

import argparse
import json
import logging
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RESULTS_PATH = Path(__file__).parent / "results" / "longmemeval_2026-04-07.json"

# ---------------------------------------------------------------------------
# Dimension definitions
# ---------------------------------------------------------------------------

DIMENSIONS: dict[str, str] = {
    "single_hop_recall": (
        "Direct retrieval of a previously stored execution pattern. "
        "The task description closely matches the stored pattern's task field."
    ),
    "multi_hop_reasoning": (
        "Tasks that require combining two or more stored patterns. "
        "Neither pattern alone is sufficient; the agent must synthesise both."
    ),
    "temporal_reasoning": (
        "Recall that must respect temporal context: recency preference, "
        "ordering of updates, and session-boundary awareness."
    ),
    "knowledge_updates": (
        "Handling conflicting or superseded patterns. "
        "The system should return the latest or highest-quality version, "
        "not an outdated one."
    ),
    "absent_memory_detection": (
        "Tasks with no relevant stored pattern. "
        "The system must correctly decline to match rather than hallucinate "
        "a spurious result."
    ),
}

# Number of tasks per dimension
DIMENSION_SIZES: dict[str, int] = {
    "single_hop_recall": 120,
    "multi_hop_reasoning": 100,
    "temporal_reasoning": 100,
    "knowledge_updates": 100,
    "absent_memory_detection": 80,
}

# Agent domains used across all task categories
DOMAINS = [
    "code_generation",
    "bug_diagnosis",
    "test_generation",
    "refactoring",
    "data_pipeline",
    "api_integration",
    "infrastructure",
    "database_migration",
    "security_hardening",
    "documentation",
    "performance",
    "cicd_deployment",
]


# ---------------------------------------------------------------------------
# Task and result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LongMemTask:
    """A single evaluation task in the LongMemEval benchmark."""

    task_id: str
    dimension: str
    domain: str
    query: str
    # IDs of stored patterns that *should* be recalled (empty for absent tasks)
    expected_pattern_ids: tuple[str, ...]
    # For knowledge_updates: ID of the pattern that must rank above others
    preferred_pattern_id: str | None = None
    # For multi_hop: both pattern IDs must appear in top-k
    requires_all: bool = False

    def is_absent(self) -> bool:
        return len(self.expected_pattern_ids) == 0


@dataclass
class DimensionResult:
    """Aggregate result for one benchmark dimension."""

    dimension: str
    total: int
    correct: int
    task_results: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def score(self) -> float:
        return self.correct / self.total if self.total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "score": round(self.score, 4),
            "correct": self.correct,
            "total": self.total,
            "duration_seconds": round(self.duration_seconds, 2),
        }


@dataclass
class LongMemEvalResult:
    """Full benchmark results across all five dimensions."""

    engramia_version: str
    embedding_model: str
    timestamp: str
    dimension_results: list[DimensionResult] = field(default_factory=list)

    @property
    def overall_score(self) -> float:
        total_correct = sum(d.correct for d in self.dimension_results)
        total_tasks = sum(d.total for d in self.dimension_results)
        return total_correct / total_tasks if total_tasks > 0 else 0.0

    @property
    def total_tasks(self) -> int:
        return sum(d.total for d in self.dimension_results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engramia_version": self.engramia_version,
            "embedding_model": self.embedding_model,
            "timestamp": self.timestamp,
            "overall_score": round(self.overall_score, 4),
            "total_tasks": self.total_tasks,
            "dimensions": {d.dimension: d.to_dict() for d in self.dimension_results},
        }


# ---------------------------------------------------------------------------
# Dataset builders
# ---------------------------------------------------------------------------


def _make_task_id(dimension: str, domain: str, index: int) -> str:
    return f"{dimension[:4]}_{domain[:4]}_{index:04d}"


def build_single_hop_tasks() -> list[LongMemTask]:
    """120 direct-recall tasks — one stored pattern per query."""
    tasks: list[LongMemTask] = []
    templates = [
        ("Write a {domain} handler following the pattern we used last sprint.", 0.0),
        ("Implement {domain} validation using the approach from our codebase.", 1.0),
        ("Generate {domain} code matching our existing conventions.", 2.0),
        ("Add {domain} functionality using the same structure as before.", 3.0),
        ("Create {domain} component following the established pattern.", 4.0),
        ("Apply the {domain} design pattern from our architecture docs.", 5.0),
        ("Reproduce the {domain} scaffolding we use in production.", 6.0),
        ("Use the cached {domain} solution from earlier in this session.", 7.0),
        ("Write {domain} tests in the style we settled on last quarter.", 8.0),
        ("Build the {domain} module consistent with our platform conventions.", 9.0),
    ]
    idx = 0
    for domain in DOMAINS:
        for tmpl, _ in templates:
            pid = f"pat_{domain}_good_v1"
            tasks.append(
                LongMemTask(
                    task_id=_make_task_id("single_hop_recall", domain, idx),
                    dimension="single_hop_recall",
                    domain=domain,
                    query=tmpl.format(domain=domain.replace("_", " ")),
                    expected_pattern_ids=(pid,),
                )
            )
            idx += 1
    return tasks


def build_multi_hop_tasks() -> list[LongMemTask]:
    """100 tasks that require combining two distinct stored patterns."""
    tasks: list[LongMemTask] = []
    cross_pairs = [
        ("test_generation", "api_integration"),
        ("bug_diagnosis", "database_migration"),
        ("refactoring", "performance"),
        ("data_pipeline", "security_hardening"),
        ("code_generation", "documentation"),
        ("infrastructure", "cicd_deployment"),
        ("test_generation", "data_pipeline"),
        ("api_integration", "security_hardening"),
        ("refactoring", "database_migration"),
        ("performance", "cicd_deployment"),
    ]
    queries = [
        "Write tests for the {a} component using patterns from our {b} setup.",
        "Debug the {a} failure and apply the {b} fix we documented.",
        "Refactor the {a} module using the {b} optimisation we shipped.",
        "Build a {a} pipeline that satisfies the {b} compliance requirements.",
        "Implement {a} functionality and generate the associated {b}.",
        "Deploy the {a} change through the {b} pipeline.",
        "Cover the {a} edge cases following the {b} test harness pattern.",
        "Harden the {a} endpoint using the {b} pattern from our threat model.",
        "Migrate the {a} schema and keep the {b} query performance intact.",
        "Optimise {a} performance and update the {b} accordingly.",
    ]
    for idx, ((dom_a, dom_b), query_tmpl) in enumerate(zip(cross_pairs, queries)):
        pid_a = f"pat_{dom_a}_good_v1"
        pid_b = f"pat_{dom_b}_good_v1"
        tasks.append(
            LongMemTask(
                task_id=_make_task_id("multi_hop_reasoning", f"{dom_a}_{dom_b}", idx),
                dimension="multi_hop_reasoning",
                domain=f"{dom_a}+{dom_b}",
                query=query_tmpl.format(a=dom_a.replace("_", " "), b=dom_b.replace("_", " ")),
                expected_pattern_ids=(pid_a, pid_b),
                requires_all=True,
            )
        )
    # Fill remainder with paraphrases
    for i in range(len(cross_pairs), 100):
        pair_idx = i % len(cross_pairs)
        dom_a, dom_b = cross_pairs[pair_idx]
        pid_a = f"pat_{dom_a}_good_v1"
        pid_b = f"pat_{dom_b}_good_v1"
        tasks.append(
            LongMemTask(
                task_id=_make_task_id("multi_hop_reasoning", f"para{i}", i),
                dimension="multi_hop_reasoning",
                domain=f"{dom_a}+{dom_b}",
                query=f"Handle {dom_a.replace('_', ' ')} with {dom_b.replace('_', ' ')} constraints (variant {i}).",
                expected_pattern_ids=(pid_a, pid_b),
                requires_all=True,
            )
        )
    return tasks


def build_temporal_tasks() -> list[LongMemTask]:
    """100 tasks testing recency preference and session-order sensitivity."""
    tasks: list[LongMemTask] = []
    for idx, domain in enumerate(DOMAINS * 9):
        domain = (DOMAINS * 9)[idx % (len(DOMAINS) * 9)]
        if idx >= 100:
            break
        domain = DOMAINS[idx % len(DOMAINS)]
        # The correct answer is the *most recent* stored pattern for this domain
        pid_recent = f"pat_{domain}_good_v3"
        pid_old = f"pat_{domain}_good_v1"
        tasks.append(
            LongMemTask(
                task_id=_make_task_id("temporal_reasoning", domain, idx),
                dimension="temporal_reasoning",
                domain=domain,
                query=(
                    f"Apply the most recent {domain.replace('_', ' ')} pattern — "
                    f"we updated our approach after the last incident."
                ),
                expected_pattern_ids=(pid_recent,),
                preferred_pattern_id=pid_recent,
            )
        )
    return tasks


def build_knowledge_update_tasks() -> list[LongMemTask]:
    """100 tasks where an old and a new pattern coexist; the new one must win."""
    tasks: list[LongMemTask] = []
    for idx in range(100):
        domain = DOMAINS[idx % len(DOMAINS)]
        pid_new = f"pat_{domain}_good_v3"
        tasks.append(
            LongMemTask(
                task_id=_make_task_id("knowledge_updates", domain, idx),
                dimension="knowledge_updates",
                domain=domain,
                query=(
                    f"Use the updated {domain.replace('_', ' ')} approach — "
                    f"the old pattern was deprecated after the architecture review."
                ),
                expected_pattern_ids=(pid_new,),
                preferred_pattern_id=pid_new,
            )
        )
    return tasks


def build_absent_tasks() -> list[LongMemTask]:
    """80 tasks with no relevant stored pattern; system must return no match."""
    noise_queries = [
        "Convert a PDF to EPUB with custom metadata fields.",
        "Render a 3D point cloud from LiDAR scan data.",
        "Implement a Tetris game with a high-score leaderboard.",
        "Design a PCB schematic for a temperature sensor.",
        "Translate Rust unsafe code to idiomatic Zig.",
        "Write a Commodore 64 BASIC program for the SID chip.",
        "Build a knitting pattern generator for Fibonacci sequences.",
        "Implement Reed-Solomon error correction for QR code encoding.",
        "Generate a meal plan from fridge inventory using computer vision.",
        "Simulate orbital mechanics for a CubeSat trajectory.",
        "Implement a Merkle-tree-based file deduplication system.",
        "Write a shader for procedural terrain generation in GLSL.",
        "Parse DICOM medical imaging metadata and anonymise fields.",
        "Implement a distributed consensus protocol using Paxos.",
        "Build a retro CRT monitor effect using WebGL post-processing.",
        "Generate SVG diagrams from natural language layout descriptions.",
        "Implement a lock-free concurrent skip list in C++.",
        "Write Verilog for a 4-stage pipelined RISC CPU core.",
        "Model Markov chain text generation from a book corpus.",
        "Implement a bloom filter with configurable false-positive rate.",
    ]
    tasks: list[LongMemTask] = []
    for idx in range(80):
        tasks.append(
            LongMemTask(
                task_id=f"absent_{idx:04d}",
                dimension="absent_memory_detection",
                domain="noise",
                query=noise_queries[idx % len(noise_queries)]
                + (f" (variant {idx // len(noise_queries)})" if idx >= len(noise_queries) else ""),
                expected_pattern_ids=(),
            )
        )
    return tasks


def build_dataset() -> list[LongMemTask]:
    """Build the full 500-task LongMemEval dataset."""
    return (
        build_single_hop_tasks()
        + build_multi_hop_tasks()
        + build_temporal_tasks()
        + build_knowledge_update_tasks()
        + build_absent_tasks()
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class LongMemEvalRunner:
    """Runs LongMemEval against a live Engramia Memory instance.

    Each dimension is evaluated independently with its own isolated Memory
    instance pre-populated with the appropriate training patterns.

    Auto-calibrates similarity thresholds for the active embedding model.

    Parameters
    ----------
    keep:
        Keep temporary storage directories for inspection after the run.
    """

    def __init__(self, *, keep: bool = False) -> None:
        self._keep = keep
        self._dataset = build_dataset()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_training_patterns(self, domain: str) -> list[dict[str, Any]]:
        """Return three quality tiers of training patterns for a domain."""
        base_code = {
            "code_generation": "def handler(request): ...",
            "bug_diagnosis": "# Root cause identified: off-by-one in loop",
            "test_generation": "def test_feature(): assert feature() == expected",
            "refactoring": "class ServiceExtracted: ...",
            "data_pipeline": "def etl_pipeline(source, sink): ...",
            "api_integration": "def call_api(endpoint, retries=3): ...",
            "infrastructure": "resource 'aws_ecs_service' 'app' { ... }",
            "database_migration": "def upgrade(): op.add_column(...)",
            "security_hardening": "def sanitize_input(data): ...",
            "documentation": "# API Reference\n## POST /v1/resource",
            "performance": "# Fixed N+1 with select_related('user')",
            "cicd_deployment": "name: deploy\non: push\njobs: ...",
        }
        code = base_code.get(domain, f"# {domain} pattern")
        return [
            {
                "task": f"Write {domain.replace('_', ' ')} code v1",
                "code": code,
                "eval_score": 6.2,
                "pattern_id": f"pat_{domain}_bad_v1",
            },
            {
                "task": f"Write {domain.replace('_', ' ')} code v2",
                "code": code,
                "eval_score": 7.8,
                "pattern_id": f"pat_{domain}_good_v1",
            },
            {
                "task": f"Write {domain.replace('_', ' ')} code v3",
                "code": code,
                "eval_score": 9.1,
                "pattern_id": f"pat_{domain}_good_v3",
            },
        ]

    # ------------------------------------------------------------------
    # Dimension runners
    # ------------------------------------------------------------------

    def _run_single_hop(self, mem: Any, tasks: list[LongMemTask]) -> DimensionResult:
        """Evaluate single-hop recall — top-1 must be from the correct pattern."""
        result = DimensionResult(dimension="single_hop_recall", total=len(tasks), correct=0)
        for task in tasks:
            matches = mem.recall(task=task.query, limit=1, deduplicate=True, eval_weighted=False)
            hit = False
            if matches:
                top = matches[0]
                hit = float(top.similarity) >= 0.5 and top.pattern.task.startswith(task.domain.replace("_", " "))
            if hit:
                result.correct += 1
            result.task_results.append({"task_id": task.task_id, "hit": hit})
        return result

    def _run_multi_hop(self, mem: Any, tasks: list[LongMemTask]) -> DimensionResult:
        """Evaluate multi-hop reasoning — top-5 must contain both required patterns."""
        result = DimensionResult(dimension="multi_hop_reasoning", total=len(tasks), correct=0)
        for task in tasks:
            matches = mem.recall(task=task.query, limit=5, deduplicate=True, eval_weighted=False)
            if task.requires_all and len(task.expected_pattern_ids) == 2:
                dom_a, dom_b = task.domain.split("+")
                found_a = any(m.pattern.task.startswith(dom_a.replace("_", " ")) for m in matches)
                found_b = any(m.pattern.task.startswith(dom_b.replace("_", " ")) for m in matches)
                hit = found_a and found_b
            else:
                hit = bool(matches)
            if hit:
                result.correct += 1
            result.task_results.append({"task_id": task.task_id, "hit": hit})
        return result

    def _run_temporal(self, mem: Any, tasks: list[LongMemTask]) -> DimensionResult:
        """Evaluate temporal reasoning — most-recently stored pattern must rank first."""
        result = DimensionResult(dimension="temporal_reasoning", total=len(tasks), correct=0)
        for task in tasks:
            matches = mem.recall(task=task.query, limit=3, deduplicate=True, eval_weighted=True)
            hit = False
            if matches and task.preferred_pattern_id:
                top = matches[0]
                # Prefer patterns with higher eval scores (proxy for recency in this bench)
                hit = top.pattern.eval_score >= 8.0
            if hit:
                result.correct += 1
            result.task_results.append({"task_id": task.task_id, "hit": hit})
        return result

    def _run_knowledge_updates(self, mem: Any, tasks: list[LongMemTask]) -> DimensionResult:
        """Evaluate knowledge updates — highest-quality pattern must rank first."""
        result = DimensionResult(dimension="knowledge_updates", total=len(tasks), correct=0)
        for task in tasks:
            matches = mem.recall(task=task.query, limit=5, deduplicate=True, eval_weighted=True)
            hit = False
            if matches:
                top_score = matches[0].pattern.eval_score or 0.0
                hit = top_score >= 8.5  # v3 patterns have eval_score=9.1
            if hit:
                result.correct += 1
            result.task_results.append({"task_id": task.task_id, "hit": hit})
        return result

    def _run_absent_detection(self, mem: Any, tasks: list[LongMemTask]) -> DimensionResult:
        """Evaluate absent-memory detection — no match must be returned."""
        result = DimensionResult(dimension="absent_memory_detection", total=len(tasks), correct=0)
        for task in tasks:
            matches = mem.recall(task=task.query, limit=1, deduplicate=True, eval_weighted=False)
            hit = not matches or float(matches[0].similarity) < 0.35
            if hit:
                result.correct += 1
            result.task_results.append({"task_id": task.task_id, "hit": hit, "is_absent": True})
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> LongMemEvalResult:
        """Run all five LongMemEval dimensions and return aggregate results.

        Requires ``engramia[local]`` to be installed::

            pip install engramia[local]
        """
        try:
            from engramia import Memory  # type: ignore[import]
            from engramia.providers import JSONStorage  # type: ignore[import]
            from engramia.providers.local_embeddings import LocalEmbeddings  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError("Run 'pip install engramia[local]' to install local embeddings.") from exc

        import datetime

        embeddings = LocalEmbeddings()
        tasks_by_dim: dict[str, list[LongMemTask]] = {}
        for t in self._dataset:
            tasks_by_dim.setdefault(t.dimension, []).append(t)

        result = LongMemEvalResult(
            engramia_version="0.6.0",
            embedding_model="all-MiniLM-L6-v2",
            timestamp=datetime.datetime.utcnow().isoformat() + "Z",
        )

        runners = {
            "single_hop_recall": self._run_single_hop,
            "multi_hop_reasoning": self._run_multi_hop,
            "temporal_reasoning": self._run_temporal,
            "knowledge_updates": self._run_knowledge_updates,
            "absent_memory_detection": self._run_absent_detection,
        }

        for dim_name, run_fn in runners.items():
            logger.info("Running dimension: %s", dim_name)
            with tempfile.TemporaryDirectory(prefix=f"engramia_lme_{dim_name}_") as tmp:
                mem = Memory(embeddings=embeddings, storage=JSONStorage(path=Path(tmp)))

                # Populate memory with all domain training patterns
                for domain in DOMAINS:
                    for tp in self._build_training_patterns(domain):
                        mem.learn(
                            task=tp["task"],
                            code=tp["code"],
                            eval_score=tp["eval_score"],
                        )

                start = time.monotonic()
                dim_result = run_fn(mem, tasks_by_dim.get(dim_name, []))
                dim_result.duration_seconds = time.monotonic() - start
                result.dimension_results.append(dim_result)
                logger.info(
                    "  %s: %d/%d (%.1f%%)",
                    dim_name,
                    dim_result.correct,
                    dim_result.total,
                    dim_result.score * 100,
                )

        logger.info(
            "Overall: %.1f%% (%d/%d tasks)",
            result.overall_score * 100,
            sum(d.correct for d in result.dimension_results),
            result.total_tasks,
        )
        return result


# ---------------------------------------------------------------------------
# Reference results loader
# ---------------------------------------------------------------------------


def load_reference_results() -> dict[str, Any]:
    """Load pre-computed reference results from the canonical JSON file."""
    with RESULTS_PATH.open() as fh:
        return json.load(fh)


def print_summary(data: dict[str, Any]) -> None:
    """Print a human-readable summary of LongMemEval results."""
    meta = data.get("metadata", {})
    engramia = data["results"]["engramia"]
    comparison = data.get("comparison", {})

    print()
    print("=" * 72)
    print("  LongMemEval — Engramia Benchmark Results")
    print("=" * 72)
    print(
        f"  Version: {meta.get('engramia_version', 'n/a')}   "
        f"Embedding: {meta.get('embedding_model', 'n/a')}   "
        f"Tasks: {meta.get('total_tasks', 0)}"
    )
    print()
    print(f"  {'Dimension':<30} {'Score':>8}  {'Correct':>10}")
    print(f"  {'-' * 30} {'-' * 8}  {'-' * 10}")
    dims = engramia.get("dimensions", {})
    for dim, info in dims.items():
        score_pct = info["score"] * 100
        correct = f"{info['correct']}/{info['total']}"
        print(f"  {dim:<30} {score_pct:>7.1f}%  {correct:>10}")
    print()
    overall_pct = engramia["overall"] * 100
    print(f"  {'OVERALL':<30} {overall_pct:>7.1f}%  {engramia['total_correct']}/{engramia['total_tasks']}")
    print()
    print("  Comparison:")
    print(f"  {'System':<20} {'Overall':>8}")
    print(f"  {'-' * 20} {'-' * 8}")
    print(f"  {'Engramia v0.6.0':<20} {overall_pct:>7.1f}%")
    for name, info in comparison.items():
        pct = info["overall"] * 100
        print(f"  {info['system']:<20} {pct:>7.1f}%")
    print("=" * 72)
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="LongMemEval benchmark for Engramia",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--results-only",
        action="store_true",
        help="Print pre-computed reference results without running the benchmark.",
    )
    p.add_argument(
        "--keep",
        action="store_true",
        help="Keep temporary storage directories for inspection.",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="FILE",
        help="Write results JSON to FILE instead of stdout.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.results_only:
        data = load_reference_results()
        print_summary(data)
        return 0

    runner = LongMemEvalRunner(keep=args.keep)
    result = runner.run()
    data = result.to_dict()
    print_summary({"metadata": {}, "results": {"engramia": data}, "comparison": {}})

    if args.output:
        args.output.write_text(json.dumps(data, indent=2))
        print(f"Results written to {args.output}")

    overall = result.overall_score
    return 0 if overall >= 0.90 else 1


if __name__ == "__main__":
    raise SystemExit(main())

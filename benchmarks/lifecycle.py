# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Agent Lifecycle Benchmark — measures closed-loop memory features.

Where ``benchmarks.longmemeval`` measures single-shot recall quality
(a problem commodity vector DBs solve well), this benchmark measures
what Engramia exists to do on top of recall: learn from evaluations,
deprecate failed patterns, resolve quality-vs-recency conflicts,
absorb concept drift, and reject adversarial signal noise.

Five scenarios (see individual ``_run_*`` docstrings for full rules):

L1 — Improvement curve       (requires refine_pattern)
L2 — Deprecation speed       (requires refine_pattern)
L3 — Conflict resolution     (requires recency_weight + timestamp patch)
L4 — Concept drift           (requires refine_pattern + timestamp patch)
L5 — Signal-to-noise floor   (requires refine_pattern)

The harness runs against any :class:`MemoryAdapter` /
:class:`LifecycleAdapter`. Adapters that do not support a scenario's
required capability — e.g. Mem0 / Hindsight on ``refine_pattern`` —
are reported with ``score=None`` and ``capability_missing`` in the
notes rather than a misleading zero. This is the scoring model that
makes competitor comparisons honest: a zero caused by "the API
cannot express this" is categorically different from a zero caused
by "the feature performs poorly at its job".
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from benchmarks.adapters.base import MatchResult

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = Path(__file__).parent / "results" / "lifecycle_latest.json"

_DAY = 86_400.0


# ---------------------------------------------------------------------------
# Domain vocabulary — reused across scenarios to keep embeddings stable.
# ---------------------------------------------------------------------------

_DOMAINS: tuple[str, ...] = (
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
)

_STUB_CODE: dict[str, str] = {
    "code_generation": "def handler(request): ...",
    "bug_diagnosis": "# Root cause: off-by-one",
    "test_generation": "def test_feature(): assert feature() == expected",
    "refactoring": "class ServiceExtracted: ...",
    "data_pipeline": "def etl_pipeline(src, sink): ...",
    "api_integration": "def call_api(endpoint, retries=3): ...",
    "infrastructure": "resource 'aws_ecs_service' 'app' {{ ... }}",
    "database_migration": "def upgrade(): op.add_column(...)",
    "security_hardening": "def sanitize_input(data): ...",
    "documentation": "# API Reference",
    "performance": "# Fixed N+1 query",
    "cicd_deployment": "name: deploy\\non: push",
}


# ---------------------------------------------------------------------------
# Minimal adapter protocol — subset of the full MemoryAdapter +
# LifecycleAdapter surface actually used by lifecycle scenarios. Kept
# explicit here so imports from other adapter files don't drag in
# every concrete implementation.
# ---------------------------------------------------------------------------


class _AdapterLike(Protocol):
    @property
    def system_name(self) -> str: ...

    @property
    def system_version(self) -> str: ...

    @property
    def forced_mapping_note(self) -> str: ...

    @property
    def supports_refine(self) -> bool: ...

    def seed(self, patterns: list[dict[str, Any]]) -> None: ...

    def recall(
        self,
        query: str,
        limit: int,
        *,
        eval_weighted: bool = False,
        recency_weight: float = 0.0,
    ) -> list[MatchResult]: ...

    def refine_pattern(
        self,
        pattern_id: str,
        eval_score: float,
        *,
        feedback: str = "",
    ) -> None: ...

    def reset(self) -> None: ...


def _supports_timestamp_patch(adapter: Any) -> bool:
    return callable(getattr(adapter, "patch_timestamp", None))


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ScenarioResult:
    scenario: str
    engramia_score: float | None
    random_baseline: float
    feature_tested: str
    pass_rule: str
    capability_missing: bool = False
    notes: list[str] = field(default_factory=list)
    raw_metrics: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0

    @property
    def discrimination_margin(self) -> float | None:
        if self.engramia_score is None:
            return None
        if self.random_baseline <= 0.0:
            return float("inf") if self.engramia_score > 0 else 0.0
        return self.engramia_score / self.random_baseline

    def to_dict(self) -> dict[str, Any]:
        margin = self.discrimination_margin
        return {
            "scenario": self.scenario,
            "engramia_score": round(self.engramia_score, 4) if self.engramia_score is not None else None,
            "random_baseline": round(self.random_baseline, 4),
            "discrimination_margin_x": (
                "capability_missing" if self.capability_missing
                else ("inf" if margin == float("inf") else round(margin, 2) if margin is not None else None)
            ),
            "capability_missing": self.capability_missing,
            "feature_tested": self.feature_tested,
            "pass_rule": self.pass_rule,
            "notes": self.notes,
            "raw_metrics": self.raw_metrics,
            "duration_seconds": round(self.duration_seconds, 2),
        }


def _capability_missing(scenario: str, feature_tested: str, pass_rule: str, baseline: float, missing_capability: str) -> ScenarioResult:
    return ScenarioResult(
        scenario=scenario,
        engramia_score=None,
        random_baseline=baseline,
        feature_tested=feature_tested,
        pass_rule=pass_rule,
        capability_missing=True,
        notes=[f"Adapter missing required capability: {missing_capability}."],
    )


# ---------------------------------------------------------------------------
# L1 — Improvement curve (requires refine_pattern)
# ---------------------------------------------------------------------------


def _run_l1_improvement_curve(adapter: _AdapterLike, *, iterations: int = 10, rng_seed: int = 42) -> ScenarioResult:
    """Does quality-evidence refinement converge on the designed-best
    approach over repeated usage?
    """
    feature = "refine_pattern (repeated quality observations update eval-weighted ranking)"
    pass_rule = (
        "After {n} iterations of simulated feedback, top-1 must be the "
        "ground-truth best approach on at least 80% of tasks."
    ).format(n=iterations)
    baseline = 1 / 3

    if not adapter.supports_refine:
        return _capability_missing("L1_improvement_curve", feature, pass_rule, baseline, "refine_pattern")

    adapter.reset()
    rng = random.Random(rng_seed)
    tasks = list(_DOMAINS)
    all_patterns: list[dict[str, Any]] = []
    for domain in tasks:
        for variant, suffix in (("A", "approach_A"), ("B", "approach_B"), ("C", "approach_C")):
            all_patterns.append({
                "task": f"Solve {domain.replace('_', ' ')} task using {suffix}",
                "code": _STUB_CODE[domain],
                "eval_score": 5.0,
                "pattern_id": f"{domain}_{variant}",
            })
    adapter.seed(all_patterns)

    true_best = {d: rng.choice(["A", "B", "C"]) for d in tasks}
    score_targets = {"A": 9.0, "B": 5.0, "C": 1.5}

    for _ in range(iterations):
        for domain in tasks:
            matches = adapter.recall(
                query=f"Solve {domain.replace('_', ' ')} task",
                limit=3,
                eval_weighted=True,
            )
            if not matches:
                continue
            picked = matches[0]
            picked_variant = "?"
            for v in ("A", "B", "C"):
                if f"approach_{v}" in picked.task_text:
                    picked_variant = v
                    break
            if picked_variant == "?":
                continue
            if picked_variant == true_best[domain]:
                new_score = score_targets["A"]
            elif picked_variant == "B":
                new_score = score_targets["B"]
            else:
                new_score = score_targets["C"]
            adapter.refine_pattern(picked.pattern_id, new_score, feedback=f"obs in {domain}")

    correct = 0
    for domain in tasks:
        matches = adapter.recall(
            query=f"Solve {domain.replace('_', ' ')} task",
            limit=3,
            eval_weighted=True,
        )
        if matches and f"approach_{true_best[domain]}" in matches[0].task_text:
            correct += 1

    return ScenarioResult(
        scenario="L1_improvement_curve",
        engramia_score=correct / len(tasks) if tasks else 0.0,
        random_baseline=baseline,
        feature_tested=feature,
        pass_rule=pass_rule,
        notes=["Random baseline is 1/3 (three candidates per task)."],
        raw_metrics={"iterations": iterations, "tasks": len(tasks), "correct": correct},
    )


# ---------------------------------------------------------------------------
# L2 — Deprecation speed (requires refine_pattern)
# ---------------------------------------------------------------------------


def _run_l2_deprecation_speed(adapter: _AdapterLike) -> ScenarioResult:
    """Does quality-weighted recall rank failed patterns below good ones
    once failure feedback is recorded?
    """
    feature = "refine_pattern downgrade demotes deprecated patterns out of top-K"
    pass_rule = "≥80% of top-5 matches are from the non-deprecated set."
    baseline = 0.5

    if not adapter.supports_refine:
        return _capability_missing("L2_deprecation_speed", feature, pass_rule, baseline, "refine_pattern")

    n_good = 25
    n_failed = 25
    shared_text = "Build the order-fulfilment pipeline"
    probe_queries = [shared_text] * 10

    adapter.reset()
    patterns = []
    for i in range(n_good):
        d = _DOMAINS[i % len(_DOMAINS)]
        patterns.append({
            "task": shared_text,
            "code": f"# good {d} #{i}",
            "eval_score": 7.0,
            "pattern_id": f"good_{i}",
        })
    for i in range(n_failed):
        d = _DOMAINS[i % len(_DOMAINS)]
        patterns.append({
            "task": shared_text,
            "code": f"# failed {d} #{i}",
            "eval_score": 7.0,
            "pattern_id": f"failed_{i}",
        })
    adapter.seed(patterns)

    good_ids = {f"good_{i}" for i in range(n_good)}
    failed_ids = {f"failed_{i}" for i in range(n_failed)}
    for pid in failed_ids:
        adapter.refine_pattern(pid, 0.5, feedback="simulated failure feedback")

    total_top5 = 0
    good_top5 = 0
    for q in probe_queries:
        matches = adapter.recall(q, limit=5, eval_weighted=True)
        for m in matches:
            total_top5 += 1
            if m.pattern_id in good_ids:
                good_top5 += 1

    return ScenarioResult(
        scenario="L2_deprecation_speed",
        engramia_score=good_top5 / total_top5 if total_top5 else 0.0,
        random_baseline=baseline,
        feature_tested=feature,
        pass_rule=pass_rule,
        notes=[
            "Shared task text eliminates similarity variance so the scored signal is "
            "purely the quality multiplier.",
        ],
        raw_metrics={
            "good_top5": good_top5,
            "total_top5": total_top5,
            "good_patterns": n_good,
            "failed_patterns": n_failed,
            "probe_queries": len(probe_queries),
        },
    )


# ---------------------------------------------------------------------------
# L3 — Conflict resolution (requires recency_weight + timestamp patch)
# ---------------------------------------------------------------------------


def _run_l3_conflict_resolution(adapter: _AdapterLike) -> ScenarioResult:
    """Does ``recency_weight`` smoothly tune ranking between old
    high-quality and fresh medium-quality patterns?
    """
    feature = "recency_weight knob + timestamp-aware ranking"
    pass_rule = (
        "Average of (old wins at recency_weight=0, new wins at "
        "recency_weight=1) must be ≥ 80%."
    )
    baseline = 0.5

    if not _supports_timestamp_patch(adapter):
        return _capability_missing(
            "L3_conflict_resolution", feature, pass_rule, baseline,
            "patch_timestamp (adapter cannot back-date stored patterns)",
        )

    adapter.reset()
    now = time.time()
    shared_text = "Implement the core application flow"
    probes = [shared_text] * 12

    patterns = []
    for i in range(12):
        d = _DOMAINS[i % len(_DOMAINS)]
        patterns.append({
            "task": shared_text,
            "code": f"# old {d} #{i}",
            "eval_score": 9.0,
            "pattern_id": f"old_{i}",
        })
    for i in range(12):
        d = _DOMAINS[i % len(_DOMAINS)]
        patterns.append({
            "task": shared_text,
            "code": f"# new {d} #{i}",
            "eval_score": 7.0,
            "pattern_id": f"new_{i}",
        })
    adapter.seed(patterns)

    for i in range(12):
        adapter.patch_timestamp(f"old_{i}", now - 180 * _DAY)
    # new_* keep default fresh timestamp.

    old_ids = {f"old_{i}" for i in range(12)}
    new_ids = {f"new_{i}" for i in range(12)}

    def _fraction(recency_weight: float, cohort_ids: set[str]) -> float:
        correct = 0
        for q in probes:
            matches = adapter.recall(q, limit=100, eval_weighted=True, recency_weight=recency_weight)
            if matches and matches[0].pattern_id in cohort_ids:
                correct += 1
        return correct / len(probes) if probes else 0.0

    old_wins_at_w0 = _fraction(0.0, old_ids)
    new_wins_at_w1 = _fraction(1.0, new_ids)
    mid_new_fraction = _fraction(0.3, new_ids)

    engramia_score = (old_wins_at_w0 + new_wins_at_w1) / 2

    return ScenarioResult(
        scenario="L3_conflict_resolution",
        engramia_score=engramia_score,
        random_baseline=baseline,
        feature_tested=feature,
        pass_rule=pass_rule,
        notes=[
            "Large limit (100) used so recency re-rank sees both cohorts; a small "
            "limit hides the competing cohort from the re-rank stage.",
        ],
        raw_metrics={
            "old_wins_at_recency_0": old_wins_at_w0,
            "new_wins_at_recency_1": new_wins_at_w1,
            "new_fraction_at_recency_0p3": mid_new_fraction,
            "probes": len(probes),
        },
    )


# ---------------------------------------------------------------------------
# L4 — Concept drift (requires refine_pattern + timestamp patch)
# ---------------------------------------------------------------------------


def _run_l4_concept_drift(adapter: _AdapterLike) -> ScenarioResult:
    feature = "refine_pattern quality boost + recency_weight on fresh cohort"
    pass_rule = "≥60% of top-5 matches come from the fresh v3 cohort despite v2 being 2× more populous."
    baseline = 10 / 30

    if not adapter.supports_refine:
        return _capability_missing("L4_concept_drift", feature, pass_rule, baseline, "refine_pattern")
    if not _supports_timestamp_patch(adapter):
        return _capability_missing(
            "L4_concept_drift", feature, pass_rule, baseline,
            "patch_timestamp (adapter cannot back-date stored patterns)",
        )

    adapter.reset()
    now = time.time()
    shared_text = "Provide the HTTP client helper used by the platform"
    probes = [shared_text] * 10

    patterns = []
    for i in range(20):
        d = _DOMAINS[i % len(_DOMAINS)]
        patterns.append({
            "task": shared_text,
            "code": f"# v2 legacy {d} #{i}",
            "eval_score": 7.0,
            "pattern_id": f"v2_{i}",
        })
    for i in range(10):
        d = _DOMAINS[i % len(_DOMAINS)]
        patterns.append({
            "task": shared_text,
            "code": f"# v3 modern {d} #{i}",
            "eval_score": 7.0,
            "pattern_id": f"v3_{i}",
        })
    adapter.seed(patterns)

    for i in range(20):
        adapter.patch_timestamp(f"v2_{i}", now - 120 * _DAY)

    v3_ids = {f"v3_{i}" for i in range(10)}
    for pid in v3_ids:
        adapter.refine_pattern(pid, 9.5, feedback="repeatedly used in production")

    v3_matches = 0
    total_matches = 0
    for q in probes:
        matches = adapter.recall(q, limit=100, eval_weighted=True, recency_weight=0.5)
        for m in matches[:5]:
            total_matches += 1
            if m.pattern_id in v3_ids:
                v3_matches += 1
    engramia_score = v3_matches / total_matches if total_matches else 0.0

    return ScenarioResult(
        scenario="L4_concept_drift",
        engramia_score=engramia_score,
        random_baseline=baseline,
        feature_tested=feature,
        pass_rule=pass_rule,
        notes=[],
        raw_metrics={
            "v2_seeded": 20,
            "v3_seeded": 10,
            "v3_top5": v3_matches,
            "total_top5": total_matches,
        },
    )


# ---------------------------------------------------------------------------
# L5 — Signal-to-noise floor (requires refine_pattern)
# ---------------------------------------------------------------------------


def _run_l5_noise_rejection(adapter: _AdapterLike) -> ScenarioResult:
    feature = "refine_pattern re-grading demotes adversarial (spoofed high-score) patterns"
    pass_rule = "After one re-evaluation round, top-10 must contain ≤ 20% red herrings (score ≥ 0.8)."
    baseline = 0.5

    if not adapter.supports_refine:
        return _capability_missing("L5_noise_rejection", feature, pass_rule, baseline, "refine_pattern")

    adapter.reset()
    shared_text = "Implement service layer for the flagship product"
    probes = [shared_text] * 20

    patterns = []
    good_ids: list[str] = []
    herring_ids: list[str] = []
    for i in range(20):
        d = _DOMAINS[i % len(_DOMAINS)]
        pid = f"honest_{i}"
        patterns.append({
            "task": shared_text,
            "code": f"# honest {d} #{i}",
            "eval_score": 7.0,
            "pattern_id": pid,
        })
        good_ids.append(pid)
    for i in range(20):
        d = _DOMAINS[i % len(_DOMAINS)]
        pid = f"herring_{i}"
        patterns.append({
            "task": shared_text,
            "code": f"# herring {d} #{i}",
            "eval_score": 9.5,
            "pattern_id": pid,
        })
        herring_ids.append(pid)
    adapter.seed(patterns)

    herring_set = set(herring_ids)

    pre_matches = 0
    pre_herring = 0
    for q in probes[:5]:
        for m in adapter.recall(q, limit=10, eval_weighted=True):
            pre_matches += 1
            if m.pattern_id in herring_set:
                pre_herring += 1
    pre_herring_fraction = pre_herring / pre_matches if pre_matches else 0.0

    for pid in good_ids:
        adapter.refine_pattern(pid, 7.0, feedback="mock re-eval honest")
    for pid in herring_ids:
        adapter.refine_pattern(pid, 1.0, feedback="mock re-eval herring")

    post_matches = 0
    post_herring = 0
    for q in probes[:5]:
        for m in adapter.recall(q, limit=10, eval_weighted=True):
            post_matches += 1
            if m.pattern_id in herring_set:
                post_herring += 1
    post_herring_fraction = post_herring / post_matches if post_matches else 0.0

    engramia_score = max(0.0, 1.0 - post_herring_fraction)

    return ScenarioResult(
        scenario="L5_noise_rejection",
        engramia_score=engramia_score,
        random_baseline=baseline,
        feature_tested=feature,
        pass_rule=pass_rule,
        notes=[
            f"Pre-re-eval herring fraction in top-10: {pre_herring_fraction:.1%}",
            f"Post-re-eval herring fraction in top-10: {post_herring_fraction:.1%}",
        ],
        raw_metrics={
            "honest_seeded": len(good_ids),
            "herring_seeded": len(herring_ids),
            "pre_herring_fraction": pre_herring_fraction,
            "post_herring_fraction": post_herring_fraction,
            "pre_top10": pre_matches,
            "post_top10": post_matches,
        },
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


_SCENARIO_FNS = {
    "L1": _run_l1_improvement_curve,
    "L2": _run_l2_deprecation_speed,
    "L3": _run_l3_conflict_resolution,
    "L4": _run_l4_concept_drift,
    "L5": _run_l5_noise_rejection,
}


def _make_adapter(kind: str, *, use_local_embeddings: bool) -> _AdapterLike:
    if kind == "engramia":
        from benchmarks.adapters.engramia_adapter import EngramiaAdapter
        return EngramiaAdapter(use_local_embeddings=use_local_embeddings)
    if kind == "mem0":
        from benchmarks.adapters.mem0_adapter import Mem0Adapter
        return Mem0Adapter()
    if kind == "hindsight":
        from benchmarks.adapters.hindsight_adapter import HindsightAdapter
        return HindsightAdapter()
    raise ValueError(f"Unknown adapter kind: {kind!r}")


def run_all(
    *,
    adapter_kind: str,
    use_local_embeddings: bool,
    scenarios: list[str],
) -> dict[str, Any]:
    adapter = _make_adapter(adapter_kind, use_local_embeddings=use_local_embeddings)
    results: list[ScenarioResult] = []

    for sid in scenarios:
        fn = _SCENARIO_FNS[sid]
        t0 = time.monotonic()
        try:
            result = fn(adapter)
        except Exception as exc:  # noqa: BLE001 — benchmark resilience
            logger.exception("[%s] %s failed: %s", adapter.system_name, sid, exc)
            result = ScenarioResult(
                scenario=f"{sid}_error",
                engramia_score=None,
                random_baseline=0.0,
                feature_tested="—",
                pass_rule="—",
                capability_missing=False,
                notes=[f"exception: {type(exc).__name__}: {exc}"],
            )
        result.duration_seconds = time.monotonic() - t0
        results.append(result)
        if result.capability_missing:
            logger.info("[%s] %s: capability_missing", adapter.system_name, result.scenario)
        elif result.engramia_score is None:
            logger.info("[%s] %s: error", adapter.system_name, result.scenario)
        else:
            logger.info(
                "[%s] %s: score=%.1f%% baseline=%.1f%% margin=%s",
                adapter.system_name, result.scenario,
                result.engramia_score * 100, result.random_baseline * 100,
                result.discrimination_margin,
            )

    valid_scores = [r.engramia_score for r in results if r.engramia_score is not None]
    mean_score = sum(valid_scores) / len(valid_scores) if valid_scores else None
    baselines = [r.random_baseline for r in results if r.engramia_score is not None]
    mean_baseline = sum(baselines) / len(baselines) if baselines else 0.0

    return {
        "metadata": {
            "benchmark": "AgentLifecycleBench",
            "adapter_kind": adapter_kind,
            "system_name": adapter.system_name,
            "system_version": adapter.system_version,
            "forced_mapping_note": adapter.forced_mapping_note,
            "supports_refine": adapter.supports_refine,
            "supports_timestamp_patch": _supports_timestamp_patch(adapter),
            "embedding_model": getattr(adapter, "_embedding_model", "adapter-internal"),
            "use_local_embeddings": use_local_embeddings,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
            "scenarios_run": [r.scenario for r in results],
        },
        "results": [r.to_dict() for r in results],
        "summary": {
            "mean_engramia_score": round(mean_score, 4) if mean_score is not None else None,
            "mean_random_baseline": round(mean_baseline, 4),
            "scenarios_with_score": len(valid_scores),
            "scenarios_capability_missing": sum(1 for r in results if r.capability_missing),
            "scenarios_errored": sum(1 for r in results if (not r.capability_missing) and r.engramia_score is None),
        },
    }


def _print_summary(report: dict[str, Any]) -> None:
    meta = report["metadata"]
    print()
    print("=" * 76)
    print(f"  AgentLifecycleBench — {meta['system_name']} {meta['system_version']}")
    print("=" * 76)
    print(
        f"  supports_refine={meta['supports_refine']}   "
        f"supports_timestamp_patch={meta['supports_timestamp_patch']}"
    )
    print(f"  embedding: {meta['embedding_model']}")
    print()
    print(f"  {'Scenario':<28} {'Score':>10}  {'Random':>8}  {'Margin':>10}  {'Secs':>6}")
    print(f"  {'-' * 28} {'-' * 10}  {'-' * 8}  {'-' * 10}  {'-' * 6}")
    for r in report["results"]:
        if r["capability_missing"]:
            score_str = "—"
            margin_str = "missing"
        elif r["engramia_score"] is None:
            score_str = "ERR"
            margin_str = "ERR"
        else:
            score_str = f"{r['engramia_score'] * 100:>8.1f}%"
            m = r["discrimination_margin_x"]
            margin_str = f"{m}x" if isinstance(m, (int, float)) else str(m)
        print(
            f"  {r['scenario']:<28} {score_str:>10}  "
            f"{r['random_baseline'] * 100:>7.1f}%  {margin_str:>10}  "
            f"{r['duration_seconds']:>5.2f}"
        )
    s = report["summary"]
    print()
    mean_str = (
        f"{s['mean_engramia_score'] * 100:>8.1f}%" if s["mean_engramia_score"] is not None else "—"
    )
    print(
        f"  MEAN ({s['scenarios_with_score']} scored, "
        f"{s['scenarios_capability_missing']} capability_missing, "
        f"{s['scenarios_errored']} errored): {mean_str}"
    )
    print("=" * 76)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="AgentLifecycleBench — closed-loop memory scenarios",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--adapter",
        choices=["engramia", "mem0", "hindsight"],
        default="engramia",
        help="Which adapter to run against.",
    )
    p.add_argument(
        "--scenario",
        choices=["L1", "L2", "L3", "L4", "L5", "all"],
        default="all",
    )
    p.add_argument(
        "--local",
        action="store_true",
        help=(
            "Use local sentence-transformers embeddings for the Engramia "
            "adapter (zero-cost). Ignored for Mem0 / Hindsight."
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="FILE",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    scenarios = ["L1", "L2", "L3", "L4", "L5"] if args.scenario == "all" else [args.scenario]
    report = run_all(
        adapter_kind=args.adapter,
        use_local_embeddings=args.local,
        scenarios=scenarios,
    )
    _print_summary(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

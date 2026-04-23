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
from typing import Any, Literal, Protocol

from benchmarks.adapters.base import MatchResult

Difficulty = Literal["easy", "medium", "hard"]
DIFFICULTIES: tuple[Difficulty, ...] = ("easy", "medium", "hard")

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
    difficulty: Difficulty
    engramia_score: float | None
    random_baseline: float
    feature_tested: str
    pass_rule: str
    capability_missing: bool = False
    notes: list[str] = field(default_factory=list)
    raw_metrics: dict[str, Any] = field(default_factory=dict)
    curves: dict[str, Any] = field(default_factory=dict)
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
            "difficulty": self.difficulty,
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
            "curves": self.curves,
            "duration_seconds": round(self.duration_seconds, 2),
        }


def _capability_missing(
    scenario: str, difficulty: Difficulty, feature_tested: str, pass_rule: str, baseline: float, missing_capability: str
) -> ScenarioResult:
    return ScenarioResult(
        scenario=scenario,
        difficulty=difficulty,
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


# L1 tuning per difficulty: (iterations, noise_prob — chance that a
# simulated feedback observation lies about which variant is best).
_L1_CONFIG: dict[Difficulty, tuple[int, float]] = {
    "easy": (10, 0.0),
    "medium": (10, 0.20),
    "hard": (8, 0.40),
}


def _run_l1_improvement_curve(adapter: _AdapterLike, difficulty: Difficulty = "easy", *, rng_seed: int = 42) -> ScenarioResult:
    """Does quality-evidence refinement converge on the designed-best
    approach over repeated usage?

    Difficulty knob: how often feedback lies about which variant was
    the real best. easy = 0 %, medium = 20 %, hard = 40 %. Under
    heavy misleading feedback the convergence degrades gracefully
    rather than collapsing — the profile of score vs noise is the
    measurement.
    """
    iterations, noise_prob = _L1_CONFIG[difficulty]
    feature = "refine_pattern (repeated quality observations update eval-weighted ranking)"
    pass_rule = (
        f"After {iterations} iterations with {int(noise_prob * 100)}% misleading-feedback noise, "
        "top-1 must be the ground-truth best approach on at least 80% of tasks."
    )
    baseline = 1 / 3

    if not adapter.supports_refine:
        return _capability_missing("L1_improvement_curve", difficulty, feature, pass_rule, baseline, "refine_pattern")

    adapter.reset()
    rng = random.Random(rng_seed)
    noise_rng = random.Random(rng_seed + 1)
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

    all_targets = list(score_targets.values())

    def _noisy_score(picked_variant: str, domain: str) -> float:
        correct_score = (
            score_targets["A"] if picked_variant == true_best[domain]
            else (score_targets["B"] if picked_variant == "B" else score_targets["C"])
        )
        if noise_prob > 0.0 and noise_rng.random() < noise_prob:
            # Realistic noise: uniform-random target. 1/3 chance of
            # landing on truth by accident. This is the "human rater
            # is sometimes wrong" distribution — NOT adversarial
            # inversion. An adversarial-inversion model would actively
            # flip truth to falsehood; real evaluation noise is
            # uncorrelated with truth. A separate variant could model
            # adversarial distribution if we wanted a worst-case test.
            return noise_rng.choice(all_targets)
        return correct_score

    def _measure_convergence() -> float:
        """Fraction of tasks whose current top-1 is the ground-truth best."""
        hit = 0
        for d in tasks:
            matches = adapter.recall(
                query=f"Solve {d.replace('_', ' ')} task",
                limit=3,
                eval_weighted=True,
            )
            if matches and f"approach_{true_best[d]}" in matches[0].task_text:
                hit += 1
        return hit / len(tasks) if tasks else 0.0

    convergence_curve: list[float] = [_measure_convergence()]  # iter 0 baseline
    noisy_feedbacks = 0
    total_feedbacks = 0
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
            total_feedbacks += 1
            honest_score = (
                score_targets["A"] if picked_variant == true_best[domain]
                else (score_targets["B"] if picked_variant == "B" else score_targets["C"])
            )
            observed_score = _noisy_score(picked_variant, domain)
            if observed_score != honest_score:
                noisy_feedbacks += 1
            adapter.refine_pattern(picked.pattern_id, observed_score, feedback=f"obs in {domain}")
        # Snapshot after each full iteration over tasks.
        convergence_curve.append(_measure_convergence())

    correct = round(convergence_curve[-1] * len(tasks))

    return ScenarioResult(
        scenario="L1_improvement_curve",
        difficulty=difficulty,
        engramia_score=convergence_curve[-1],
        random_baseline=baseline,
        feature_tested=feature,
        pass_rule=pass_rule,
        notes=[
            "Random baseline is 1/3 (three candidates per task).",
            f"Noise: {noisy_feedbacks} of {total_feedbacks} feedback observations were misleading.",
        ],
        raw_metrics={
            "iterations": iterations,
            "noise_prob": noise_prob,
            "tasks": len(tasks),
            "correct": correct,
            "noisy_feedbacks": noisy_feedbacks,
            "total_feedbacks": total_feedbacks,
        },
        curves={
            "convergence": [round(v, 4) for v in convergence_curve],
            "convergence_iterations": list(range(len(convergence_curve))),
            "convergence_interpretation": (
                "Fraction of 12 tasks whose current top-1 is the ground-truth best "
                "approach, sampled after each of {n} training iterations (index 0 = "
                "pre-training baseline). A growing curve indicates feedback "
                "accumulates; a flat/declining curve indicates noise dominates."
            ).format(n=iterations),
        },
    )


# ---------------------------------------------------------------------------
# L2 — Deprecation speed (requires refine_pattern)
# ---------------------------------------------------------------------------


# L2 tuning: (failed_score, good_score) — narrower gap means the
# multiplier spread has to work harder to demote the failed cohort.
_L2_CONFIG: dict[Difficulty, tuple[float, float]] = {
    "easy": (0.5, 7.0),
    "medium": (3.0, 7.0),
    "hard": (4.0, 6.0),
}


def _run_l2_deprecation_speed(adapter: _AdapterLike, difficulty: Difficulty = "easy") -> ScenarioResult:
    """Does quality-weighted recall rank failed patterns below good ones
    once failure feedback is recorded?

    Difficulty: easy = large score gap (0.5 vs 7.0); medium = moderate
    (3.0 vs 7.0); hard = narrow (4.0 vs 6.0). Narrower gap tests
    whether the quality multiplier has enough spread to discriminate
    near-equal quality cohorts.
    """
    failed_score, good_score = _L2_CONFIG[difficulty]
    feature = "refine_pattern downgrade demotes deprecated patterns out of top-K"
    pass_rule = (
        f"≥80% of top-5 matches are from the non-deprecated set "
        f"(failed eval_score={failed_score}, good eval_score={good_score})."
    )
    baseline = 0.5

    if not adapter.supports_refine:
        return _capability_missing("L2_deprecation_speed", difficulty, feature, pass_rule, baseline, "refine_pattern")

    n_good = 25
    n_failed = 25
    # easy/medium use shared task text so the ranking signal is purely
    # the quality multiplier. hard breaks the shared-text assumption:
    # patterns use per-domain task text, probes use domain-specific
    # wording, and similarity variance competes with the multiplier.
    if difficulty == "hard":
        shared_text: str | None = None
        probe_queries = [
            f"Implement {d.replace('_', ' ')} flow"
            for d in _DOMAINS[:10]
        ]
    else:
        shared_text = "Build the order-fulfilment pipeline"
        probe_queries = [shared_text] * 10

    adapter.reset()
    patterns = []
    for i in range(n_good):
        d = _DOMAINS[i % len(_DOMAINS)]
        task_text = shared_text if shared_text is not None else f"Implement {d.replace('_', ' ')} task"
        patterns.append({
            "task": task_text,
            "code": f"# good {d} #{i}",
            "eval_score": good_score,
            "pattern_id": f"good_{i}",
        })
    for i in range(n_failed):
        d = _DOMAINS[i % len(_DOMAINS)]
        task_text = shared_text if shared_text is not None else f"Implement {d.replace('_', ' ')} task"
        patterns.append({
            "task": task_text,
            "code": f"# failed {d} #{i}",
            "eval_score": good_score,  # all seeded equal; failure is recorded after
            "pattern_id": f"failed_{i}",
        })
    adapter.seed(patterns)

    good_ids = {f"good_{i}" for i in range(n_good)}
    failed_ids = {f"failed_{i}" for i in range(n_failed)}
    for pid in failed_ids:
        adapter.refine_pattern(pid, failed_score, feedback="simulated failure feedback")

    precision_at_k: dict[str, float] = {}
    for k in (1, 3, 5, 10):
        total = 0
        hits = 0
        for q in probe_queries:
            matches = adapter.recall(q, limit=k, eval_weighted=True)
            for m in matches:
                total += 1
                if m.pattern_id in good_ids:
                    hits += 1
        precision_at_k[f"p@{k}"] = round(hits / total, 4) if total else 0.0

    # Top-5 is the pass-rule metric; keep it as engramia_score for continuity.
    total_top5 = 0
    good_top5 = 0
    for q in probe_queries:
        for m in adapter.recall(q, limit=5, eval_weighted=True):
            total_top5 += 1
            if m.pattern_id in good_ids:
                good_top5 += 1

    return ScenarioResult(
        scenario="L2_deprecation_speed",
        difficulty=difficulty,
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
            "failed_score": failed_score,
            "good_score": good_score,
        },
        curves={
            "precision_at_k": precision_at_k,
            "precision_at_k_interpretation": (
                "Fraction of the top-K recalled matches that belong to the "
                "non-deprecated set, for K in {1, 3, 5, 10}. Degradation at "
                "higher K indicates the quality multiplier discriminates "
                "well at the head but loses resolution deeper in the list."
            ),
        },
    )


# ---------------------------------------------------------------------------
# L3 — Conflict resolution (requires recency_weight + timestamp patch)
# ---------------------------------------------------------------------------


# L3 tuning: (old_days_ago, old_eval, new_eval). Harder = smaller
# time gap + narrower quality gap, so the recency knob has to work
# against a closer starting point.
_L3_CONFIG: dict[Difficulty, tuple[float, float, float]] = {
    "easy": (180.0, 9.0, 7.0),
    "medium": (60.0, 8.5, 7.5),
    "hard": (15.0, 8.0, 7.5),
}


def _run_l3_conflict_resolution(adapter: _AdapterLike, difficulty: Difficulty = "easy") -> ScenarioResult:
    """Does ``recency_weight`` smoothly tune ranking between old
    high-quality and fresh medium-quality patterns?

    Difficulty: easy = 180 d / 9.0 vs 7.0 (wide gap); medium = 60 d /
    8.5 vs 7.5; hard = 15 d / 8.0 vs 7.5 (small gap — recency has to
    overcome near-equal quality across a modest time delta).
    """
    old_days_ago, old_eval, new_eval = _L3_CONFIG[difficulty]
    feature = "recency_weight knob + timestamp-aware ranking"
    pass_rule = (
        f"Average of (old wins at recency_weight=0, new wins at "
        f"recency_weight=1) ≥ 80% with old-{int(old_days_ago)}d / "
        f"quality {old_eval} vs {new_eval}."
    )
    baseline = 0.5

    if not _supports_timestamp_patch(adapter):
        return _capability_missing(
            "L3_conflict_resolution", difficulty, feature, pass_rule, baseline,
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
            "eval_score": old_eval,
            "pattern_id": f"old_{i}",
        })
    for i in range(12):
        d = _DOMAINS[i % len(_DOMAINS)]
        patterns.append({
            "task": shared_text,
            "code": f"# new {d} #{i}",
            "eval_score": new_eval,
            "pattern_id": f"new_{i}",
        })
    adapter.seed(patterns)

    for i in range(12):
        adapter.patch_timestamp(f"old_{i}", now - old_days_ago * _DAY)

    old_ids = {f"old_{i}" for i in range(12)}
    new_ids = {f"new_{i}" for i in range(12)}

    def _fraction(recency_weight: float, cohort_ids: set[str]) -> float:
        correct = 0
        for q in probes:
            matches = adapter.recall(q, limit=100, eval_weighted=True, recency_weight=recency_weight)
            if matches and matches[0].pattern_id in cohort_ids:
                correct += 1
        return correct / len(probes) if probes else 0.0

    # Sharpness curve: sweep recency_weight in 11 steps from 0 to 1.
    sharpness_weights = [round(i * 0.1, 2) for i in range(11)]
    new_fraction_by_weight: list[float] = [_fraction(w, new_ids) for w in sharpness_weights]
    # Identify the crossover point (first weight at which new beats old in top-1 majority).
    crossover_weight: float | None = None
    for w, frac in zip(sharpness_weights, new_fraction_by_weight, strict=True):
        if frac >= 0.5:
            crossover_weight = w
            break

    old_wins_at_w0 = _fraction(0.0, old_ids)
    new_wins_at_w1 = _fraction(1.0, new_ids)
    mid_new_fraction = _fraction(0.3, new_ids)

    engramia_score = (old_wins_at_w0 + new_wins_at_w1) / 2

    return ScenarioResult(
        scenario="L3_conflict_resolution",
        difficulty=difficulty,
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
            "old_days_ago": old_days_ago,
            "old_eval": old_eval,
            "new_eval": new_eval,
        },
        curves={
            "sharpness_weights": sharpness_weights,
            "new_fraction_by_weight": [round(v, 4) for v in new_fraction_by_weight],
            "crossover_weight": crossover_weight,
            "sharpness_interpretation": (
                "Fraction of probes whose top-1 comes from the new (fresh) cohort "
                "as a function of recency_weight. A sharp step function near a "
                "specific weight indicates the knob flips ranking cleanly at that "
                "point; a smooth ramp indicates the knob blends the two cohorts "
                "gradually. Competitors without a recency knob cannot produce "
                "either shape — their fraction stays flat."
            ),
        },
    )


# ---------------------------------------------------------------------------
# L4 — Concept drift (requires refine_pattern + timestamp patch)
# ---------------------------------------------------------------------------


# L4 tuning: (n_v2, n_v3, v3_refined_score). Harder = v2 more numerous
# and v3 less-strongly endorsed; the combination is harder for the
# recency + quality signal to overcome population bias.
_L4_CONFIG: dict[Difficulty, tuple[int, int, float]] = {
    "easy": (20, 10, 9.5),
    "medium": (30, 10, 8.5),
    "hard": (40, 10, 8.0),
}


def _run_l4_concept_drift(adapter: _AdapterLike, difficulty: Difficulty = "easy") -> ScenarioResult:
    n_v2, n_v3, v3_refined_score = _L4_CONFIG[difficulty]
    feature = "refine_pattern quality boost + recency_weight on fresh cohort"
    pass_rule = (
        f"≥60% of top-5 come from v3 ({n_v3} patterns) despite v2 ({n_v2}) "
        f"being {n_v2 / n_v3:.0f}× more populous; v3 refined to eval={v3_refined_score}."
    )
    baseline = n_v3 / (n_v2 + n_v3)

    if not adapter.supports_refine:
        return _capability_missing("L4_concept_drift", difficulty, feature, pass_rule, baseline, "refine_pattern")
    if not _supports_timestamp_patch(adapter):
        return _capability_missing(
            "L4_concept_drift", difficulty, feature, pass_rule, baseline,
            "patch_timestamp (adapter cannot back-date stored patterns)",
        )

    adapter.reset()
    now = time.time()
    # easy/medium: shared task text → ranking decided by eval_weighted
    # and recency_weight alone. hard: per-domain task text so
    # similarity varies per-probe; the combined signal has to beat
    # similarity bias on top of population imbalance.
    if difficulty == "hard":
        shared_text = None
        probes = [f"Implement {d.replace('_', ' ')} flow" for d in _DOMAINS[:10]]
    else:
        shared_text = "Provide the HTTP client helper used by the platform"
        probes = [shared_text] * 10

    patterns = []
    for i in range(n_v2):
        d = _DOMAINS[i % len(_DOMAINS)]
        task_text = shared_text if shared_text is not None else f"Implement {d.replace('_', ' ')} task"
        patterns.append({
            "task": task_text,
            "code": f"# v2 legacy {d} #{i}",
            "eval_score": 7.0,
            "pattern_id": f"v2_{i}",
        })
    for i in range(n_v3):
        d = _DOMAINS[i % len(_DOMAINS)]
        task_text = shared_text if shared_text is not None else f"Implement {d.replace('_', ' ')} task"
        patterns.append({
            "task": task_text,
            "code": f"# v3 modern {d} #{i}",
            "eval_score": 7.0,
            "pattern_id": f"v3_{i}",
        })
    adapter.seed(patterns)

    for i in range(n_v2):
        adapter.patch_timestamp(f"v2_{i}", now - 120 * _DAY)

    v3_ids = {f"v3_{i}" for i in range(n_v3)}
    for pid in v3_ids:
        adapter.refine_pattern(pid, v3_refined_score, feedback="repeatedly used in production")

    precision_at_k: dict[str, float] = {}
    for k in (1, 3, 5, 10):
        total = 0
        hits = 0
        for q in probes:
            matches = adapter.recall(q, limit=100, eval_weighted=True, recency_weight=0.5)
            for m in matches[:k]:
                total += 1
                if m.pattern_id in v3_ids:
                    hits += 1
        precision_at_k[f"p@{k}"] = round(hits / total, 4) if total else 0.0

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
        difficulty=difficulty,
        engramia_score=engramia_score,
        random_baseline=baseline,
        feature_tested=feature,
        pass_rule=pass_rule,
        notes=[],
        raw_metrics={
            "v2_seeded": n_v2,
            "v3_seeded": n_v3,
            "v3_refined_score": v3_refined_score,
            "v3_top5": v3_matches,
            "total_top5": total_matches,
        },
        curves={
            "precision_at_k": precision_at_k,
            "precision_at_k_interpretation": (
                "Fraction of top-K matches that come from the fresh v3 cohort "
                "(refined quality + fresh timestamp) despite v2 being more "
                "populous. Drop-off at higher K shows how far the fresh "
                "cohort's ranking advantage extends."
            ),
            "cohort_sizes": {"v2": n_v2, "v3": n_v3},
        },
    )


# ---------------------------------------------------------------------------
# L5 — Signal-to-noise floor (requires refine_pattern)
# ---------------------------------------------------------------------------


# L5 tuning: (herring_claimed_score, herring_corrected_score, honest_corrected_score).
# Easy = wide gap; hard = subtle correction (herring still looks ok after re-eval).
_L5_CONFIG: dict[Difficulty, tuple[float, float, float]] = {
    "easy": (9.5, 1.0, 7.0),
    "medium": (8.0, 3.0, 7.0),
    "hard": (7.5, 5.0, 7.0),
}


def _run_l5_noise_rejection(adapter: _AdapterLike, difficulty: Difficulty = "easy") -> ScenarioResult:
    herring_claim, herring_corrected, honest_corrected = _L5_CONFIG[difficulty]
    feature = "refine_pattern re-grading demotes adversarial (spoofed high-score) patterns"
    pass_rule = (
        f"After re-evaluation (herring claim={herring_claim}, "
        f"corrected={herring_corrected}; honest corrected={honest_corrected}), "
        "top-10 must contain ≤ 20% red herrings."
    )
    baseline = 0.5

    if not adapter.supports_refine:
        return _capability_missing("L5_noise_rejection", difficulty, feature, pass_rule, baseline, "refine_pattern")

    adapter.reset()
    # easy/medium: shared task text so ranking is driven purely by the
    # eval store's pre- vs post-refine multiplier. hard: per-domain
    # task text so similarity variance competes with the corrected
    # score.
    if difficulty == "hard":
        shared_text = None
        probes = [
            f"Implement {_DOMAINS[i % len(_DOMAINS)].replace('_', ' ')} flow"
            for i in range(20)
        ]
    else:
        shared_text = "Implement service layer for the flagship product"
        probes = [shared_text] * 20

    patterns = []
    good_ids: list[str] = []
    herring_ids: list[str] = []
    for i in range(20):
        d = _DOMAINS[i % len(_DOMAINS)]
        pid = f"honest_{i}"
        task_text = shared_text if shared_text is not None else f"Implement {d.replace('_', ' ')} task"
        patterns.append({
            "task": task_text,
            "code": f"# honest {d} #{i}",
            "eval_score": 7.0,
            "pattern_id": pid,
        })
        good_ids.append(pid)
    for i in range(20):
        d = _DOMAINS[i % len(_DOMAINS)]
        pid = f"herring_{i}"
        task_text = shared_text if shared_text is not None else f"Implement {d.replace('_', ' ')} task"
        patterns.append({
            "task": task_text,
            "code": f"# herring {d} #{i}",
            "eval_score": herring_claim,
            "pattern_id": pid,
        })
        herring_ids.append(pid)
    adapter.seed(patterns)

    herring_set = set(herring_ids)

    def _probe_top10() -> tuple[int, int]:
        # Fetch all 40 patterns then truncate to 10 so the
        # effective-score re-rank sees the full pool; default fetch
        # depth would leave insertion-order tie-break dictating the
        # top-10 and defeat the multiplier signal we're measuring.
        total = 0
        herring = 0
        for q in probes[:5]:
            matches = adapter.recall(q, limit=100, eval_weighted=True)
            for m in matches[:10]:
                total += 1
                if m.pattern_id in herring_set:
                    herring += 1
        return herring, total

    pre_herring, pre_matches = _probe_top10()
    pre_herring_fraction = pre_herring / pre_matches if pre_matches else 0.0

    for pid in good_ids:
        adapter.refine_pattern(pid, honest_corrected, feedback="mock re-eval honest")
    for pid in herring_ids:
        adapter.refine_pattern(pid, herring_corrected, feedback="mock re-eval herring")

    post_herring, post_matches = _probe_top10()
    post_herring_fraction = post_herring / post_matches if post_matches else 0.0

    engramia_score = max(0.0, 1.0 - post_herring_fraction)

    # Classification metrics treating "honest pattern in the probe's
    # top-10" as the positive class. Averaged across the five probes so
    # numbers stay in [0, 1]. Precision = honest / returned; recall =
    # honest / min(10, total_honest_seeded) — bounded because our top-K
    # is smaller than the pool.
    num_probes_scored = len(probes[:5])
    max_honest_in_topk = min(10, len(good_ids))

    def _metrics(herring_total: int, matches_total: int) -> dict[str, float]:
        top_count_per_probe = matches_total // max(1, num_probes_scored)
        honest_total = matches_total - herring_total
        honest_per_probe = honest_total / max(1, num_probes_scored)
        # Precision across returned matches.
        precision = honest_total / matches_total if matches_total else 0.0
        # Recall bounded by the smaller of top-10 and total seeded.
        recall = min(1.0, honest_per_probe / max(1, max_honest_in_topk))
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        return {
            "precision_honest": round(precision, 4),
            "recall_honest": round(recall, 4),
            "f1_honest": round(f1, 4),
            "herring_fraction_in_top10": round(herring_total / matches_total if matches_total else 0.0, 4),
            "top_count_per_probe": top_count_per_probe,
        }

    pre_metrics = _metrics(pre_herring, pre_matches)
    post_metrics = _metrics(post_herring, post_matches)
    f1_improvement = round(post_metrics["f1_honest"] - pre_metrics["f1_honest"], 4)

    return ScenarioResult(
        scenario="L5_noise_rejection",
        difficulty=difficulty,
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
            "herring_claim": herring_claim,
            "herring_corrected": herring_corrected,
            "honest_corrected": honest_corrected,
        },
        curves={
            "pre_re_eval": pre_metrics,
            "post_re_eval": post_metrics,
            "f1_improvement": f1_improvement,
            "classification_interpretation": (
                "Precision / recall / F1 treating 'honest pattern in top-10' as "
                "the positive class. F1 improvement = post - pre is the net gain "
                "from one round of refine_pattern re-grading. A positive "
                "delta indicates re-evaluation successfully identified and "
                "demoted the adversarial patterns; zero or negative indicates "
                "the backend cannot act on the corrected scores."
            ),
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
    difficulties: tuple[Difficulty, ...] = DIFFICULTIES,
) -> dict[str, Any]:
    adapter = _make_adapter(adapter_kind, use_local_embeddings=use_local_embeddings)
    results: list[ScenarioResult] = []

    for sid in scenarios:
        fn = _SCENARIO_FNS[sid]
        for difficulty in difficulties:
            t0 = time.monotonic()
            try:
                result = fn(adapter, difficulty)
            except Exception as exc:  # noqa: BLE001 — benchmark resilience
                logger.exception("[%s] %s/%s failed: %s", adapter.system_name, sid, difficulty, exc)
                result = ScenarioResult(
                    scenario=sid,
                    difficulty=difficulty,
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
                logger.info("[%s] %s/%s: capability_missing", adapter.system_name, result.scenario, difficulty)
            elif result.engramia_score is None:
                logger.info("[%s] %s/%s: error", adapter.system_name, result.scenario, difficulty)
            else:
                logger.info(
                    "[%s] %s/%s: score=%.1f%% baseline=%.1f%% margin=%s",
                    adapter.system_name, result.scenario, difficulty,
                    result.engramia_score * 100, result.random_baseline * 100,
                    result.discrimination_margin,
                )

    valid_scores = [r.engramia_score for r in results if r.engramia_score is not None]
    mean_score = sum(valid_scores) / len(valid_scores) if valid_scores else None
    baselines = [r.random_baseline for r in results if r.engramia_score is not None]
    mean_baseline = sum(baselines) / len(baselines) if baselines else 0.0

    # Headline per-difficulty means — what the marketing copy quotes.
    per_difficulty: dict[str, dict[str, Any]] = {}
    for diff in difficulties:
        diff_scores = [r.engramia_score for r in results if r.difficulty == diff and r.engramia_score is not None]
        diff_baselines = [r.random_baseline for r in results if r.difficulty == diff and r.engramia_score is not None]
        per_difficulty[diff] = {
            "mean_score": round(sum(diff_scores) / len(diff_scores), 4) if diff_scores else None,
            "mean_baseline": round(sum(diff_baselines) / len(diff_baselines), 4) if diff_baselines else 0.0,
            "scenarios_scored": len(diff_scores),
        }

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
            "scenarios_run": list(scenarios),
            "difficulties_run": list(difficulties),
        },
        "results": [r.to_dict() for r in results],
        "summary": {
            "mean_engramia_score": round(mean_score, 4) if mean_score is not None else None,
            "mean_random_baseline": round(mean_baseline, 4),
            "scenarios_scored": len(valid_scores),
            "scenarios_capability_missing": sum(1 for r in results if r.capability_missing),
            "scenarios_errored": sum(1 for r in results if (not r.capability_missing) and r.engramia_score is None),
            "headline": (
                "medium-difficulty mean is the realistic workload estimate; "
                "easy is a feature-correctness check, hard is stress-test."
            ),
            "per_difficulty": per_difficulty,
        },
    }


def _print_summary(report: dict[str, Any]) -> None:
    meta = report["metadata"]
    s = report["summary"]
    print()
    print("=" * 90)
    print(f"  AgentLifecycleBench — {meta['system_name']} {meta['system_version']}")
    print("=" * 90)
    print(
        f"  supports_refine={meta['supports_refine']}   "
        f"supports_timestamp_patch={meta['supports_timestamp_patch']}   "
        f"embedding: {meta['embedding_model']}"
    )
    print()

    # Pivoted table: one row per scenario, one column per difficulty.
    results_by_scenario: dict[str, dict[str, dict[str, Any]]] = {}
    for r in report["results"]:
        results_by_scenario.setdefault(r["scenario"], {})[r["difficulty"]] = r

    difficulties = meta.get("difficulties_run", ["easy", "medium", "hard"])
    header = f"  {'Scenario':<26}"
    for d in difficulties:
        header += f"  {d:>10}"
    header += f"  {'Random':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    def _cell(r: dict[str, Any] | None) -> str:
        if r is None:
            return "—"
        if r["capability_missing"]:
            return "missing"
        if r["engramia_score"] is None:
            return "ERR"
        return f"{r['engramia_score'] * 100:>7.1f}%"

    for scenario, by_diff in results_by_scenario.items():
        row = f"  {scenario:<26}"
        for d in difficulties:
            row += f"  {_cell(by_diff.get(d)):>10}"
        # Use the first available random baseline — same across difficulties for L1/L2/L3/L5.
        first = next((v for v in by_diff.values() if v), None)
        if first is not None:
            row += f"  {first['random_baseline'] * 100:>7.1f}%"
        print(row)

    print()
    if s["per_difficulty"]:
        print("  Per-difficulty means:")
        for d in difficulties:
            entry = s["per_difficulty"].get(d, {})
            mean = entry.get("mean_score")
            if mean is None:
                print(f"    {d:<8}  —")
            else:
                print(f"    {d:<8}  {mean * 100:>6.1f}%  (over {entry['scenarios_scored']} scenarios)")
        print()
        print("  " + s["headline"])
    print("=" * 90)


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

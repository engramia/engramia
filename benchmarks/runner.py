# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Benchmark runner — core engine for recall quality validation.

Runs three scenarios (cold / warm / full) against the Engramia Memory API
using local embeddings (sentence-transformers) and temporary JSON storage.
No API keys required.
"""
from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from engramia import Memory
from engramia.providers import JSONStorage
from engramia.providers.local_embeddings import LocalEmbeddings

from benchmarks.dataset import (
    DOMAINS,
    NOISE_TASKS,
    TaskEntry,
    TrainingPattern,
    build_dataset,
    build_training_set,
)

logger = logging.getLogger(__name__)

# Minimum eval_score for a training pattern to count as "quality hit"
QUALITY_THRESHOLD = 7.0


# ---------------------------------------------------------------------------
# Auto-calibration — compute model-appropriate similarity threshold
# ---------------------------------------------------------------------------


def _cosine_sim(a: list[float], b: list[float]) -> float:
    va, vb = np.asarray(a), np.asarray(b)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(np.dot(va, vb) / denom) if denom > 0 else 0.0


@dataclass(frozen=True)
class CalibrationResult:
    """Embedding-model-specific similarity thresholds."""

    adapt_threshold: float  # minimum sim for "recall hit"
    noise_threshold: float  # maximum sim for noise rejection
    model_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapt_threshold": round(self.adapt_threshold, 4),
            "noise_threshold": round(self.noise_threshold, 4),
            "model_name": self.model_name,
        }


def calibrate(embeddings: LocalEmbeddings) -> CalibrationResult:
    """Auto-calibrate similarity thresholds for the active embedding model.

    Strategy:
        1. Embed one representative task per domain (12 tasks)
        2. Embed 5 noise tasks
        3. Compute intra-domain similarities (within-domain variant pairs)
        4. Compute cross-domain similarities (between different domains)
        5. Set adapt_threshold = midpoint between worst intra and best cross
        6. Set noise_threshold = max noise similarity + small margin
    """
    logger.info("Calibrating similarity thresholds...")

    domain_ids = list(DOMAINS.keys())

    # Embed all 5 variants per domain
    all_embeddings: dict[str, list[list[float]]] = {}
    for did in domain_ids:
        variants = DOMAINS[did]
        embs = [embeddings.embed(t) for t in variants]
        all_embeddings[did] = embs

    # Intra-domain: pairwise sim between variants of SAME domain
    intra_sims: list[float] = []
    for did in domain_ids:
        embs = all_embeddings[did]
        for i in range(len(embs)):
            for j in range(i + 1, len(embs)):
                intra_sims.append(_cosine_sim(embs[i], embs[j]))

    # Cross-domain: sim between first variant of DIFFERENT domains
    cross_sims: list[float] = []
    for i, did_a in enumerate(domain_ids):
        for j, did_b in enumerate(domain_ids):
            if j <= i:
                continue
            cross_sims.append(_cosine_sim(all_embeddings[did_a][0], all_embeddings[did_b][0]))

    # Noise: sim between noise tasks and domain representatives
    noise_embs = [embeddings.embed(t) for t in NOISE_TASKS[:5]]
    noise_sims: list[float] = []
    for n_emb in noise_embs:
        for did in domain_ids:
            noise_sims.append(_cosine_sim(n_emb, all_embeddings[did][0]))

    min_intra = float(np.percentile(intra_sims, 10))  # 10th percentile (conservative)
    max_cross = float(np.percentile(cross_sims, 90))  # 90th percentile
    max_noise = float(np.max(noise_sims))

    # Threshold = midpoint between worst intra-domain and best cross-domain
    adapt_threshold = (min_intra + max_cross) / 2
    # Noise threshold = max observed noise sim + 5% margin
    noise_threshold = max_noise + 0.05

    logger.info(
        "Calibration: intra=[%.3f, %.3f] cross=[%.3f, %.3f] noise_max=%.3f -> adapt=%.3f noise=%.3f",
        min_intra, float(np.max(intra_sims)),
        float(np.min(cross_sims)), max_cross,
        max_noise, adapt_threshold, noise_threshold,
    )

    return CalibrationResult(
        adapt_threshold=adapt_threshold,
        noise_threshold=noise_threshold,
        model_name="all-MiniLM-L6-v2",
    )


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class TaskResult:
    """Result of evaluating a single test task."""

    task: str
    category: str  # "in_domain" | "boundary" | "noise"
    expected_domains: tuple[str, ...]
    top1_similarity: float
    top1_domain: str | None  # domain of the top-1 matched training pattern
    top1_eval_score: float | None
    recall_hit: bool  # top-1 sim >= threshold AND from correct domain
    quality_hit: bool  # recall_hit AND top-1 eval_score >= quality threshold
    noise_rejected: bool  # for noise: no match above threshold
    precision_at_1: bool  # top-1 is from correct domain (ignoring threshold)


@dataclass
class ScenarioResult:
    """Aggregate metrics for one benchmark scenario."""

    name: str
    training_patterns: int
    patterns_per_domain: int
    calibration: CalibrationResult | None = None
    task_results: list[TaskResult] = field(default_factory=list)
    duration_seconds: float = 0.0

    # --- Computed metrics ---

    @property
    def total_tasks(self) -> int:
        return len(self.task_results)

    @property
    def in_domain_results(self) -> list[TaskResult]:
        return [r for r in self.task_results if r.category == "in_domain"]

    @property
    def boundary_results(self) -> list[TaskResult]:
        return [r for r in self.task_results if r.category == "boundary"]

    @property
    def noise_results(self) -> list[TaskResult]:
        return [r for r in self.task_results if r.category == "noise"]

    @property
    def in_domain_recall_hits(self) -> int:
        return sum(1 for r in self.in_domain_results if r.recall_hit)

    @property
    def in_domain_precision_at_1(self) -> int:
        return sum(1 for r in self.in_domain_results if r.precision_at_1)

    @property
    def in_domain_quality_hits(self) -> int:
        return sum(1 for r in self.in_domain_results if r.quality_hit)

    @property
    def boundary_hits(self) -> int:
        return sum(1 for r in self.boundary_results if r.recall_hit)

    @property
    def boundary_precision(self) -> int:
        return sum(1 for r in self.boundary_results if r.precision_at_1)

    @property
    def noise_rejected(self) -> int:
        return sum(1 for r in self.noise_results if r.noise_rejected)

    @property
    def overall_success(self) -> int:
        """Total successful tasks (recall hit + noise rejection)."""
        return (
            self.in_domain_recall_hits
            + self.boundary_hits
            + self.noise_rejected
        )

    @property
    def overall_success_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.overall_success / self.total_tasks

    def to_dict(self) -> dict[str, Any]:
        n_in = len(self.in_domain_results)
        n_bnd = len(self.boundary_results)
        n_noise = len(self.noise_results)
        return {
            "name": self.name,
            "training_patterns": self.training_patterns,
            "patterns_per_domain": self.patterns_per_domain,
            "calibration": self.calibration.to_dict() if self.calibration else None,
            "duration_seconds": round(self.duration_seconds, 2),
            "total_tasks": self.total_tasks,
            "in_domain": {
                "total": n_in,
                "recall_hits": self.in_domain_recall_hits,
                "recall_rate": round(self.in_domain_recall_hits / n_in, 4) if n_in else 0,
                "precision_at_1": self.in_domain_precision_at_1,
                "precision_rate": round(self.in_domain_precision_at_1 / n_in, 4) if n_in else 0,
                "quality_hits": self.in_domain_quality_hits,
                "quality_rate": round(self.in_domain_quality_hits / n_in, 4) if n_in else 0,
            },
            "boundary": {
                "total": n_bnd,
                "hits": self.boundary_hits,
                "hit_rate": round(self.boundary_hits / n_bnd, 4) if n_bnd else 0,
                "precision_at_1": self.boundary_precision,
                "precision_rate": round(self.boundary_precision / n_bnd, 4) if n_bnd else 0,
            },
            "noise": {
                "total": n_noise,
                "rejected": self.noise_rejected,
                "rejection_rate": round(self.noise_rejected / n_noise, 4) if n_noise else 0,
            },
            "overall": {
                "success": self.overall_success,
                "total": self.total_tasks,
                "success_rate": round(self.overall_success_rate, 4),
            },
        }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class BenchmarkRunner:
    """Runs benchmark scenarios against a fresh Memory instance.

    Each scenario creates an isolated Memory with temporary storage
    that is cleaned up after the run (unless keep=True).

    Auto-calibrates similarity thresholds for the embedding model
    at initialization.
    """

    def __init__(self, *, keep: bool = False, storage_dir: Path | None = None) -> None:
        self._keep = keep
        self._storage_dir = storage_dir
        self._dataset = build_dataset()
        self._embeddings = LocalEmbeddings()
        self._calibration = calibrate(self._embeddings)

    @property
    def calibration(self) -> CalibrationResult:
        return self._calibration

    def _create_memory(self, tmp_dir: Path) -> Memory:
        return Memory(
            embeddings=self._embeddings,
            storage=JSONStorage(path=tmp_dir),
        )

    def _learn_training_set(
        self, mem: Memory, training: list[TrainingPattern]
    ) -> None:
        """Populate memory with training patterns."""
        for tp in training:
            mem.learn(
                task=tp.task,
                code=tp.code,
                eval_score=tp.eval_score,
                output=tp.output,
            )

    def _evaluate_task(
        self,
        mem: Memory,
        entry: TaskEntry,
        training: list[TrainingPattern],
    ) -> TaskResult:
        """Evaluate a single test task against populated memory."""
        matches = mem.recall(
            task=entry.task,
            limit=5,
            deduplicate=True,
            eval_weighted=False,
        )

        top1_sim = 0.0
        top1_domain: str | None = None
        top1_eval: float | None = None

        if matches:
            top = matches[0]
            top1_sim = float(top.similarity)
            # Find which domain the matched pattern belongs to
            matched_task = top.pattern.task
            for tp in training:
                if tp.task == matched_task:
                    top1_domain = tp.domain_id
                    top1_eval = tp.eval_score
                    break

        adapt_thresh = self._calibration.adapt_threshold
        noise_thresh = self._calibration.noise_threshold

        # Scoring logic
        if entry.category == "noise":
            return TaskResult(
                task=entry.task,
                category="noise",
                expected_domains=(),
                top1_similarity=top1_sim,
                top1_domain=top1_domain,
                top1_eval_score=top1_eval,
                recall_hit=False,
                quality_hit=False,
                noise_rejected=top1_sim < noise_thresh,
                precision_at_1=False,
            )

        # In-domain or boundary: check if top-1 is from an expected domain
        domain_match = top1_domain in entry.expected_domains if top1_domain else False
        recall_hit = top1_sim >= adapt_thresh and domain_match
        quality_hit = recall_hit and (top1_eval is not None and top1_eval >= QUALITY_THRESHOLD)

        return TaskResult(
            task=entry.task,
            category=entry.category,
            expected_domains=entry.expected_domains,
            top1_similarity=top1_sim,
            top1_domain=top1_domain,
            top1_eval_score=top1_eval,
            recall_hit=recall_hit,
            quality_hit=quality_hit,
            noise_rejected=False,
            precision_at_1=domain_match,
        )

    def _run_scenario(
        self,
        name: str,
        patterns_per_domain: int,
        tasks: list[TaskEntry] | None = None,
    ) -> ScenarioResult:
        """Run a single benchmark scenario."""
        if tasks is None:
            tasks = self._dataset

        training = build_training_set(patterns_per_domain) if patterns_per_domain > 0 else []

        # Create isolated storage
        if self._storage_dir:
            tmp_dir = self._storage_dir / name
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp_context = None
        else:
            tmp_context = tempfile.TemporaryDirectory(prefix=f"engramia_bench_{name}_")
            tmp_dir = Path(tmp_context.name)

        try:
            mem = self._create_memory(tmp_dir)
            start = time.monotonic()

            # Learn phase
            if training:
                logger.info("Learning %d training patterns for '%s'...", len(training), name)
                self._learn_training_set(mem, training)

            # Evaluation phase
            logger.info("Evaluating %d tasks for '%s'...", len(tasks), name)
            result = ScenarioResult(
                name=name,
                training_patterns=len(training),
                patterns_per_domain=patterns_per_domain,
                calibration=self._calibration,
            )

            for i, entry in enumerate(tasks):
                task_result = self._evaluate_task(mem, entry, training)
                result.task_results.append(task_result)
                if (i + 1) % 50 == 0:
                    logger.info("  ...evaluated %d/%d tasks", i + 1, len(tasks))

            result.duration_seconds = time.monotonic() - start
            logger.info(
                "Scenario '%s' complete: %d/%d success (%.1f%%) in %.1fs",
                name, result.overall_success, result.total_tasks,
                result.overall_success_rate * 100, result.duration_seconds,
            )
            return result

        finally:
            if tmp_context and not self._keep:
                tmp_context.cleanup()
            elif tmp_context and self._keep:
                print(f"  Storage kept at: {tmp_dir}")

    def run_cold(self) -> ScenarioResult:
        """Cold start — no patterns in memory."""
        return self._run_scenario("cold_start", patterns_per_domain=0)

    def run_warm(self) -> ScenarioResult:
        """Warm-up — 1 good pattern per domain (12 total)."""
        # Only test with held-out variants (variants 3,4) + boundary + noise
        held_out = [
            e for e in self._dataset
            if e.category != "in_domain" or e.task not in _first_n_variants(3)
        ]
        return self._run_scenario("warm_up", patterns_per_domain=1, tasks=held_out)

    def run_full(self) -> ScenarioResult:
        """Full library — 3 patterns per domain (36 total), all 254 tasks."""
        return self._run_scenario("full_library", patterns_per_domain=3)

    def run_all(self) -> list[ScenarioResult]:
        """Run all three scenarios."""
        return [self.run_cold(), self.run_warm(), self.run_full()]


def _first_n_variants(n: int) -> set[str]:
    """Return the first N task variants from each domain (training tasks)."""
    result = set()
    for variants in DOMAINS.values():
        for v in variants[:n]:
            result.add(v)
    return result

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Benchmark report — terminal output and JSON persistence."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from benchmarks.runner import ScenarioResult


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------


def _pct(n: int, total: int) -> str:
    if total == 0:
        return "  —  "
    return f"{n / total * 100:.1f}%"


def print_calibration(result: ScenarioResult) -> None:
    """Print calibration info."""
    if result.calibration:
        c = result.calibration
        print(f"  Embedding model:    {c.model_name}")
        print(f"  Adapt threshold:    {c.adapt_threshold:.3f} (auto-calibrated)")
        print(f"  Noise threshold:    {c.noise_threshold:.3f} (auto-calibrated)")
        print()


def print_scenario(result: ScenarioResult) -> None:
    """Print a single scenario summary to stdout."""
    d = result.to_dict()
    n_in = d["in_domain"]["total"]
    n_bnd = d["boundary"]["total"]
    n_noise = d["noise"]["total"]

    print()
    header = f"Scenario: {result.name} ({result.total_tasks} tasks, {result.training_patterns} training patterns)"
    print(header)
    print("-" * len(header))

    if result.training_patterns == 0:
        print("  No patterns in memory -- baseline measurement.")
        print(f"  All {result.total_tasks} tasks are 'fresh' (no recall assistance).")
        print(f"  Duration: {result.duration_seconds:.1f}s")
        print()
        return

    print_calibration(result)

    thresh = result.calibration.adapt_threshold if result.calibration else 0.70

    # In-domain
    print(f"  In-domain ({n_in} tasks):")
    print(
        f"    Precision@1 (correct domain in top-1):      "
        f"{d['in_domain']['precision_at_1']}/{n_in} ({_pct(d['in_domain']['precision_at_1'], n_in)})"
    )
    print(
        f"    Recall hit (+ sim >= {thresh:.2f}):              "
        f"{d['in_domain']['recall_hits']}/{n_in} ({_pct(d['in_domain']['recall_hits'], n_in)})"
    )
    print(
        f"    Quality rank (hit + eval >= 7.0):            "
        f"{d['in_domain']['quality_hits']}/{n_in} ({_pct(d['in_domain']['quality_hits'], n_in)})"
    )

    # Boundary
    print(f"  Boundary ({n_bnd} tasks):")
    print(
        f"    Precision@1 (expected domain in top-1):      "
        f"{d['boundary']['precision_at_1']}/{n_bnd} ({_pct(d['boundary']['precision_at_1'], n_bnd)})"
    )
    print(
        f"    Recall hit (+ sim >= {thresh:.2f}):              "
        f"{d['boundary']['hits']}/{n_bnd} ({_pct(d['boundary']['hits'], n_bnd)})"
    )

    # Noise
    print(f"  Noise ({n_noise} tasks):")
    print(
        f"    Correctly rejected:                          "
        f"{d['noise']['rejected']}/{n_noise} ({_pct(d['noise']['rejected'], n_noise)})"
    )

    # Overall
    print(f"  {'':->54}")
    rate = d["overall"]["success_rate"] * 100
    print(f"  Overall success rate:  {d['overall']['success']}/{d['overall']['total']} = {rate:.1f}%")

    claim = 93.0
    status = "VALIDATED" if rate >= claim else "NOT MET"
    mark = "PASS" if rate >= claim else "FAIL"
    print(f"  Agent Factory V2 claim: {claim:.0f}%  [{mark}] {status}")
    print(f"  Duration: {result.duration_seconds:.1f}s")
    print()


def print_summary(results: list[ScenarioResult]) -> None:
    """Print comparison table across all scenarios."""
    print()
    print("=" * 72)
    print("  BENCHMARK SUMMARY")
    print("=" * 72)
    print(f"  {'Scenario':<18} {'Patterns':>8} {'Success':>10} {'Rate':>8} {'P@1':>8} {'Time':>8}")
    print(f"  {'-' * 18} {'-' * 8} {'-' * 10} {'-' * 8} {'-' * 8} {'-' * 8}")
    for r in results:
        # P@1 = precision at 1 across in-domain + boundary (ignoring threshold)
        p1_total = len(r.in_domain_results) + len(r.boundary_results)
        p1_hits = r.in_domain_precision_at_1 + r.boundary_precision
        p1_rate = f"{p1_hits / p1_total * 100:.1f}%" if p1_total > 0 else "—"
        print(
            f"  {r.name:<18} {r.training_patterns:>8} "
            f"{r.overall_success:>6}/{r.total_tasks:<3} "
            f"{r.overall_success_rate * 100:>7.1f}% "
            f"{p1_rate:>8} "
            f"{r.duration_seconds:>7.1f}s"
        )
    print("=" * 72)


# ---------------------------------------------------------------------------
# JSON persistence
# ---------------------------------------------------------------------------


def _git_info() -> dict[str, str]:
    info = {}
    for key, cmd in [
        ("commit", ["git", "rev-parse", "--short", "HEAD"]),
        ("branch", ["git", "rev-parse", "--abbrev-ref", "HEAD"]),
    ]:
        try:
            info[key] = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
        except Exception:
            info[key] = "unknown"
    return info


def save_results(
    results: list[ScenarioResult],
    output_dir: Path,
) -> Path:
    """Save benchmark results as timestamped JSON.

    Returns:
        Path to the saved JSON file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    git = _git_info()
    ts = datetime.now(UTC)
    run_id = f"{ts.strftime('%Y%m%dT%H%M%S')}_{git.get('commit', 'unknown')}"

    cal = results[0].calibration if results else None
    report: dict[str, Any] = {
        "run_id": run_id,
        "timestamp": ts.isoformat(),
        "git_commit": git.get("commit"),
        "git_branch": git.get("branch"),
        "embedding_model": cal.model_name if cal else "unknown",
        "calibration": cal.to_dict() if cal else None,
        "scenarios": [r.to_dict() for r in results],
    }

    path = output_dir / f"{run_id}.json"
    path.write_text(json.dumps(report, indent=2))
    return path


def clean_results(output_dir: Path) -> int:
    """Delete all JSON result files from output_dir. Returns count deleted."""
    if not output_dir.exists():
        return 0
    count = 0
    for f in output_dir.glob("*.json"):
        f.unlink()
        count += 1
    return count

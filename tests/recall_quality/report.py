#!/usr/bin/env python
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Recall quality report generator with longitudinal trend support.

Each test session writes a timestamped JSON run file to
tests/recall_quality/results/.  This script reads the full history and
shows both the latest run summary and a trend table so you can track
whether embedding model changes or matcher tuning improved quality.

Usage:
    python tests/recall_quality/report.py [--results-dir DIR] [--last N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_DEFAULT_RESULTS_DIR = Path(__file__).parent / "results"
_THRESHOLDS_PATH = Path(__file__).parent / "thresholds.json"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_history(results_dir: Path) -> list[dict]:
    """Load all run JSON files from results_dir, sorted oldest→newest."""
    runs: list[dict] = []
    if not results_dir.exists():
        return runs
    for path in sorted(results_dir.glob("*.json")):
        if path.name == "recall_quality_report.json":
            continue  # skip legacy report file if present
        try:
            data = json.loads(path.read_text())
            if "run_id" in data and "dimensions" in data:
                runs.append(data)
            # else: skip legacy fragment files
        except Exception as exc:
            print(f"  Warning: could not load {path.name}: {exc}", file=sys.stderr)
    return runs


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _dim_status(dim: dict | None) -> str:
    if dim is None:
        return "  —  "
    return " PASS" if dim.get("pass") else " FAIL"


def _fmt(value: float | None, width: int = 6) -> str:
    if value is None:
        return " " * width + "—"
    return f"{value:.3f}".rjust(width)


def print_latest_summary(run: dict) -> None:
    dims = run.get("dimensions", {})
    d1 = dims.get("D1_recall_precision", {})
    d2 = dims.get("D2_cross_isolation", {})
    d3 = dims.get("D3_noise_rejection", {})
    bnd = dims.get("boundary", {})

    print("\n" + "=" * 66)
    print("  RECALL QUALITY REPORT — latest run")
    print("=" * 66)
    print(f"  Run ID:  {run.get('run_id', '?')}")
    print(f"  Branch:  {run.get('git_branch', '?')}  commit {run.get('git_commit', '?')}")
    print(f"  Model:   {run.get('embedding_model', '?')}")

    thr = run.get("thresholds", {})
    print(f"  Thresholds:  intra={thr.get('intra')}  cross={thr.get('cross')}  noise={thr.get('noise')}")

    print()
    print(f"  {'Dimension':<28}  {'Status':>6}  {'Key metric':>12}")
    print(f"  {'-'*28}  {'-'*6}  {'-'*12}")

    d1_pass = d1.get("clusters_passed", 0)
    d1_total = d1.get("clusters_total", 0)
    print(f"  {'D1 Recall precision':<28}  {_dim_status(d1):>6}  "
          f"avg={_fmt(d1.get('avg_top1_sim'))}  min={_fmt(d1.get('min_top1_sim'))}  "
          f"({d1_pass}/{d1_total} clusters)")

    d2_pass = d2.get("pairs_passed", 0)
    d2_total = d2.get("pairs_total", 0)
    print(f"  {'D2 Cross-cluster isolation':<28}  {_dim_status(d2):>6}  "
          f"max_cross={_fmt(d2.get('max_cross_sim'))}  ({d2_pass}/{d2_total} pairs)")

    d3_fail = d3.get("noise_failed", 0)
    d3_total = d3.get("noise_total", 0)
    print(f"  {'D3 Noise rejection':<28}  {_dim_status(d3):>6}  "
          f"max_noise={_fmt(d3.get('max_noise_sim'))}  ({d3_total - d3_fail}/{d3_total} passed)")

    bnd_matched = bnd.get("matched_either", 0)
    bnd_total = bnd.get("tasks_total", 0)
    bnd_both = bnd.get("matched_both", 0)
    print(f"  {'Boundary tasks':<28}  {_dim_status(bnd):>6}  "
          f"matched={bnd_matched}/{bnd_total}  both={bnd_both}")

    # Per-cluster D1 detail
    per_cluster = d1.get("per_cluster", {})
    if per_cluster:
        failed = [(cid, v["top1_sim"]) for cid, v in per_cluster.items() if not v.get("pass")]
        if failed:
            print(f"\n  D1 failing clusters:")
            for cid, sim in failed:
                print(f"    {cid}: top1_sim={sim:.4f}")

    print("=" * 66)


def print_trend(history: list[dict], last: int) -> None:
    if len(history) < 2:
        return

    runs = history[-last:] if last else history
    print("\n" + "=" * 90)
    print("  TREND  (oldest → newest)")
    print("=" * 90)
    header = (f"  {'Commit':<9}  {'Branch':<14}  {'Model':<22}  "
              f"{'D1 avg':>7}  {'D1 min':>7}  {'D2 max':>8}  {'D3 max':>8}  "
              f"{'Bnd':>5}  {'OK?':>4}")
    print(header)
    print("  " + "-" * 88)

    for run in runs:
        dims = run.get("dimensions", {})
        d1 = dims.get("D1_recall_precision", {})
        d2 = dims.get("D2_cross_isolation", {})
        d3 = dims.get("D3_noise_rejection", {})
        bnd = dims.get("boundary", {})

        all_pass = all(
            d.get("pass") is not False
            for d in (d1, d2, d3, bnd) if d
        )
        status = " OK" if all_pass else "FAIL"
        bnd_frac = (f"{bnd.get('matched_either', 0)}/{bnd.get('tasks_total', 0)}"
                    if bnd else "—")

        print(
            f"  {run.get('git_commit', '?'):<9}  "
            f"{run.get('git_branch', '?'):<14}  "
            f"{run.get('embedding_model', '?'):<22}  "
            f"{_fmt(d1.get('avg_top1_sim'))}  "
            f"{_fmt(d1.get('min_top1_sim'))}  "
            f"{_fmt(d2.get('max_cross_sim'), 8)}  "
            f"{_fmt(d3.get('max_noise_sim'), 8)}  "
            f"{bnd_frac:>5}  "
            f"{status:>4}"
        )

    print("=" * 90)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(results_dir: Path, last: int) -> None:
    history = load_history(results_dir)
    if not history:
        print(f"No run files found in {results_dir}. Run the test suite first.")
        sys.exit(1)

    print_latest_summary(history[-1])
    print_trend(history, last)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recall quality report with longitudinal trends.")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=_DEFAULT_RESULTS_DIR,
        help=f"Directory with run JSON files (default: {_DEFAULT_RESULTS_DIR})",
    )
    parser.add_argument(
        "--last",
        type=int,
        default=20,
        metavar="N",
        help="Show last N runs in the trend table (default: 20, 0=all)",
    )
    args = parser.parse_args()
    main(args.results_dir, args.last)

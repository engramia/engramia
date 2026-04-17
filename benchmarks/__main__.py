# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Benchmark CLI entry point.

Usage:
    python -m benchmarks                          # run all scenarios
    python -m benchmarks --scenario full          # single scenario
    python -m benchmarks --clean                  # purge previous results
    python -m benchmarks --keep                   # keep temp storage
    python -m benchmarks --output ./my-results/   # custom output dir
    python -m benchmarks --validate               # validate dataset only
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_DEFAULT_OUTPUT = Path(__file__).parent / "results"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks",
        description="Engramia benchmark suite — reproducible recall quality validation.",
    )
    parser.add_argument(
        "--scenario",
        choices=["all", "cold", "warm", "full"],
        default="all",
        help="Which scenario to run (default: all).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        metavar="DIR",
        help=f"Directory for JSON result files (default: {_DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete all previous result files before running.",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep temporary storage after run (for debugging).",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate dataset integrity and exit (no benchmark run).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )

    # --- Validate only ---
    if args.validate:
        from benchmarks.dataset import validate_dataset

        issues = validate_dataset()
        if issues:
            print("Dataset validation warnings:")
            for w in issues:
                print(f"  {w}")
            return 1
        from benchmarks.dataset import build_dataset

        ds = build_dataset()
        cats: dict[str, int] = {}
        for e in ds:
            cats[e.category] = cats.get(e.category, 0) + 1
        print(f"Dataset OK: {len(ds)} tasks — {cats}")
        return 0

    # --- Clean ---
    if args.clean:
        from benchmarks.report import clean_results

        deleted = clean_results(args.output)
        print(f"Cleaned {deleted} result file(s) from {args.output}")

    # --- Run benchmarks ---
    from benchmarks.report import print_scenario, print_summary, save_results
    from benchmarks.runner import BenchmarkRunner

    runner = BenchmarkRunner(keep=args.keep)

    if args.scenario == "all":
        results = runner.run_all()
    elif args.scenario == "cold":
        results = [runner.run_cold()]
    elif args.scenario == "warm":
        results = [runner.run_warm()]
    elif args.scenario == "full":
        results = [runner.run_full()]
    else:
        results = []

    # --- Report ---
    for r in results:
        print_scenario(r)

    if len(results) > 1:
        print_summary(results)

    # Save JSON
    path = save_results(results, args.output)
    print(f"Results saved to: {path}")

    # --- Exit code: pass if full_library >= 90% ---
    full = next((r for r in results if r.name == "full_library"), None)
    if full and full.overall_success_rate < 0.90:
        print(f"\nFAIL: full_library success rate {full.overall_success_rate:.1%} < 90%")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
"""Update LICENSE.txt for a new release.

Each release of Engramia ships with its own Change Date per BUSL 1.1's
per-version scope (see LICENSE.txt § 69-70 — "This License applies
separately for each version of the Licensed Work and the Change Date may
vary for each version"). This script rewrites the `Licensed Work:` and
`Change Date:` lines in place; everything else is untouched.

Examples:
    python scripts/update_license.py --version 1.0.0
    python scripts/update_license.py --version 1.0.0 --change-date 2032-06-01
    python scripts/update_license.py --version 1.0.0 --dry-run

Defaults:
    --version       required
    --change-date   today + 4 years (UTC)
    --year          current UTC year (used in copyright notice)
    --licensor      "Marek Čermák"
    --license-path  LICENSE.txt (relative to cwd)
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import re
import sys
from pathlib import Path

LICENSED_WORK_RE = re.compile(r"^Licensed Work:.*$", re.MULTILINE)
CHANGE_DATE_RE = re.compile(r"^Change Date:.*$", re.MULTILINE)
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def build_licensed_work(version: str, year: int, licensor: str) -> str:
    return (
        f"Licensed Work: Engramia, version {version}. "
        f"Licensed work is (c) {year} {licensor}"
    )


def build_change_date(change_date: str) -> str:
    return f"Change Date: {change_date}"


def update_license_text(
    text: str,
    version: str,
    year: int,
    change_date: str,
    licensor: str = "Marek Čermák",
) -> str:
    """Return LICENSE text with Licensed Work + Change Date rewritten.

    Raises ValueError if either anchor line is missing from the input.
    """
    new_licensed = build_licensed_work(version, year, licensor)
    new_change = build_change_date(change_date)

    text, licensed_count = LICENSED_WORK_RE.subn(new_licensed, text, count=1)
    text, change_count = CHANGE_DATE_RE.subn(new_change, text, count=1)

    if licensed_count != 1:
        raise ValueError("Could not find 'Licensed Work:' line in LICENSE.txt")
    if change_count != 1:
        raise ValueError("Could not find 'Change Date:' line in LICENSE.txt")

    return text


def default_change_date(today: dt.date | None = None) -> str:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    return today.replace(year=today.year + 4).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Update LICENSE.txt for a new BUSL 1.1 release.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", required=True, help="Release version (X.Y.Z)")
    parser.add_argument("--change-date", help="BUSL Change Date (YYYY-MM-DD)")
    parser.add_argument("--year", type=int, help="Copyright year (default: current UTC year)")
    parser.add_argument("--licensor", default="Marek Čermák")
    parser.add_argument("--license-path", default="LICENSE.txt")
    parser.add_argument("--dry-run", action="store_true", help="Print diff, do not write")
    args = parser.parse_args(argv)

    if not VERSION_RE.match(args.version):
        parser.error(f"Invalid version: {args.version!r} (expected X.Y.Z)")

    today = dt.datetime.now(dt.timezone.utc).date()
    change_date = args.change_date or default_change_date(today)
    year = args.year if args.year is not None else today.year

    if not DATE_RE.match(change_date):
        parser.error(f"Invalid date: {change_date!r} (expected YYYY-MM-DD)")

    license_path = Path(args.license_path)
    if not license_path.exists():
        parser.error(f"{license_path} not found in {Path.cwd()}")

    original = license_path.read_text(encoding="utf-8")
    updated = update_license_text(
        original, args.version, year, change_date, args.licensor
    )

    if original == updated:
        print(
            f"No changes — LICENSE already at version={args.version}, "
            f"change_date={change_date}",
            file=sys.stderr,
        )
        return 0

    if args.dry_run:
        print(f"--- {license_path}")
        print(f"+++ {license_path} (proposed)")
        sys.stdout.writelines(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                lineterm="",
            )
        )
        return 0

    license_path.write_text(updated, encoding="utf-8")
    print(
        f"LICENSE.txt updated: version={args.version}, "
        f"year={year}, change_date={change_date}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""C02 — CSV Aggregation snippets."""

GOOD: dict = {
    "eval_score": 9.0,
    "output": "{'electronics': 4200.0, 'clothing': 1850.5, 'food': 920.0}",
    "code": '''\
import csv
from collections import defaultdict
from pathlib import Path


def aggregate_csv_by_category(
    path: str | Path,
    category_col: str,
    amount_col: str,
    *,
    encoding: str = "utf-8",
) -> dict[str, float]:
    """Sum *amount_col* values grouped by *category_col*.

    Args:
        path: CSV file path.
        category_col: Column to group on.
        amount_col: Numeric column to sum.
        encoding: File encoding.

    Returns:
        Dict mapping category → total amount.

    Raises:
        ValueError: If *amount_col* contains a non-numeric value.
    """
    totals: dict[str, float] = defaultdict(float)
    with Path(path).open(encoding=encoding) as fh:
        for row in csv.DictReader(fh):
            try:
                totals[row[category_col]] += float(row[amount_col])
            except (ValueError, KeyError) as exc:
                raise ValueError(f"Bad row {dict(row)}: {exc}") from exc
    return dict(totals)
''',
}

MEDIUM: dict = {
    "eval_score": 6.0,
    "output": "{'electronics': 4200.0, 'clothing': 1850.5}",
    "code": """\
import csv
from collections import defaultdict

def group_sum(filepath, group_col, sum_col):
    totals = defaultdict(float)
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            totals[row[group_col]] += float(row[sum_col])
    return dict(totals)
""",
}

BAD: dict = {
    "eval_score": 2.0,
    "output": "",
    "code": """\
def aggregate(file, cat_col, amt_col):
    lines = open(file).readlines()
    header = lines[0].strip().split(",")
    cat_idx = header.index(cat_col)
    amt_idx = header.index(amt_col)
    result = {}
    # O(n*m): for each row, scan result dict linearly
    for line in lines[1:]:
        parts = line.strip().split(",")
        cat = parts[cat_idx]
        amt = float(parts[amt_idx])
        found = False
        for k in result:
            if k == cat:
                result[k] = result[k] + amt
                found = True
        if not found:
            result[cat] = amt
    return result
""",
}

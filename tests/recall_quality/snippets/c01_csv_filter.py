# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""C01 — CSV Row Filtering snippets (good / medium / bad)."""

GOOD: dict = {
    "eval_score": 9.0,
    "output": "Found 42 active rows out of 150 total.",
    "code": '''\
import csv
from pathlib import Path


def filter_csv_rows(
    path: str | Path,
    column: str,
    value: str,
    *,
    encoding: str = "utf-8",
) -> list[dict[str, str]]:
    """Filter CSV rows where *column* equals *value*.

    Args:
        path: Path to the CSV file.
        column: Column name to filter on.
        value: Required value (case-sensitive).
        encoding: File encoding (default utf-8).

    Returns:
        List of matching row dicts.

    Raises:
        FileNotFoundError: If *path* does not exist.
        KeyError: If *column* is not in the CSV header.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    with file_path.open(encoding=encoding) as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames and column not in reader.fieldnames:
            raise KeyError(
                f"Column \'{column}\' not found. Available: {list(reader.fieldnames)}"
            )
        return [row for row in reader if row.get(column) == value]
''',
}

MEDIUM: dict = {
    "eval_score": 6.0,
    "output": "Filtered 42 rows.",
    "code": """\
import csv

def filter_rows(filepath, col, val):
    with open(filepath) as f:
        reader = csv.DictReader(f)
        results = []
        for row in reader:
            if row[col] == val:
                results.append(row)
    return results
""",
}

BAD: dict = {
    "eval_score": 2.5,
    "output": "",
    "code": """\
def filter(file, col, val):
    f = open(file)
    lines = f.readlines()
    header = lines[0].strip().split(",")
    out = []
    for line in lines[1:]:
        parts = line.split(",")
        # BUG: does not handle quoted commas
        # BUG: no strip() on values
        if parts[header.index(col)] == val:
            out.append(parts)
    return out
""",
}

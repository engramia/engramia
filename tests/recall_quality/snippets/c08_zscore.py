# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""C08 — Z-Score Normalization snippets."""

GOOD: dict = {
    "eval_score": 9.0,
    "output": "[-1.414, -0.707, 0.0, 0.707, 1.414]",
    "code": '''\
from typing import Sequence

import numpy as np


def zscore_normalize(
    values: Sequence[float],
    *,
    ddof: int = 0,
    constant_fill: float = 0.0,
) -> list[float]:
    """Z-score standardize a numeric sequence.

    Args:
        values: Input numbers.
        ddof: Delta degrees of freedom for std calculation (0=population, 1=sample).
        constant_fill: Value to return for each element when std == 0
            (all inputs identical).  Defaults to 0.0 — center without scaling.

    Returns:
        Normalized values as a list.  Empty input → empty list.
    """
    if not values:
        return []
    arr = np.asarray(values, dtype=float)
    mean = arr.mean()
    std = arr.std(ddof=ddof)
    if std == 0.0:
        return [constant_fill] * len(arr)
    return ((arr - mean) / std).tolist()
''',
}

MEDIUM: dict = {
    "eval_score": 6.0,
    "output": "[-1.41, -0.71, 0.0, 0.71, 1.41]",
    "code": """\
def zscore(values):
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    std = variance ** 0.5
    # BUG: ZeroDivisionError if std == 0
    return [(x - mean) / std for x in values]
""",
}

BAD: dict = {
    "eval_score": 2.5,
    "output": "",
    "code": """\
def normalize(data):
    # BAD: divides by len instead of std — this is mean normalization, not z-score
    mean = sum(data) / len(data)
    return [(x - mean) / len(data) for x in data]
""",
}

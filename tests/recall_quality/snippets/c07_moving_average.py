# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""C07 — Moving Average snippets."""

GOOD: dict = {
    "eval_score": 9.0,
    "output": "[nan, nan, nan, nan, nan, nan, 4.0, 5.0, 6.0, 7.0]",
    "code": '''\
from typing import Sequence

import numpy as np


def moving_average(
    values: Sequence[float],
    window: int = 7,
    *,
    min_periods: int | None = None,
) -> list[float]:
    """Compute a rolling moving average.

    Args:
        values: Input numeric sequence.
        window: Rolling window size (default 7).
        min_periods: Minimum non-NaN values required to produce a result.
            Defaults to *window* (strict — NaN until window is full).

    Returns:
        List of floats the same length as *values*.
        Leading values (before window fills) are NaN.
    """
    if not values:
        return []
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")

    arr = np.asarray(values, dtype=float)
    kernel = np.ones(window) / window
    # Use "same" mode then zero-pad edges with NaN
    result = np.convolve(arr, kernel, mode="full")[: len(arr)]
    # Positions before the window fills are invalid
    effective_min = min_periods if min_periods is not None else window
    result[: effective_min - 1] = np.nan
    return result.tolist()
''',
}

MEDIUM: dict = {
    "eval_score": 6.0,
    "output": "[4.0, 5.0, 6.0, 7.0]",
    "code": '''\
from collections import deque

def moving_avg(values, window=7):
    buf = deque(maxlen=window)
    result = []
    for v in values:
        buf.append(v)
        if len(buf) == window:
            result.append(sum(buf) / window)
    return result
''',
}

BAD: dict = {
    "eval_score": 2.0,
    "output": "",
    "code": '''\
def moving_avg(values, window=7):
    result = []
    for i in range(len(values) - window + 1):
        # BAD: O(n*window) — recomputes full sum each iteration
        total = 0
        for j in range(window):
            total += values[i + j]
        result.append(total / window)
    # BUG: returns shorter list with no NaN padding — length mismatch
    return result
''',
}

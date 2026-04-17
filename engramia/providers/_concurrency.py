# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Global LLM concurrency semaphore.

Limits the number of simultaneous LLM API calls across all providers to
prevent runaway costs and API-side throttling when multiple requests are
processed concurrently.

Configure via env var:
    ENGRAMIA_LLM_CONCURRENCY   max parallel LLM calls (default: 10)
"""

import os
import threading

_sem = threading.BoundedSemaphore(int(os.environ.get("ENGRAMIA_LLM_CONCURRENCY", "10")))


def llm_semaphore() -> threading.BoundedSemaphore:
    """Return the process-wide LLM concurrency semaphore."""
    return _sem

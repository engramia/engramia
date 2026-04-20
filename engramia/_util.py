# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Shared internal utilities for Engramia."""

import hashlib
import json
import re
import time
from typing import Literal

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

PATTERNS_PREFIX = "patterns"
"""Storage key prefix for all success patterns."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _pattern_key(task: str) -> str:
    """Generate a unique storage key for a task pattern.

    Args:
        task: Natural language description of the task.

    Returns:
        Storage key in the format ``patterns/<hash8>_<ts_ms>_<rand6>``.
        The trailing random suffix prevents key collisions when two
        ``learn()`` calls land in the same millisecond (e.g. bulk
        ``import_data``, multi-threaded API handlers, load-test
        scenarios). Without it the second writer silently overwrote
        the first's pattern.
    """
    import secrets

    task_hash = hashlib.sha256(task.encode()).hexdigest()[:8]
    ts = int(time.time() * 1000)
    rand = secrets.token_urlsafe(4).replace("-", "").replace("_", "")[:6]
    return f"{PATTERNS_PREFIX}/{task_hash}_{ts}_{rand}"


def jaccard(a: str, b: str) -> float:
    """Word-level Jaccard similarity between two strings.

    Args:
        a: First string.
        b: Second string.

    Returns:
        Jaccard index (0.0-1.0).
    """
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def reuse_tier(similarity: float) -> Literal["duplicate", "adapt", "fresh"]:
    """Classify a similarity score into a reuse tier.

    Args:
        similarity: Cosine similarity (0.0-1.0).

    Returns:
        One of ``"duplicate"``, ``"adapt"``, or ``"fresh"``.
    """
    from engramia.types import SIMILARITY_ADAPT, SIMILARITY_DUPLICATE

    if similarity >= SIMILARITY_DUPLICATE:
        return "duplicate"
    if similarity >= SIMILARITY_ADAPT:
        return "adapt"
    return "fresh"


def extract_json_from_llm(text: str) -> dict:
    """Extract a JSON object from LLM response text.

    Handles raw JSON, markdown code blocks, and embedded JSON objects.

    Args:
        text: Raw LLM response string.

    Returns:
        Parsed JSON dict.

    Raises:
        ValueError: If no valid JSON object is found in the text.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Markdown code block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # Any JSON object in the text — scan with JSONDecoder to find the first valid object
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        start = text.find("{", idx)
        if start == -1:
            break
        try:
            obj, _ = decoder.raw_decode(text, start)
            return obj
        except json.JSONDecodeError:
            idx = start + 1
    raise ValueError(f"No valid JSON found in LLM response: {text[:300]}")

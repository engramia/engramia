# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Shared internal utilities for Engramia."""

import json
import re
from typing import Literal

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

PATTERNS_PREFIX = "patterns"
"""Storage key prefix for all success patterns."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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
    # Any JSON object in the text
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"No valid JSON found in LLM response: {text[:300]}")

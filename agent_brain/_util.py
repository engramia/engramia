"""Shared internal utilities for Agent Brain."""

import json
import re


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

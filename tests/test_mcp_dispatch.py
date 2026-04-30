# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Tests for engramia.mcp.dispatch — shared low-level dispatch.

Covers the two new tools (engramia_evolve, engramia_analyze_failures) added
in Phase 6.6 for the hosted transport. The seven legacy tools are already
covered by tests/test_mcp.py (which exercises the same dispatch via the
stdio shim). Re-tests of those would duplicate.
"""

from unittest.mock import MagicMock

import pytest

from engramia.evolution.failure_cluster import FailureCluster
from engramia.evolution.prompt_evolver import EvolutionResult
from engramia.mcp.dispatch import dispatch_to_memory, format_result_text
from engramia.mcp.errors import ToolNotFoundError


def test_evolve_returns_dict_with_expected_fields():
    mem = MagicMock()
    mem.evolve_prompt.return_value = EvolutionResult(
        improved_prompt="You are a careful coder...",
        changes=["Added defensive check"],
        issues_addressed=["null pointer"],
        accepted=True,
        reason="Improvement clear",
    )
    result = dispatch_to_memory(
        mem,
        "engramia_evolve",
        {
            "role": "coder",
            "current_prompt": "You are a coder.",
            "num_issues": 5,
        },
    )
    assert result == {
        "improved_prompt": "You are a careful coder...",
        "changes": ["Added defensive check"],
        "issues_addressed": ["null pointer"],
        "accepted": True,
        "reason": "Improvement clear",
    }
    mem.evolve_prompt.assert_called_once_with(
        role="coder", current_prompt="You are a coder.", num_issues=5
    )


def test_evolve_default_num_issues_is_5():
    mem = MagicMock()
    mem.evolve_prompt.return_value = EvolutionResult(
        improved_prompt="x", changes=[], issues_addressed=[], accepted=False, reason="r"
    )
    dispatch_to_memory(
        mem, "engramia_evolve", {"role": "coder", "current_prompt": "p"}
    )
    mem.evolve_prompt.assert_called_once_with(
        role="coder", current_prompt="p", num_issues=5
    )


def test_analyze_failures_returns_list_of_clusters():
    mem = MagicMock()
    mem.analyze_failures.return_value = [
        FailureCluster(
            representative="missing null check",
            members=["null check missing", "no null guard"],
            total_count=12,
            avg_score=0.85,
        ),
        FailureCluster(
            representative="bad regex",
            members=["bad regex"],
            total_count=3,
            avg_score=0.5,
        ),
    ]
    result = dispatch_to_memory(mem, "engramia_analyze_failures", {"min_count": 2})
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["representative"] == "missing null check"
    assert result[0]["total_count"] == 12
    assert result[0]["members"] == ["null check missing", "no null guard"]
    mem.analyze_failures.assert_called_once_with(min_count=2)


def test_analyze_failures_default_min_count_is_1():
    mem = MagicMock()
    mem.analyze_failures.return_value = []
    dispatch_to_memory(mem, "engramia_analyze_failures", {})
    mem.analyze_failures.assert_called_once_with(min_count=1)


def test_unknown_tool_raises_tool_not_found_error():
    mem = MagicMock()
    with pytest.raises(ToolNotFoundError):
        dispatch_to_memory(mem, "nonexistent_tool", {})


def test_tool_not_found_is_also_value_error_for_backward_compat():
    """Pre-refactor stdio dispatch raised plain ValueError. Inheritance
    keeps existing ``except ValueError`` handlers working."""
    mem = MagicMock()
    with pytest.raises(ValueError):
        dispatch_to_memory(mem, "nonexistent_tool", {})


def test_format_result_text_serialises_dict():
    text = format_result_text({"foo": "bar", "n": 1})
    assert '"foo"' in text
    assert '"bar"' in text
    assert '"n": 1' in text

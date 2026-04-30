# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Tests for engramia.mcp.tools — shared catalog + tier filter.

Covers:
- 9 tools in catalog, all have unique names.
- Tier rank ordering: dev < pro < team < business < enterprise.
- Hosted MCP minimum tier is 'team' (matches PRICING_TIERS_260428.md).
- tools_for() filters correctly by tier and RBAC.
- 'compose', 'evolve', 'analyze_failures' require Business+.
- Owner role with '*' wildcard sees every tool in their tier band.
- Reader role on Team sees only read-only tools.
"""

import pytest

from engramia.api.permissions import PERMISSIONS
from engramia.mcp.tools import (
    ALL_TOOLS,
    MIN_TIER_FOR_HOSTED_MCP,
    get_entry,
    stdio_tools,
    tier_satisfies,
    tools_for,
)


def test_catalog_has_nine_tools():
    assert len(ALL_TOOLS) == 9


def test_all_tool_names_unique():
    names = [e.name for e in ALL_TOOLS]
    assert len(set(names)) == len(names)


def test_min_tier_for_hosted_is_team():
    assert MIN_TIER_FOR_HOSTED_MCP == "team"


@pytest.mark.parametrize(
    "current,required,expected",
    [
        ("developer", "team", False),
        ("pro", "team", False),
        ("team", "team", True),
        ("team", "business", False),
        ("business", "team", True),
        ("business", "business", True),
        ("enterprise", "business", True),
        ("enterprise", "enterprise", True),
    ],
)
def test_tier_satisfies(current, required, expected):
    assert tier_satisfies(current, required) is expected


def test_get_entry_known_returns_tool_entry():
    entry = get_entry("engramia_recall")
    assert entry is not None
    assert entry.permission == "recall"
    assert entry.min_tier == "team"


def test_get_entry_unknown_returns_none():
    assert get_entry("nonexistent_tool") is None


def test_stdio_tools_returns_full_catalog():
    """Per ADR-003, stdio shares the catalog (free bonus from refactor)."""
    assert len(stdio_tools()) == 9


def test_tools_for_team_owner_excludes_business_only_tools():
    perms = PERMISSIONS["owner"]
    tools = tools_for("team", perms)
    names = {t.name for t in tools}
    # Team can do all the basic ops...
    assert {
        "engramia_learn",
        "engramia_recall",
        "engramia_evaluate",
        "engramia_feedback",
        "engramia_metrics",
        "engramia_aging",
    }.issubset(names)
    # ...but not the Business-tier-gated ones.
    assert "engramia_compose" not in names
    assert "engramia_evolve" not in names
    assert "engramia_analyze_failures" not in names


def test_tools_for_business_owner_includes_all_nine():
    perms = PERMISSIONS["owner"]
    tools = tools_for("business", perms)
    names = {t.name for t in tools}
    assert len(names) == 9


def test_tools_for_pro_returns_empty():
    """Pro tier cannot use hosted MCP at all."""
    perms = PERMISSIONS["owner"]
    tools = tools_for("pro", perms)
    assert tools == []


def test_tools_for_team_reader_excludes_write_tools():
    perms = PERMISSIONS["reader"]
    tools = tools_for("team", perms)
    names = {t.name for t in tools}
    # Reader can read patterns + feedback + metrics
    assert "engramia_recall" in names
    assert "engramia_feedback" in names
    assert "engramia_metrics" in names
    # ... but not create or mutate
    assert "engramia_learn" not in names
    assert "engramia_evaluate" not in names
    assert "engramia_aging" not in names


def test_tools_for_team_editor_includes_evaluate_excludes_business():
    perms = PERMISSIONS["editor"]
    tools = tools_for("team", perms)
    names = {t.name for t in tools}
    assert "engramia_evaluate" in names
    assert "engramia_learn" in names
    assert "engramia_compose" not in names  # editor on team — tier-blocked
    assert "engramia_evolve" not in names


def test_tools_for_business_editor_includes_compose_evolve_analyze():
    perms = PERMISSIONS["editor"]
    tools = tools_for("business", perms)
    names = {t.name for t in tools}
    assert "engramia_compose" in names
    assert "engramia_evolve" in names
    assert "engramia_analyze_failures" in names


def test_quota_kind_mapping_mirrors_rest():
    """OQ-002 resolved: quota_kind aligns with REST behavior."""
    assert get_entry("engramia_learn").quota_kind == "patterns"
    assert get_entry("engramia_evaluate").quota_kind == "eval_runs"
    assert get_entry("engramia_evolve").quota_kind == "eval_runs"
    assert get_entry("engramia_recall").quota_kind == "none"
    assert get_entry("engramia_metrics").quota_kind == "none"

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Shared MCP tool catalog.

Single source of truth for tool definitions used by both transports:

- ``engramia/mcp/server.py`` (stdio) — uses :data:`STDIO_TOOLS` (full catalog,
  no tier filter, no RBAC; self-host is unscoped).
- ``engramia/mcp/http_server.py`` (hosted, Streamable HTTP) — uses
  :func:`tools_for` to filter by the caller's plan tier and RBAC role.

Adding a new tool is a single-file edit: append a :class:`ToolEntry` to
:data:`ALL_TOOLS` with its name, description, inputSchema, RBAC permission,
minimum tier, and quota kind. The dispatch logic in ``dispatch.py`` reads the
same entry for routing and policy enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import mcp.types as types

# ---------------------------------------------------------------------------
# Tier ordering — used for tier-gate comparisons.
# ---------------------------------------------------------------------------

PlanTier = Literal["developer", "pro", "team", "business", "enterprise"]
QuotaKind = Literal["eval_runs", "patterns", "none"]

_TIER_RANK: dict[str, int] = {
    "developer": 0,
    "pro": 1,
    "team": 2,
    "business": 3,
    "enterprise": 4,
}

#: Minimum tier required to *open* a hosted MCP session at all. Tiers below
#: this get HTTP 402 on session initialize.
MIN_TIER_FOR_HOSTED_MCP: PlanTier = "team"


def tier_satisfies(current: str, required: str) -> bool:
    """Return True iff *current* tier is at least *required*."""
    return _TIER_RANK.get(current, -1) >= _TIER_RANK.get(required, 99)


# ---------------------------------------------------------------------------
# Tool definitions — shared by stdio and hosted.
# ---------------------------------------------------------------------------

_TOOL_LEARN = types.Tool(
    name="engramia_learn",
    description=(
        "Record a successful agent run so Engramia can store it as a reusable pattern. "
        "Stores the task, code, and eval score."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Natural language task description."},
            "code": {"type": "string", "description": "Agent source code / solution."},
            "eval_score": {
                "type": "number",
                "description": "Quality score 0-10.",
                "minimum": 0,
                "maximum": 10,
            },
            "output": {"type": "string", "description": "Captured stdout (optional)."},
        },
        "required": ["task", "code", "eval_score"],
    },
)

_TOOL_RECALL = types.Tool(
    name="engramia_recall",
    description=(
        "Find stored patterns most relevant to a new task using semantic "
        "search with optional eval-score weighting and recency bias."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Task to find relevant patterns for."},
            "limit": {
                "type": "integer",
                "description": "Max results (1-50).",
                "minimum": 1,
                "maximum": 50,
                "default": 5,
            },
            "recency_weight": {
                "type": "number",
                "description": (
                    "Bias toward recently-stored patterns via exponential "
                    "half-life decay. 0.0 = off (default), 1.0 = full decay."
                ),
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.0,
            },
            "recency_half_life_days": {
                "type": "number",
                "description": "Half-life of the recency decay, in days.",
                "exclusiveMinimum": 0.0,
                "default": 30.0,
            },
        },
        "required": ["task"],
    },
)

_TOOL_EVALUATE = types.Tool(
    name="engramia_evaluate",
    description=(
        "Run N independent LLM evaluations on an agent run and return median "
        "score, variance, and feedback."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "task": {"type": "string"},
            "code": {"type": "string"},
            "output": {"type": "string", "description": "Captured stdout (optional)."},
            "num_evals": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "default": 3,
            },
        },
        "required": ["task", "code"],
    },
)

_TOOL_COMPOSE = types.Tool(
    name="engramia_compose",
    description=(
        "[Experimental] Decompose a high-level task into a validated multi-agent pipeline. "
        "Each stage is matched against stored patterns."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "High-level task to decompose."},
        },
        "required": ["task"],
    },
)

_TOOL_FEEDBACK = types.Tool(
    name="engramia_feedback",
    description="Return top recurring quality issues suitable for injection into agent prompts.",
    inputSchema={
        "type": "object",
        "properties": {
            "task_type": {
                "type": "string",
                "description": "Filter by task type prefix (optional).",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "default": 4,
            },
        },
    },
)

_TOOL_METRICS = types.Tool(
    name="engramia_metrics",
    description="Return aggregate Engramia statistics: runs, success rate, pattern count, reuse rate.",
    inputSchema={"type": "object", "properties": {}},
)

_TOOL_AGING = types.Tool(
    name="engramia_aging",
    description=(
        "Apply time-based decay to all stored patterns (2%/week) and prune those below the minimum threshold."
    ),
    inputSchema={"type": "object", "properties": {}},
)

_TOOL_EVOLVE = types.Tool(
    name="engramia_evolve",
    description=(
        "Generate an improved system prompt for an agent role by analyzing recurring failure feedback. "
        "Does NOT run A/B evaluation — returns a candidate prompt for the caller to validate."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "role": {
                "type": "string",
                "description": "Agent role (e.g. 'coder', 'eval', 'architect').",
            },
            "current_prompt": {
                "type": "string",
                "description": "The current system prompt to improve.",
            },
            "num_issues": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "default": 5,
                "description": "Number of top failure issues to address.",
            },
        },
        "required": ["role", "current_prompt"],
    },
)

_TOOL_ANALYZE_FAILURES = types.Tool(
    name="engramia_analyze_failures",
    description=(
        "Cluster recurring failure feedback into systemic issues with counts and example feedback strings."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "min_count": {
                "type": "integer",
                "minimum": 1,
                "default": 1,
                "description": "Minimum cluster occurrence count.",
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Tool entry: tool definition + policy metadata.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolEntry:
    """One row of the tool catalog.

    Attributes:
        name: Tool name (must match ``tool.name``). Stored explicitly so that
            tests stubbing :class:`mcp.types.Tool` with ``MagicMock`` (where
            ``.name`` returns a mock attribute, not the string) can still look
            up entries reliably.
        tool: The MCP tool definition (name, description, JSON schema).
        permission: Required RBAC permission string from
            :data:`engramia.api.permissions.PERMISSIONS`.
        min_tier: Minimum plan tier that may call this tool over hosted
            transport. Stdio ignores tier — it is single-tenant by definition.
        quota_kind: Which billing quota the call debits, mirroring REST.
            ``"none"`` for read-only or aggregate operations.
    """

    name: str
    tool: types.Tool
    permission: str
    min_tier: PlanTier
    quota_kind: QuotaKind

    def visible_to(self, plan_tier: str, role_perms: frozenset[str]) -> bool:
        """Filter rule for ``tools/list``: hide if tier *or* RBAC blocks it.

        Owners (`*` permission) see every tool in their tier band.
        """
        if not tier_satisfies(plan_tier, self.min_tier):
            return False
        if "*" in role_perms:
            return True
        return self.permission in role_perms


ALL_TOOLS: list[ToolEntry] = [
    ToolEntry("engramia_learn",             _TOOL_LEARN,            "learn",            "team",     "patterns"),
    ToolEntry("engramia_recall",            _TOOL_RECALL,           "recall",           "team",     "none"),
    ToolEntry("engramia_evaluate",          _TOOL_EVALUATE,         "evaluate",         "team",     "eval_runs"),
    ToolEntry("engramia_feedback",          _TOOL_FEEDBACK,         "feedback:read",    "team",     "none"),
    ToolEntry("engramia_metrics",           _TOOL_METRICS,          "metrics",          "team",     "none"),
    ToolEntry("engramia_aging",             _TOOL_AGING,            "aging",            "team",     "none"),
    ToolEntry("engramia_compose",           _TOOL_COMPOSE,          "compose",          "business", "none"),
    ToolEntry("engramia_evolve",            _TOOL_EVOLVE,           "evolve",           "business", "eval_runs"),
    ToolEntry("engramia_analyze_failures",  _TOOL_ANALYZE_FAILURES, "analyze_failures", "business", "none"),
]


_BY_NAME: dict[str, ToolEntry] = {e.name: e for e in ALL_TOOLS}


def get_entry(name: str) -> ToolEntry | None:
    """Lookup a tool entry by name."""
    return _BY_NAME.get(name)


def stdio_tools() -> list[types.Tool]:
    """All tool definitions for the stdio transport (no policy filter)."""
    return [e.tool for e in ALL_TOOLS]


def tools_for(plan_tier: str, role_perms: frozenset[str]) -> list[types.Tool]:
    """Filtered tool list for hosted transport — applies tier + RBAC gates.

    Per OQ-001 (resolved 2026-04-29): blocked tools are *hidden*, not returned
    with an ``unavailable`` flag. Discoverability handled in dashboard UX.
    """
    return [e.tool for e in ALL_TOOLS if e.visible_to(plan_tier, role_perms)]

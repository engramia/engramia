# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Shared MCP tool dispatch.

Two layers:

- :func:`dispatch_to_memory` — synchronous, transport-neutral. Given a
  :class:`Memory` instance, a tool name, and arguments, route to the right
  Memory method and return the JSON-serialisable result. Used by both stdio
  (``server.py``) and hosted (``http_server.py``).

- :func:`format_result_text` — render the JSON-serialisable result back into
  a single-line MCP ``TextContent`` payload, also shared between transports.

Policy enforcement (RBAC, tier gate, quota debit, audit) lives one layer up
in ``http_server.py`` — stdio is unscoped self-host and bypasses all of it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engramia import Memory


def dispatch_to_memory(mem: Memory, name: str, arguments: dict[str, Any]) -> Any:
    """Route an MCP tool call to the corresponding Memory operation.

    Synchronous — callers that need async should wrap in
    ``asyncio.to_thread``. Memory itself is sync.

    Returns a JSON-serialisable Python object (dict, list, etc.). Raises
    :class:`engramia.mcp.errors.ToolNotFoundError` for unknown tool names;
    other exceptions (Pydantic validation, ProviderError, StorageError, ...)
    propagate to the caller verbatim.
    """
    if name == "engramia_learn":
        result = mem.learn(
            task=arguments["task"],
            code=arguments["code"],
            eval_score=float(arguments["eval_score"]),
            output=arguments.get("output"),
        )
        return {"stored": result.stored, "pattern_count": result.pattern_count}

    if name == "engramia_recall":
        matches = mem.recall(
            task=arguments["task"],
            limit=int(arguments.get("limit", 5)),
            recency_weight=float(arguments.get("recency_weight", 0.0)),
            recency_half_life_days=float(arguments.get("recency_half_life_days", 30.0)),
        )
        return [
            {
                "similarity": m.similarity,
                "reuse_tier": m.reuse_tier,
                "pattern_key": m.pattern_key,
                "task": m.pattern.task,
                "success_score": m.pattern.success_score,
                "code": m.pattern.design.get("code"),
            }
            for m in matches
        ]

    if name == "engramia_evaluate":
        ev = mem.evaluate(
            task=arguments["task"],
            code=arguments["code"],
            output=arguments.get("output"),
            num_evals=int(arguments.get("num_evals", 3)),
        )
        return {
            "median_score": ev.median_score,
            "variance": ev.variance,
            "high_variance": ev.high_variance,
            "feedback": ev.feedback,
            "adversarial_detected": ev.adversarial_detected,
        }

    if name == "engramia_compose":
        pipeline = mem.compose(task=arguments["task"])
        return {
            "task": pipeline.task,
            "valid": pipeline.valid,
            "contract_errors": pipeline.contract_errors,
            "stages": [
                {
                    "name": s.name,
                    "task": s.task,
                    "reads": s.reads,
                    "writes": s.writes,
                    "reuse_tier": s.reuse_tier,
                }
                for s in pipeline.stages
            ],
        }

    if name == "engramia_feedback":
        feedback = mem.get_feedback(
            task_type=arguments.get("task_type"),
            limit=int(arguments.get("limit", 4)),
        )
        return {"feedback": feedback}

    if name == "engramia_metrics":
        m = mem.metrics
        reuse_rate = m.pipeline_reuse / m.runs if m.runs > 0 else 0.0
        return {
            "runs": m.runs,
            "success_rate": m.success_rate,
            "avg_eval_score": m.avg_eval_score,
            "pattern_count": m.pattern_count,
            "reuse_rate": reuse_rate,
        }

    if name == "engramia_aging":
        pruned = mem.run_aging()
        return {"pruned": pruned}

    if name == "engramia_evolve":
        evolution = mem.evolve_prompt(
            role=arguments["role"],
            current_prompt=arguments["current_prompt"],
            num_issues=int(arguments.get("num_issues", 5)),
        )
        return {
            "improved_prompt": evolution.improved_prompt,
            "changes": evolution.changes,
            "issues_addressed": evolution.issues_addressed,
            "accepted": evolution.accepted,
            "reason": evolution.reason,
        }

    if name == "engramia_analyze_failures":
        clusters = mem.analyze_failures(min_count=int(arguments.get("min_count", 1)))
        return [
            {
                "representative": c.representative,
                "members": c.members,
                "total_count": c.total_count,
                "avg_score": c.avg_score,
            }
            for c in clusters
        ]

    from engramia.mcp.errors import ToolNotFoundError

    raise ToolNotFoundError(f"Unknown tool: {name!r}")


def format_result_text(result: Any) -> str:
    """Serialise dispatch result as the single-string MCP TextContent payload."""
    return json.dumps(result, indent=2, default=str)

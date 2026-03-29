# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Map job operations to Memory method calls.

Each dispatcher function receives the Memory instance and the job params dict,
executes the operation, and returns a JSON-serializable result dict.
"""

import logging
from typing import Any

from engramia import Memory
from engramia.jobs.models import JobOperation

_log = logging.getLogger(__name__)


def _dispatch_evaluate(memory: Memory, params: dict[str, Any]) -> dict[str, Any]:
    result = memory.evaluate(
        task=params["task"],
        code=params["code"],
        output=params.get("output"),
        num_evals=params.get("num_evals", 3),
    )
    return {
        "median_score": result.median_score,
        "variance": result.variance,
        "high_variance": result.high_variance,
        "feedback": result.feedback,
        "adversarial_detected": result.adversarial_detected,
        "scores": [s.model_dump() for s in result.scores],
    }


def _dispatch_compose(memory: Memory, params: dict[str, Any]) -> dict[str, Any]:
    pipeline = memory.compose(task=params["task"])
    return {
        "task": pipeline.task,
        "stages": [
            {
                "name": s.name,
                "task": s.task,
                "reads": s.reads,
                "writes": s.writes,
                "reuse_tier": s.reuse_tier,
                "similarity": s.similarity,
                "code": s.design.get("code") if s.design else None,
            }
            for s in pipeline.stages
        ],
        "valid": pipeline.valid,
        "contract_errors": pipeline.contract_errors,
    }


def _dispatch_evolve(memory: Memory, params: dict[str, Any]) -> dict[str, Any]:
    result = memory.evolve_prompt(
        role=params["role"],
        current_prompt=params["current_prompt"],
        num_issues=params.get("num_issues", 5),
    )
    return {
        "improved_prompt": result.improved_prompt,
        "changes": result.changes,
        "issues_addressed": result.issues_addressed,
        "accepted": result.accepted,
        "reason": result.reason,
    }


def _dispatch_aging(memory: Memory, params: dict[str, Any]) -> dict[str, Any]:
    pruned = memory.run_aging()
    return {"pruned": pruned}


def _dispatch_feedback_decay(memory: Memory, params: dict[str, Any]) -> dict[str, Any]:
    pruned = memory.run_feedback_decay()
    return {"pruned": pruned}


def _dispatch_import(memory: Memory, params: dict[str, Any]) -> dict[str, Any]:
    imported = memory.import_data(params["records"], overwrite=params.get("overwrite", False))
    return {"imported": imported, "total": len(params["records"])}


def _dispatch_export(memory: Memory, params: dict[str, Any]) -> dict[str, Any]:
    records = memory.export()
    return {"records": records, "count": len(records)}


def _dispatch_retention_cleanup(memory: Memory, params: dict[str, Any]) -> dict[str, Any]:
    from engramia.governance.lifecycle import cleanup_expired_patterns

    return cleanup_expired_patterns(memory, params)


def _dispatch_compact_audit_log(memory: Memory, params: dict[str, Any]) -> dict[str, Any]:
    from engramia.governance.lifecycle import compact_audit_log

    return compact_audit_log(memory, params)


def _dispatch_cleanup_old_jobs(memory: Memory, params: dict[str, Any]) -> dict[str, Any]:
    from engramia.governance.lifecycle import cleanup_old_jobs

    return cleanup_old_jobs(memory, params)


DISPATCHERS: dict[str, Any] = {
    JobOperation.EVALUATE: _dispatch_evaluate,
    JobOperation.COMPOSE: _dispatch_compose,
    JobOperation.EVOLVE: _dispatch_evolve,
    JobOperation.AGING: _dispatch_aging,
    JobOperation.FEEDBACK_DECAY: _dispatch_feedback_decay,
    JobOperation.IMPORT: _dispatch_import,
    JobOperation.EXPORT: _dispatch_export,
    # Phase 5.6: Data Governance lifecycle jobs
    JobOperation.RETENTION_CLEANUP: _dispatch_retention_cleanup,
    JobOperation.COMPACT_AUDIT_LOG: _dispatch_compact_audit_log,
    JobOperation.CLEANUP_OLD_JOBS: _dispatch_cleanup_old_jobs,
}


def dispatch_job(memory: Memory, operation: str, params: dict[str, Any]) -> dict[str, Any]:
    """Execute a job operation and return the result dict.

    Args:
        memory: The Memory instance to operate on.
        operation: Operation name (must match a JobOperation value).
        params: Serialized request parameters for the operation.

    Returns:
        JSON-serializable result dict.

    Raises:
        ValueError: If the operation is unknown.
    """
    handler = DISPATCHERS.get(operation)
    if handler is None:
        raise ValueError(f"Unknown job operation: {operation}")
    return handler(memory, params)

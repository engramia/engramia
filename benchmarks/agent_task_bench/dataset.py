# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""HumanEval+ loader + task record.

Wraps ``evalplus.data.get_human_eval_plus`` in a thin dataclass so
the rest of the harness does not depend on evalplus internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaskSpec:
    """One HumanEval+ problem.

    Attributes:
        task_id: ``"HumanEval/N"``.
        prompt: Python source prefix the agent must complete — typically
            an import block, a function signature, and a docstring.
        entry_point: Name of the function the agent must implement.
        canonical_solution: Reference completion (used as the
            "gold standard" example we can teach Engramia about once
            the agent has produced a verified-correct solution).
        test: Test harness source. `evalplus` executes this against the
            agent's completion to decide pass/fail.
        contract: Optional input-validation contract string from the
            EvalPlus dataset. Not used by scoring here.
    """

    task_id: str
    prompt: str
    entry_point: str
    canonical_solution: str
    test: str
    contract: str = ""


def load_humaneval_plus(*, limit: int | None = None) -> list[TaskSpec]:
    """Fetch the HumanEval+ dataset.

    The first call downloads the dataset tarball into the evalplus
    cache (``~/.cache/evalplus/`` on POSIX). Subsequent calls are
    offline.
    """
    from evalplus.data import get_human_eval_plus

    raw: dict[str, dict[str, Any]] = get_human_eval_plus()
    out: list[TaskSpec] = []
    for task_id, rec in raw.items():
        out.append(
            TaskSpec(
                task_id=task_id,
                prompt=rec["prompt"],
                entry_point=rec["entry_point"],
                canonical_solution=rec.get("canonical_solution", ""),
                test=rec["test"],
                contract=rec.get("contract", ""),
            )
        )
    out.sort(key=lambda t: int(t.task_id.split("/", 1)[1]))
    if limit is not None:
        out = out[:limit]
    return out

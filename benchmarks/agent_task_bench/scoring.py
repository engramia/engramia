# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""HumanEval+ scoring — run a completion through the task's test
harness and decide pass/fail.

Each scoring call is a subprocess with a short timeout so an agent-
generated infinite loop cannot stall the whole benchmark. stdout /
stderr / return code are captured for diagnostic purposes.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from benchmarks.agent_task_bench.dataset import TaskSpec

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 30.0


@dataclass
class ScoringResult:
    passed: bool
    detail: str  # short human-readable label: "passed", "assertion", "timeout", "exception: X"


def score_completion(task: TaskSpec, completion: str) -> ScoringResult:
    """Execute the agent's completion followed by the test harness in a
    subprocess with a timeout. Non-zero exit (assertion, exception, or
    timeout kill) is a failure; zero exit is a pass.

    Completion is a COMPLETE self-contained module (imports + def +
    body); the test harness is appended directly. If the agent
    accidentally emits only a function body (no ``def`` line) we fall
    back to ``task.prompt + completion`` to recover.
    """
    if f"def {task.entry_point}" in completion:
        source = completion + "\n\n" + task.test + f"\n\ncheck({task.entry_point})\n"
    else:
        # Defensive fallback: treat completion as a body and splice it
        # onto the prompt's def signature.
        source = (
            task.prompt
            + completion
            + "\n\n"
            + task.test
            + f"\n\ncheck({task.entry_point})\n"
        )
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
        fh.write(source)
        path = Path(fh.name)
    try:
        proc = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ScoringResult(passed=False, detail="timeout")
    finally:
        try:
            path.unlink()
        except OSError:
            pass

    if proc.returncode == 0:
        return ScoringResult(passed=True, detail="passed")
    err = (proc.stderr or "").strip()
    if "AssertionError" in err:
        return ScoringResult(passed=False, detail="assertion")
    # Fall back to first line of stderr for a human-readable label.
    first = err.splitlines()[-1] if err else f"exit code {proc.returncode}"
    return ScoringResult(passed=False, detail=f"exception: {first[:200]}")

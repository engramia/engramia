# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""CrewAI integration for Engramia.

Requires the ``crewai`` extra:
    pip install engramia[crewai]

Usage — Mode 1 (task_callback only, auto-learn):
    from engramia.sdk.crewai import EngramiaCrewCallback

    callback = EngramiaCrewCallback(brain, auto_learn=True)
    crew = Crew(
        agents=[agent],
        tasks=[task],
        task_callback=callback.task_callback,
    )
    crew.kickoff()

Usage — Mode 2 (inject_recall + task_callback, full auto):
    callback = EngramiaCrewCallback(brain, auto_learn=True, auto_recall=True)
    callback.inject_recall(crew.tasks)  # Prepend recalled context to task descriptions
    crew = Crew(agents=[agent], tasks=[task], task_callback=callback.task_callback)
    crew.kickoff()

Usage — Mode 3 (kickoff wrapper, most convenient):
    callback = EngramiaCrewCallback(brain, auto_learn=True, auto_recall=True)
    result = callback.kickoff(crew, inputs={"topic": "AI memory systems"})
"""

import logging
from typing import Any

from engramia.brain import Memory

_log = logging.getLogger(__name__)

_INSTALL_MSG = "CrewAI callback requires crewai. Install with: pip install engramia[crewai]"

# Injected context header appended to task description when auto_recall is enabled.
_RECALL_HEADER = "\n\n---\n**Relevant prior patterns from Engramia memory:**\n"


class EngramiaCrewCallback:
    """CrewAI integration that adds self-learning to agent crews.

    Unlike LangChain, CrewAI does not expose a pre-task hook, so auto-recall
    requires explicit injection before ``crew.kickoff()``. Three usage modes
    are supported — see module docstring.

    Args:
        brain: Memory instance to use for learn/recall.
        auto_learn: If True, call brain.learn() after each task via task_callback.
        auto_recall: If True, inject_recall() / kickoff() will recall patterns
            and prepend them to task descriptions before execution.
        default_score: Eval score used when auto-learning from task outputs.
            Represents "acceptable quality" — adjust based on expected crew output.
        recall_limit: Number of patterns to recall per task.
    """

    def __init__(
        self,
        brain: Memory,
        auto_learn: bool = True,
        auto_recall: bool = True,
        default_score: float = 7.0,
        recall_limit: int = 3,
    ) -> None:
        try:
            import crewai  # noqa: F401
        except ImportError:
            raise ImportError(_INSTALL_MSG) from None
        self._brain = brain
        self._auto_learn = auto_learn
        self._auto_recall = auto_recall
        self._default_score = default_score
        self._recall_limit = recall_limit

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def task_callback(self):
        """Bound method for use as ``Crew(task_callback=callback.task_callback)``.

        Called by CrewAI after each task completes. Auto-learns from the
        task output if ``auto_learn`` is enabled.
        """
        return self._on_task_complete

    def inject_recall(self, tasks: list) -> None:
        """Prepend recalled patterns to task descriptions before kickoff.

        Modifies each task's ``description`` in-place by appending a block of
        relevant patterns recalled from brain memory. Tasks with no similar
        patterns are left unchanged.

        Args:
            tasks: List of CrewAI ``Task`` objects (from ``crew.tasks``).
        """
        if not self._auto_recall:
            return
        for task in tasks:
            task_text = getattr(task, "description", None)
            if not task_text:
                continue
            try:
                matches = self._brain.recall(task=task_text, limit=self._recall_limit)
                if matches:
                    context_block = _RECALL_HEADER + self._format_context(matches)
                    try:
                        task.description = task_text + context_block
                    except Exception:
                        # Pydantic model may be frozen in some CrewAI versions — skip silently
                        _log.debug("EngramiaCrewCallback: could not mutate task.description (frozen model)")
                        continue
                    _log.info(
                        "EngramiaCrewCallback: injected %d recalled patterns into task %r",
                        len(matches),
                        task_text[:80],
                    )
            except Exception as exc:
                _log.warning("EngramiaCrewCallback inject_recall failed for task %r: %s", task_text[:80], exc)

    def kickoff(self, crew: Any, inputs: dict | None = None) -> Any:
        """Convenience wrapper: inject_recall + crew.kickoff().

        Equivalent to calling ``inject_recall(crew.tasks)`` followed by
        ``crew.kickoff(inputs=inputs)``.

        Args:
            crew: CrewAI ``Crew`` instance.
            inputs: Optional inputs dict passed to ``crew.kickoff()``.

        Returns:
            Whatever ``crew.kickoff()`` returns (typically a ``CrewOutput``).
        """
        tasks = getattr(crew, "tasks", [])
        self.inject_recall(tasks)
        if inputs is not None:
            return crew.kickoff(inputs=inputs)
        return crew.kickoff()

    def get_learned_count(self) -> int:
        """Return the total number of patterns stored by this callback instance."""
        return self._brain.metrics.pattern_count

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_task_complete(self, output: Any) -> None:
        """Called by CrewAI after each task. Extracts task + result and learns."""
        if not self._auto_learn:
            return

        task_text = _extract_task(output)
        result_text = _extract_result(output)

        if not task_text or not result_text:
            _log.debug("EngramiaCrewCallback: skipping learn — empty task or result")
            return

        try:
            self._brain.learn(
                task=task_text,
                code=result_text,
                eval_score=self._default_score,
                output=result_text,
            )
            _log.info("EngramiaCrewCallback: learned from task %r", task_text[:80])
        except Exception as exc:
            _log.warning("EngramiaCrewCallback learn failed: %s", exc)

    def _format_context(self, matches: list) -> str:
        """Format recalled matches as a human-readable context block."""
        lines = []
        for i, m in enumerate(matches, 1):
            tier = m.reuse_tier
            task = m.pattern.task[:120]
            snippet = m.pattern.design.get("code", "")[:200]
            lines.append(f"{i}. [{tier.upper()}] {task}")
            if snippet:
                lines.append(f"   ```\n   {snippet}\n   ```")
        return "\n".join(lines)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _extract_task(output: Any) -> str:
    """Best-effort extraction of the task description from a CrewAI TaskOutput."""
    # TaskOutput.description — the original task description
    for attr in ("description", "task", "name"):
        val = getattr(output, attr, None)
        if isinstance(val, str) and val.strip():
            # Strip injected recall context if present
            return val.split(_RECALL_HEADER)[0].strip()
    if isinstance(output, str):
        return output.split(_RECALL_HEADER)[0].strip()
    return ""


def _extract_result(output: Any) -> str:
    """Best-effort extraction of the result text from a CrewAI TaskOutput."""
    # TaskOutput.raw — raw string output from the agent
    for attr in ("raw", "result", "output", "exported_output"):
        val = getattr(output, attr, None)
        if isinstance(val, str) and val.strip():
            return val
    if isinstance(output, str):
        return output
    return ""

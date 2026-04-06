# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""OpenAI Agents SDK integration for Engramia.

Requires the ``openai-agents`` extra:
    pip install engramia[openai-agents]

Usage — RunHooks (recommended):
    from engramia.sdk.openai_agents import EngramiaRunHooks

    hooks = EngramiaRunHooks(memory)
    result = await Runner.run(agent, "Build a CSV parser", hooks=hooks)

Usage — Dynamic instructions (inject recalled context into system prompt):
    from engramia.sdk.openai_agents import engramia_instructions

    agent = Agent(
        name="coder",
        instructions=engramia_instructions(memory, base="You are a senior developer."),
    )
    result = await Runner.run(agent, "Build a CSV parser")

Usage — RunHooks + dynamic instructions (full automation):
    agent = Agent(
        name="coder",
        instructions=engramia_instructions(memory, base="You are a senior developer."),
    )
    hooks = EngramiaRunHooks(memory)
    result = await Runner.run(agent, "Build a CSV parser", hooks=hooks)
"""

import logging
from typing import Any

from engramia.memory import Memory

_log = logging.getLogger(__name__)

_INSTALL_MSG = (
    "OpenAI Agents integration requires openai-agents. "
    "Install with: pip install engramia[openai-agents]"
)


def _check_import() -> None:
    try:
        import agents  # noqa: F401
    except ImportError:
        raise ImportError(_INSTALL_MSG) from None


class EngramiaRunHooks:
    """OpenAI Agents SDK ``RunHooks`` that integrates Engramia memory.

    Automatically learns from completed agent runs. Pair with
    :func:`engramia_instructions` for automatic recall injection.

    Args:
        memory: Memory instance for learn/recall.
        auto_learn: If True, call mem.learn() when an agent completes.
        min_score: Minimum eval score used when storing a pattern.
        recall_limit: Number of patterns to recall (used by
            :func:`engramia_instructions`, not directly by hooks).
    """

    def __init__(
        self,
        memory: Memory,
        auto_learn: bool = True,
        min_score: float = 7.0,
        recall_limit: int = 3,
    ) -> None:
        _check_import()
        self._memory = memory
        self._auto_learn = auto_learn
        self._min_score = min_score
        self._recall_limit = recall_limit
        self._agent_tasks: dict[str, str] = {}

    async def on_agent_start(
        self, context: Any, agent: Any,
    ) -> None:
        """Capture the agent's current task for later learning."""
        task = _extract_task_from_context(context)
        agent_id = getattr(agent, "name", None) or str(id(agent))
        if task:
            self._agent_tasks[agent_id] = task
            _log.debug("EngramiaRunHooks: agent %r started with task %r", agent_id, task[:80])

    async def on_agent_end(
        self, context: Any, agent: Any, output: Any,
    ) -> None:
        """Learn from the completed agent run."""
        if not self._auto_learn:
            return

        agent_id = getattr(agent, "name", None) or str(id(agent))
        task = self._agent_tasks.pop(agent_id, "")
        if not task:
            _log.debug("EngramiaRunHooks: no task captured for agent %r, skipping learn", agent_id)
            return

        output_text = str(output) if output is not None else ""
        if not output_text:
            return

        try:
            self._memory.learn(
                task=task,
                code=output_text,
                eval_score=self._min_score,
                output=output_text,
            )
            _log.info("EngramiaRunHooks: learned from agent %r for task %r", agent_id, task[:80])
        except Exception as exc:
            _log.warning("EngramiaRunHooks learn failed: %s", exc)

    async def on_tool_start(
        self, context: Any, agent: Any, tool: Any,
    ) -> None:
        """No-op — required by RunHooks interface."""

    async def on_tool_end(
        self, context: Any, agent: Any, tool: Any, result: str,
    ) -> None:
        """No-op — required by RunHooks interface."""

    async def on_handoff(
        self, context: Any, from_agent: Any, to_agent: Any,
    ) -> None:
        """No-op — required by RunHooks interface."""

    async def on_llm_start(
        self, context: Any, agent: Any, system_prompt: str | None, input_items: Any,
    ) -> None:
        """Capture task from input items if not already captured."""
        agent_id = getattr(agent, "name", None) or str(id(agent))
        if agent_id not in self._agent_tasks and input_items:
            task = _extract_task_from_input_items(input_items)
            if task:
                self._agent_tasks[agent_id] = task

    async def on_llm_end(
        self, context: Any, agent: Any, response: Any,
    ) -> None:
        """No-op — required by RunHooks interface."""


def engramia_instructions(
    memory: Memory,
    base: str = "",
    recall_limit: int = 3,
) -> Any:
    """Create a dynamic instructions function that injects recalled patterns.

    Returns an async callable compatible with ``Agent(instructions=...)``.
    On each agent invocation, relevant patterns are recalled from Engramia
    and appended to the base instructions.

    Args:
        memory: Memory instance for recall.
        base: Base system prompt / instructions.
        recall_limit: Number of patterns to recall.

    Returns:
        Async callable ``(context, agent) -> str`` suitable for
        ``Agent(instructions=...)``.

    Example::

        agent = Agent(
            name="coder",
            instructions=engramia_instructions(mem, base="You are a coder."),
        )
    """
    _check_import()

    async def _dynamic_instructions(context: Any, agent: Any) -> str:
        task = _extract_task_from_context(context)
        if not task:
            return base

        try:
            matches = memory.recall(task=task, limit=recall_limit)
            if not matches:
                return base
        except Exception as exc:
            _log.warning("engramia_instructions recall failed: %s", exc)
            return base

        context_block = _format_recalled_context(matches)
        _log.info(
            "engramia_instructions: injected %d patterns for task %r",
            len(matches),
            task[:80],
        )
        return f"{base}\n\n{context_block}" if base else context_block

    return _dynamic_instructions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RECALL_HEADER = "## Relevant patterns from previous runs\n"


def _format_recalled_context(matches: list) -> str:
    """Format recalled matches as a context block for the system prompt."""
    lines = [_RECALL_HEADER]
    for i, m in enumerate(matches, 1):
        tier = m.reuse_tier
        task = m.pattern.task[:120]
        snippet = m.pattern.design.get("code", "")[:300]
        lines.append(f"{i}. [{tier.upper()}] {task}")
        if snippet:
            lines.append(f"   ```\n   {snippet}\n   ```")
    return "\n".join(lines)


def _extract_task_from_context(context: Any) -> str:
    """Best-effort extraction of the user task from RunContextWrapper."""
    # context is RunContextWrapper — context.context is the user-provided TContext
    user_ctx = getattr(context, "context", None)
    if isinstance(user_ctx, str):
        return user_ctx
    if isinstance(user_ctx, dict):
        for key in ("task", "input", "query", "prompt", "question"):
            if key in user_ctx and isinstance(user_ctx[key], str):
                return user_ctx[key]
    # Try to get from the input directly
    input_val = getattr(context, "input", None)
    if isinstance(input_val, str):
        return input_val
    return ""


def _extract_task_from_input_items(input_items: Any) -> str:
    """Extract user message text from OpenAI Agents input_items list."""
    if not isinstance(input_items, list):
        return ""
    for item in input_items:
        # input_items can be dicts or objects
        if isinstance(item, dict):
            role = item.get("role", "")
            content = item.get("content", "")
            if role == "user" and isinstance(content, str):
                return content
        else:
            role = getattr(item, "role", "")
            content = getattr(item, "content", "")
            if role == "user" and isinstance(content, str):
                return content
    return ""

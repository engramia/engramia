# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Pydantic AI integration for Engramia.

Requires the ``pydantic-ai`` extra:
    pip install engramia[pydantic-ai]

Usage — Capability (recommended):
    from engramia.sdk.pydantic_ai import EngramiaCapability

    agent = Agent('openai:gpt-4o', capabilities=[EngramiaCapability(memory)])
    result = agent.run_sync("Build a CSV parser")
    # Automatically recalls patterns before run and learns after.

Usage — system_prompt decorator (manual):
    from engramia.sdk.pydantic_ai import engramia_system_prompt

    agent = Agent('openai:gpt-4o')

    @agent.system_prompt
    def inject_memory(ctx):
        return engramia_system_prompt(memory, ctx)
"""

import logging
from typing import Any

from engramia.memory import Memory as EngramiaMemory

_log = logging.getLogger(__name__)

_INSTALL_MSG = "Pydantic AI integration requires pydantic-ai. Install with: pip install engramia[pydantic-ai]"


def _check_import() -> None:
    try:
        import pydantic_ai  # noqa: F401
    except ImportError:
        raise ImportError(_INSTALL_MSG) from None


class EngramiaCapability:
    """Pydantic AI capability that integrates Engramia memory.

    Recalls relevant patterns before each agent run and injects them
    as additional system context. After a successful run, learns from
    the result.

    Register as::

        agent = Agent('openai:gpt-4o', capabilities=[EngramiaCapability(memory)])

    Args:
        memory: Engramia Memory instance.
        auto_learn: If True, learn from successful runs.
        auto_recall: If True, recall patterns before each run.
        min_score: Eval score assigned when learning from runs.
        recall_limit: Number of patterns to recall.
    """

    def __init__(
        self,
        memory: EngramiaMemory,
        auto_learn: bool = True,
        auto_recall: bool = True,
        min_score: float = 7.0,
        recall_limit: int = 3,
    ) -> None:
        _check_import()
        self._memory = memory
        self._auto_learn = auto_learn
        self._auto_recall = auto_recall
        self._min_score = min_score
        self._recall_limit = recall_limit
        self._current_task: str = ""
        self._recalled_context: str = ""

    async def before_run(self, ctx: Any) -> None:
        """Recall patterns and store context for injection."""
        if not self._auto_recall:
            return

        task = _extract_task_from_ctx(ctx)
        self._current_task = task
        if not task:
            return

        try:
            matches = self._memory.recall(task=task, limit=self._recall_limit)
            if matches:
                self._recalled_context = _format_recalled_context(matches)
                _log.info(
                    "EngramiaCapability: recalled %d patterns for task %r",
                    len(matches),
                    task[:80],
                )
        except Exception as exc:
            _log.warning("EngramiaCapability recall failed: %s", exc)

    async def before_model_request(self, ctx: Any, request_context: Any) -> Any:
        """Inject recalled context into model messages."""
        if not self._recalled_context:
            return request_context

        try:
            # request_context has a .messages list we can prepend to
            messages = getattr(request_context, "messages", None)
            if messages is not None and isinstance(messages, list):
                from pydantic_ai.messages import ModelRequest, SystemPromptPart

                system_part = SystemPromptPart(content=self._recalled_context)
                messages.insert(0, ModelRequest(parts=[system_part]))
        except Exception as exc:
            _log.debug("EngramiaCapability: could not inject context: %s", exc)

        return request_context

    async def after_run(self, ctx: Any, *, result: Any) -> Any:
        """Learn from the completed run."""
        if not self._auto_learn or not self._current_task:
            return result

        output_text = ""
        try:
            output_obj = getattr(result, "output", None)
            if output_obj is not None:
                output_text = str(output_obj)
        except (AttributeError, TypeError) as exc:
            _log.debug("Failed to extract output: %s", exc)

        if not output_text:
            return result

        try:
            self._memory.learn(
                task=self._current_task,
                code=output_text,
                eval_score=self._min_score,
                output=output_text,
            )
            _log.info(
                "EngramiaCapability: learned from run for task %r",
                self._current_task[:80],
            )
        except Exception as exc:
            _log.warning("EngramiaCapability learn failed: %s", exc)
        finally:
            self._current_task = ""
            self._recalled_context = ""

        return result

    async def for_run(self, ctx: Any) -> "EngramiaCapability":
        """Return a fresh per-run instance for thread safety."""
        return EngramiaCapability(
            memory=self._memory,
            auto_learn=self._auto_learn,
            auto_recall=self._auto_recall,
            min_score=self._min_score,
            recall_limit=self._recall_limit,
        )


def engramia_system_prompt(
    memory: EngramiaMemory,
    ctx: Any,
    base: str = "",
    recall_limit: int = 3,
) -> str:
    """Build a system prompt with recalled patterns for use with @agent.system_prompt.

    Args:
        memory: Engramia Memory instance.
        ctx: Pydantic AI RunContext (used to extract task from deps).
        base: Base system prompt to extend.
        recall_limit: Number of patterns to recall.

    Returns:
        System prompt string with recalled context appended.

    Example::

        @agent.system_prompt
        def inject(ctx):
            return engramia_system_prompt(memory, ctx, base="You are a coder.")
    """
    task = _extract_task_from_ctx(ctx)
    if not task:
        return base

    try:
        matches = memory.recall(task=task, limit=recall_limit)
        if not matches:
            return base
    except Exception as exc:
        _log.warning("engramia_system_prompt recall failed: %s", exc)
        return base

    context_block = _format_recalled_context(matches)
    return f"{base}\n\n{context_block}" if base else context_block


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RECALL_HEADER = "## Relevant patterns from previous runs\n"


def _format_recalled_context(matches: list) -> str:
    """Format recalled matches as a context block."""
    lines = [_RECALL_HEADER]
    for i, m in enumerate(matches, 1):
        tier = m.reuse_tier
        task = m.pattern.task[:120]
        snippet = m.pattern.design.get("code", "")[:300]
        lines.append(f"{i}. [{tier.upper()}] {task}")
        if snippet:
            lines.append(f"   ```\n   {snippet}\n   ```")
    return "\n".join(lines)


def _extract_task_from_ctx(ctx: Any) -> str:
    """Best-effort task extraction from Pydantic AI RunContext."""
    # Try ctx.deps first (user-provided dependency object)
    deps = getattr(ctx, "deps", None)
    if isinstance(deps, str):
        return deps
    if isinstance(deps, dict):
        for key in ("task", "input", "query", "prompt", "question"):
            if key in deps and isinstance(deps[key], str):
                return deps[key]

    # Try ctx.prompt (the user's input prompt)
    prompt = getattr(ctx, "prompt", None)
    if isinstance(prompt, str):
        return prompt

    # Try ctx.messages for the latest user message
    messages = getattr(ctx, "messages", None)
    if isinstance(messages, list):
        for msg in reversed(messages):
            content = getattr(msg, "content", None)
            if isinstance(content, str) and len(content) > 3:
                return content

    return ""

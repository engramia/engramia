# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""AutoGen (v0.4+) integration for Engramia.

Requires the ``autogen`` extra:
    pip install engramia[autogen]

Usage — Memory interface (recommended):
    from engramia.sdk.autogen import EngramiaMemory

    agent = AssistantAgent(
        name="coder",
        model_client=model_client,
        memory=[EngramiaMemory(memory)],
    )
    result = await agent.run(task="Build a CSV parser")
    # Engramia patterns are automatically recalled before each LLM call.

Usage — post-run learning helper:
    from engramia.sdk.autogen import learn_from_result

    result = await agent.run(task="Build a CSV parser")
    learn_from_result(memory, task="Build a CSV parser", result=result)
"""

import logging
from typing import Any

from engramia.memory import Memory as _EngramiaMemory

_log = logging.getLogger(__name__)

_INSTALL_MSG = (
    "AutoGen integration requires autogen-agentchat. "
    "Install with: pip install engramia[autogen]"
)


def _check_import() -> None:
    try:
        import autogen_core  # noqa: F401
    except ImportError:
        raise ImportError(_INSTALL_MSG) from None


class EngramiaMemory:
    """AutoGen Memory implementation backed by Engramia.

    Implements the ``autogen_core.memory.Memory`` interface. When attached
    to an ``AssistantAgent``, patterns are automatically recalled before
    each LLM inference and injected as a system message.

    Args:
        memory: Engramia Memory instance.
        recall_limit: Maximum number of patterns to recall per inference.
        name: Display name for this memory source.

    Example::

        from engramia.sdk.autogen import EngramiaMemory

        agent = AssistantAgent(
            name="coder",
            model_client=model_client,
            memory=[EngramiaMemory(memory, recall_limit=5)],
        )
    """

    component_type = "memory"

    def __init__(
        self,
        memory: _EngramiaMemory,
        recall_limit: int = 3,
        name: str = "engramia",
    ) -> None:
        _check_import()
        self._memory = memory
        self._recall_limit = recall_limit
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def update_context(self, model_context: Any) -> Any:
        """Recall patterns and inject them as a system message.

        Called by AssistantAgent before each LLM inference. Extracts
        the current task from recent messages, recalls relevant patterns
        from Engramia, and adds them as a SystemMessage.

        Args:
            model_context: AutoGen ChatCompletionContext.

        Returns:
            UpdateContextResult with recalled memory contents.
        """
        from autogen_core.memory import MemoryContent, MemoryQueryResult, UpdateContextResult
        from autogen_core.models import SystemMessage

        task = await self._extract_task(model_context)
        if not task:
            return UpdateContextResult(memories=MemoryQueryResult(results=[]))

        try:
            matches = self._memory.recall(task=task, limit=self._recall_limit)
        except Exception as exc:
            _log.warning("EngramiaMemory recall failed: %s", exc)
            return UpdateContextResult(memories=MemoryQueryResult(results=[]))

        if not matches:
            return UpdateContextResult(memories=MemoryQueryResult(results=[]))

        context_block = _format_recalled_context(matches)
        await model_context.add_message(SystemMessage(content=context_block))

        _log.info(
            "EngramiaMemory: injected %d patterns for task %r",
            len(matches),
            task[:80],
        )

        results = [
            MemoryContent(content=m.pattern.task, mime_type="text/plain")
            for m in matches
        ]
        return UpdateContextResult(memories=MemoryQueryResult(results=results))

    async def query(self, query: Any, cancellation_token: Any = None, **kwargs: Any) -> Any:
        """Query Engramia memory for relevant patterns.

        Args:
            query: Search query (str or MemoryContent).

        Returns:
            MemoryQueryResult with matching patterns.
        """
        from autogen_core.memory import MemoryContent, MemoryQueryResult

        query_str = str(query) if not isinstance(query, str) else query
        try:
            matches = self._memory.recall(task=query_str, limit=self._recall_limit)
        except Exception as exc:
            _log.warning("EngramiaMemory query failed: %s", exc)
            return MemoryQueryResult(results=[])

        results = [
            MemoryContent(content=m.pattern.task, mime_type="text/plain")
            for m in matches
        ]
        return MemoryQueryResult(results=results)

    async def add(self, content: Any, cancellation_token: Any = None, **kwargs: Any) -> None:
        """Store content as a pattern in Engramia memory.

        Args:
            content: MemoryContent to store. The content field is used
                as both task description and code.
        """
        raw = getattr(content, "content", None)
        text = raw if isinstance(raw, str) else str(content) if raw is not None else ""
        if not text:
            return

        try:
            self._memory.learn(
                task=text,
                code=text,
                eval_score=7.0,
            )
            _log.info("EngramiaMemory: stored content (len=%d)", len(text))
        except Exception as exc:
            _log.warning("EngramiaMemory add failed: %s", exc)

    async def clear(self) -> None:
        """No-op — Engramia patterns are not cleared via this interface."""
        _log.debug("EngramiaMemory.clear() called — no-op")

    async def close(self) -> None:
        """No-op — Engramia Memory lifecycle is managed externally."""
        _log.debug("EngramiaMemory.close() called — no-op")

    async def _extract_task(self, model_context: Any) -> str:
        """Extract the latest user message from model context."""
        try:
            messages = await model_context.get_messages()
        except Exception:
            return ""

        for msg in reversed(messages):
            # UserMessage / TextMessage — look for content attribute
            content = getattr(msg, "content", None)
            if isinstance(content, str) and len(content) > 3:
                return content
        return ""


def learn_from_result(
    memory: _EngramiaMemory,
    task: str,
    result: Any,
    eval_score: float = 7.0,
) -> None:
    """Learn from an AutoGen TaskResult after a run completes.

    Since AutoGen's Memory interface has no post-run hook, call this
    explicitly after ``agent.run()`` or ``team.run()`` completes.

    Args:
        memory: Engramia Memory instance.
        task: The task description that was executed.
        result: AutoGen TaskResult from agent.run() or team.run().
        eval_score: Eval score to assign to the learned pattern.

    Example::

        result = await agent.run(task="Build a CSV parser")
        learn_from_result(memory, task="Build a CSV parser", result=result)
    """
    output_text = _extract_output(result)
    if not output_text:
        _log.debug("learn_from_result: no output to learn from")
        return

    try:
        memory.learn(
            task=task,
            code=output_text,
            eval_score=eval_score,
            output=output_text,
        )
        _log.info("learn_from_result: learned from task %r", task[:80])
    except Exception as exc:
        _log.warning("learn_from_result failed: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RECALL_HEADER = "## Relevant patterns from previous runs\n"


def _format_recalled_context(matches: list) -> str:
    """Format recalled matches as a context block for the system message."""
    lines = [_RECALL_HEADER]
    for i, m in enumerate(matches, 1):
        tier = m.reuse_tier
        task = m.pattern.task[:120]
        snippet = m.pattern.design.get("code", "")[:300]
        lines.append(f"{i}. [{tier.upper()}] {task}")
        if snippet:
            lines.append(f"   ```\n   {snippet}\n   ```")
    return "\n".join(lines)


def _extract_output(result: Any) -> str:
    """Best-effort extraction of output text from AutoGen TaskResult."""
    # TaskResult.messages[-1].content is the final agent response
    messages = getattr(result, "messages", None)
    if messages and len(messages) > 0:
        last = messages[-1]
        content = getattr(last, "content", None)
        if isinstance(content, str):
            return content
    return ""

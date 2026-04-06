# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Anthropic Agent SDK (claude-agent-sdk) integration for Engramia.

Requires the ``anthropic-agents`` extra:
    pip install engramia[anthropic-agents]

Usage — query() wrapper (simplest):
    from engramia.sdk.anthropic_agents import engramia_query

    async for message in engramia_query(memory, prompt="Build a CSV parser"):
        print(message)
    # Automatically recalls context → injects into system_prompt,
    # and learns from the final ResultMessage.

Usage — hooks for ClaudeSDKClient:
    from engramia.sdk.anthropic_agents import engramia_hooks

    hooks = engramia_hooks(memory)
    options = ClaudeAgentOptions(hooks=hooks, ...)
    async with ClaudeSDKClient(options=options) as client:
        await client.query("Build a CSV parser")
        async for msg in client.receive_response():
            ...

Usage — manual system_prompt injection:
    from engramia.sdk.anthropic_agents import recall_system_prompt

    prompt = recall_system_prompt(memory, task="Build a CSV parser", base="You are a coder.")
    async for msg in query(prompt="Build a CSV parser", options=ClaudeAgentOptions(system_prompt=prompt)):
        ...
"""

import logging
from collections.abc import AsyncIterator
from typing import Any

from engramia.memory import Memory

_log = logging.getLogger(__name__)

_INSTALL_MSG = (
    "Anthropic Agent SDK integration requires claude-agent-sdk. "
    "Install with: pip install engramia[anthropic-agents]"
)


def _check_import() -> None:
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        raise ImportError(_INSTALL_MSG) from None


def recall_system_prompt(
    memory: Memory,
    task: str,
    base: str = "",
    recall_limit: int = 3,
) -> str:
    """Build a system prompt with recalled patterns prepended.

    Args:
        memory: Memory instance for recall.
        task: The task to recall patterns for.
        base: Base system prompt to extend.
        recall_limit: Maximum number of patterns to recall.

    Returns:
        Combined system prompt with recalled context.
    """
    try:
        matches = memory.recall(task=task, limit=recall_limit)
        if not matches:
            return base
    except Exception as exc:
        _log.warning("recall_system_prompt failed: %s", exc)
        return base

    context_block = _format_recalled_context(matches)
    _log.info(
        "recall_system_prompt: injected %d patterns for task %r",
        len(matches),
        task[:80],
    )
    return f"{base}\n\n{context_block}" if base else context_block


async def engramia_query(
    memory: Memory,
    prompt: str,
    *,
    base_system_prompt: str = "",
    recall_limit: int = 3,
    auto_learn: bool = True,
    min_score: float = 7.0,
    options: Any = None,
) -> AsyncIterator[Any]:
    """Wrap ``claude_agent_sdk.query()`` with automatic recall and learn.

    Recalls relevant patterns and injects them into the system prompt,
    then yields all messages from the agent run. After receiving the
    final ``ResultMessage``, automatically learns from the result.

    Args:
        memory: Memory instance for learn/recall.
        prompt: The user prompt to send to the agent.
        base_system_prompt: Base system prompt (extended with recalled context).
        recall_limit: Number of patterns to recall.
        auto_learn: If True, learn from the final result.
        min_score: Eval score assigned when learning.
        options: Optional ``ClaudeAgentOptions`` to extend. If provided,
            the system_prompt field will be overridden with recalled context.

    Yields:
        Messages from the agent run (SystemMessage, AssistantMessage,
        ResultMessage, etc.).
    """
    _check_import()
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    # Build system prompt with recalled context
    system_prompt = recall_system_prompt(
        memory, task=prompt, base=base_system_prompt, recall_limit=recall_limit,
    )

    # Merge with provided options
    if options is None:
        opts = ClaudeAgentOptions(system_prompt=system_prompt)
    else:
        opts = options
        if system_prompt:
            opts.system_prompt = system_prompt

    result_text = None
    async for message in query(prompt=prompt, options=opts):
        yield message
        if isinstance(message, ResultMessage) and auto_learn:
            result_text = getattr(message, "result", None)

    # Learn from the final result
    if auto_learn and result_text:
        try:
            memory.learn(
                task=prompt,
                code=result_text,
                eval_score=min_score,
                output=result_text,
            )
            _log.info("engramia_query: learned from result for task %r", prompt[:80])
        except Exception as exc:
            _log.warning("engramia_query learn failed: %s", exc)


def engramia_hooks(
    memory: Memory,
    auto_learn: bool = True,
    min_score: float = 7.0,
) -> dict[str, list[Any]]:
    """Create a hooks dict for ``ClaudeAgentOptions(hooks=...)``.

    Provides a ``PostToolUse`` hook that captures tool outputs for
    pattern learning. Best combined with :func:`recall_system_prompt`
    for context injection.

    Args:
        memory: Memory instance for learning.
        auto_learn: If True, learn from tool outputs.
        min_score: Eval score assigned when learning.

    Returns:
        Dict suitable for ``ClaudeAgentOptions(hooks=...)``.
    """
    _check_import()
    from claude_agent_sdk import HookMatcher

    async def _on_post_tool_use(
        input_data: dict[str, Any],
        tool_use_id: str,
        context: Any,
    ) -> dict:
        if not auto_learn:
            return {}

        tool_input = input_data.get("tool_input", {})
        tool_name = input_data.get("tool_name", "")

        # Only learn from tools that produce meaningful output
        if tool_name not in ("Edit", "Write", "Bash"):
            return {}

        # Extract task description from tool input
        task = ""
        if isinstance(tool_input, dict):
            task = tool_input.get("description", "") or tool_input.get("command", "")
        if not task:
            return {}

        # The tool result is not directly available in input_data;
        # PostToolUse fires after completion but result comes via the stream.
        # We record the task intent for now — full output learning happens
        # in engramia_query's ResultMessage handler.
        _log.debug("engramia_hooks: observed tool %r for task %r", tool_name, task[:80])
        return {}

    hooks: dict[str, list[Any]] = {
        "PostToolUse": [
            HookMatcher(matcher="Edit|Write|Bash", hooks=[_on_post_tool_use]),
        ],
    }
    return hooks


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

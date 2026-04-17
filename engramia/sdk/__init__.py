# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Engramia SDK — framework integrations and REST client.

All public symbols are accessible from this package. Framework-specific
classes use lazy imports so that optional dependencies (langchain, crewai,
pydantic-ai, autogen, openai-agents, anthropic-agents) are only imported
when the symbol is actually used — not at package import time.

Example::

    from engramia.sdk import EngramiaBridge          # universal bridge
    from engramia.sdk import EngramiaWebhook          # REST client
    from engramia.sdk import EngramiaRunHooks          # OpenAI Agents SDK
    from engramia.sdk import EngramiaCallback          # LangChain
    from engramia.sdk import EngramiaCrewCallback      # CrewAI
    from engramia.sdk import EngramiaCapability        # Pydantic AI
    from engramia.sdk import EngramiaMemory            # AutoGen
    from engramia.sdk import engramia_query            # Anthropic Agent SDK
"""

from __future__ import annotations

__all__ = [
    "EngramiaBridge",
    "EngramiaCallback",
    "EngramiaCapability",
    "EngramiaCrewCallback",
    "EngramiaMemory",
    "EngramiaRunHooks",
    "EngramiaWebhook",
    "EngramiaWebhookError",
    "engramia_hooks",
    "engramia_instructions",
    "engramia_query",
    "engramia_system_prompt",
    "learn_from_result",
    "recall_system_prompt",
]

# Lazy import table: symbol name → (module path, attribute name)
_LAZY: dict[str, tuple[str, str]] = {
    "EngramiaBridge": ("engramia.sdk.bridge", "EngramiaBridge"),
    "EngramiaWebhook": ("engramia.sdk.webhook", "EngramiaWebhook"),
    "EngramiaWebhookError": ("engramia.sdk.webhook", "EngramiaWebhookError"),
    "engramia_query": ("engramia.sdk.anthropic_agents", "engramia_query"),
    "engramia_hooks": ("engramia.sdk.anthropic_agents", "engramia_hooks"),
    "recall_system_prompt": ("engramia.sdk.anthropic_agents", "recall_system_prompt"),
    "EngramiaRunHooks": ("engramia.sdk.openai_agents", "EngramiaRunHooks"),
    "engramia_instructions": ("engramia.sdk.openai_agents", "engramia_instructions"),
    "EngramiaCallback": ("engramia.sdk.langchain", "EngramiaCallback"),
    "EngramiaCrewCallback": ("engramia.sdk.crewai", "EngramiaCrewCallback"),
    "EngramiaCapability": ("engramia.sdk.pydantic_ai", "EngramiaCapability"),
    "engramia_system_prompt": ("engramia.sdk.pydantic_ai", "engramia_system_prompt"),
    "EngramiaMemory": ("engramia.sdk.autogen", "EngramiaMemory"),
    "learn_from_result": ("engramia.sdk.autogen", "learn_from_result"),
}


def __getattr__(name: str):
    """Lazily import SDK symbols to avoid pulling in optional dependencies."""
    if name in _LAZY:
        import importlib

        module_path, attr = _LAZY[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

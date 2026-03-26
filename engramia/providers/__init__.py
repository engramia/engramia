# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Provider implementations for Engramia.

Base classes (no extra dependencies):

    from engramia.providers import LLMProvider, EmbeddingProvider, StorageBackend
    from engramia.providers import JSONStorage

OpenAI providers (requires: pip install agent-brain[openai]):

    from engramia.providers import OpenAIProvider, OpenAIEmbeddings

Anthropic provider (requires: pip install agent-brain[anthropic]):

    from engramia.providers import AnthropicProvider

Local embeddings (requires: pip install agent-brain[local]):

    from engramia.providers import LocalEmbeddings
"""

from engramia.providers.base import EmbeddingProvider, LLMProvider, StorageBackend
from engramia.providers.json_storage import JSONStorage
from engramia.providers.openai import OpenAIEmbeddings, OpenAIProvider

__all__ = [
    "EmbeddingProvider",
    "JSONStorage",
    "LLMProvider",
    "OpenAIEmbeddings",
    "OpenAIProvider",
    "StorageBackend",
    # Lazy imports — available only when the corresponding extra is installed:
    # "AnthropicProvider",  # agent-brain[anthropic]
    # "LocalEmbeddings",    # agent-brain[local]
]


def __getattr__(name: str):
    """Lazy import for optional providers."""
    if name == "AnthropicProvider":
        from engramia.providers.anthropic import AnthropicProvider

        return AnthropicProvider
    if name == "LocalEmbeddings":
        from engramia.providers.local_embeddings import LocalEmbeddings

        return LocalEmbeddings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

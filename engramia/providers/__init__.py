# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Provider implementations for Engramia.

Base classes (no extra dependencies):

    from engramia.providers import LLMProvider, EmbeddingProvider, StorageBackend
    from engramia.providers import JSONStorage

OpenAI providers (requires: pip install engramia[openai]):

    from engramia.providers import OpenAIProvider, OpenAIEmbeddings

Anthropic provider (requires: pip install engramia[anthropic]):

    from engramia.providers import AnthropicProvider

Gemini providers (requires: pip install engramia[gemini]):

    from engramia.providers import GeminiProvider, GeminiEmbeddings

Ollama providers (no extra; reuses the openai SDK against a local Ollama
endpoint via base_url):

    from engramia.providers import OllamaProvider, OllamaEmbeddings

Demo provider (no extra; used by the BYOK fallback path when a tenant
has no LLM credential configured):

    from engramia.providers import DemoProvider, DemoMeter

Local embeddings (requires: pip install engramia[local]):

    from engramia.providers import LocalEmbeddings
"""

from engramia.providers.base import EmbeddingProvider, LLMProvider, StorageBackend
from engramia.providers.demo import DemoMeter, DemoProvider
from engramia.providers.json_storage import JSONStorage
from engramia.providers.openai import OpenAIEmbeddings, OpenAIProvider

__all__ = [
    "DemoMeter",
    "DemoProvider",
    "EmbeddingProvider",
    "JSONStorage",
    "LLMProvider",
    "OpenAIEmbeddings",
    "OpenAIProvider",
    "StorageBackend",
    # Lazy imports — available only when the corresponding extra is installed:
    # "AnthropicProvider",  # engramia[anthropic]
    # "GeminiProvider", "GeminiEmbeddings",  # engramia[gemini]
    # "OllamaProvider", "OllamaEmbeddings",  # depends on engramia[openai]
    # "LocalEmbeddings",  # engramia[local]
]


def __getattr__(name: str):
    """Lazy import for optional providers."""
    if name == "AnthropicProvider":
        from engramia.providers.anthropic import AnthropicProvider

        return AnthropicProvider
    if name in ("GeminiProvider", "GeminiEmbeddings"):
        from engramia.providers import gemini

        return getattr(gemini, name)
    if name in ("OllamaProvider", "OllamaEmbeddings"):
        from engramia.providers import ollama

        return getattr(ollama, name)
    if name == "LocalEmbeddings":
        from engramia.providers.local_embeddings import LocalEmbeddings

        return LocalEmbeddings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

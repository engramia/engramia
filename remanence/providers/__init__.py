"""Provider implementations for Remanence.

Base classes (no extra dependencies):

    from remanence.providers import LLMProvider, EmbeddingProvider, StorageBackend
    from remanence.providers import JSONStorage

OpenAI providers (requires: pip install agent-brain[openai]):

    from remanence.providers import OpenAIProvider, OpenAIEmbeddings

Anthropic provider (requires: pip install agent-brain[anthropic]):

    from remanence.providers import AnthropicProvider

Local embeddings (requires: pip install agent-brain[local]):

    from remanence.providers import LocalEmbeddings
"""

from remanence.providers.base import EmbeddingProvider, LLMProvider, StorageBackend
from remanence.providers.json_storage import JSONStorage
from remanence.providers.openai import OpenAIEmbeddings, OpenAIProvider

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
        from remanence.providers.anthropic import AnthropicProvider

        return AnthropicProvider
    if name == "LocalEmbeddings":
        from remanence.providers.local_embeddings import LocalEmbeddings

        return LocalEmbeddings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

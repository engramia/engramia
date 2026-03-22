"""Provider implementations for Agent Brain.

Base classes (no extra dependencies):

    from agent_brain.providers import LLMProvider, EmbeddingProvider, StorageBackend
    from agent_brain.providers import JSONStorage

OpenAI providers (requires: pip install agent-brain[openai]):

    from agent_brain.providers import OpenAIProvider, OpenAIEmbeddings

Anthropic provider (requires: pip install agent-brain[anthropic]):

    from agent_brain.providers import AnthropicProvider

Local embeddings (requires: pip install agent-brain[local]):

    from agent_brain.providers import LocalEmbeddings
"""

from agent_brain.providers.base import EmbeddingProvider, LLMProvider, StorageBackend
from agent_brain.providers.json_storage import JSONStorage
from agent_brain.providers.openai import OpenAIEmbeddings, OpenAIProvider

__all__ = [
    "LLMProvider",
    "EmbeddingProvider",
    "StorageBackend",
    "JSONStorage",
    "OpenAIProvider",
    "OpenAIEmbeddings",
    # Lazy imports — available only when the corresponding extra is installed:
    # "AnthropicProvider",  # agent-brain[anthropic]
    # "LocalEmbeddings",    # agent-brain[local]
]


def __getattr__(name: str):
    """Lazy import for optional providers."""
    if name == "AnthropicProvider":
        from agent_brain.providers.anthropic import AnthropicProvider
        return AnthropicProvider
    if name == "LocalEmbeddings":
        from agent_brain.providers.local_embeddings import LocalEmbeddings
        return LocalEmbeddings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

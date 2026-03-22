"""Provider implementations for Agent Brain.

Base classes (no extra dependencies):

    from agent_brain.providers import LLMProvider, EmbeddingProvider, StorageBackend
    from agent_brain.providers import JSONStorage

OpenAI providers (requires: pip install agent-brain[openai]):

    from agent_brain.providers import OpenAIProvider, OpenAIEmbeddings

Anthropic provider (requires: pip install agent-brain[anthropic]):

    from agent_brain.providers import AnthropicProvider
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
]

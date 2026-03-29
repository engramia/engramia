# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Abstract base classes for all pluggable Engramia providers.

Three provider roles:
- LLMProvider    — generates text (OpenAI, Anthropic, any LLM)
- EmbeddingProvider — produces dense vectors (OpenAI, local, ...)
- StorageBackend — persists data and serves vector search (JSON, Postgres, ...)

To add a new provider, subclass the relevant ABC and implement all
@abstractmethod methods. Engramia accepts any compliant implementation.
"""

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Generates text from a prompt.

    Implementations handle model selection, retries, and cost tracking
    internally. Engramia only calls call() and expects a string back.
    """

    @abstractmethod
    def call(
        self,
        prompt: str,
        system: str | None = None,
        role: str = "default",
    ) -> str:
        """Send a prompt and return the model response.

        Args:
            prompt: User message content.
            system: Optional system prompt.
            role: Logical role hint for model routing
                (e.g. "coder", "eval", "architect", "default").
                Providers may use this to select a cheaper/faster model
                for simpler roles. Ignored if the provider doesn't support routing.

        Returns:
            The model's text response.
        """


class EmbeddingProvider(ABC):
    """Produces dense vector representations of text."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Embed a single text into a dense vector.

        Args:
            text: Input text to embed.

        Returns:
            Embedding vector as a list of floats.
        """

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts.

        Default implementation calls embed() sequentially.
        Override for native batch API support (e.g. OpenAI embeddings batch).

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors, same order as input.
        """
        return [self.embed(text) for text in texts]


class StorageBackend(ABC):
    """Persists Engramia data and provides vector similarity search.

    Two concerns in one interface:
    1. Key-value store for structured data (patterns, evals, metrics, ...)
    2. Embedding index for semantic search (search_similar)

    Implementations:
    - JSONStorage: brute-force cosine similarity over in-memory vectors. No deps.
    - PostgresStorage: pgvector index (<=> cosine distance). Scales to millions.
    """

    # ------------------------------------------------------------------
    # Key-value store
    # ------------------------------------------------------------------

    @abstractmethod
    def load(self, key: str) -> dict[str, Any] | None:
        """Load data by key.

        Args:
            key: Storage key (e.g. "patterns/abc123").

        Returns:
            Stored dict, or None if the key does not exist.
        """

    @abstractmethod
    def save(self, key: str, data: dict | list) -> None:  # type: ignore[type-arg]
        """Persist data under key. Overwrites if key exists.

        Args:
            key: Storage key.
            data: JSON-serialisable dict (or list for internal stores) to store.
        """

    @abstractmethod
    def list_keys(self, prefix: str = "") -> list[str]:
        """List all keys, optionally filtered by prefix.

        Args:
            prefix: If non-empty, return only keys starting with this prefix.

        Returns:
            Sorted list of matching keys.
        """

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a key and its associated embedding (if any).

        No-op if the key does not exist.

        Args:
            key: Storage key to remove.
        """

    # ------------------------------------------------------------------
    # Embedding index
    # ------------------------------------------------------------------

    @abstractmethod
    def save_embedding(self, key: str, embedding: list[float]) -> None:
        """Associate an embedding vector with a key.

        Called alongside save() when storing a new pattern.
        The key must match the data key used in save().

        Args:
            key: Storage key this embedding belongs to.
            embedding: Dense vector from EmbeddingProvider.embed().
        """

    @abstractmethod
    def search_similar(
        self,
        embedding: list[float],
        limit: int = 10,
        prefix: str = "",
    ) -> list[tuple[str, float]]:
        """Find the most similar stored embeddings to a query vector.

        Args:
            embedding: Query vector.
            limit: Maximum number of results to return.
            prefix: If non-empty, search only among keys with this prefix.

        Returns:
            List of (key, similarity_score) tuples sorted by similarity
            descending. Similarity is cosine similarity in [0.0, 1.0].
        """

    @abstractmethod
    def count_patterns(self, prefix: str = "patterns/") -> int:
        """Count stored keys matching *prefix* within the current scope.

        Used for quota enforcement before ``learn()`` and ``import()``.

        Args:
            prefix: Key prefix to count (default ``'patterns/'``).

        Returns:
            Number of matching keys in the current tenant/project scope.
        """

    # ------------------------------------------------------------------
    # Governance (Phase 5.6) — optional, default no-ops
    # ------------------------------------------------------------------

    def save_pattern_meta(
        self,
        key: str,
        *,
        classification: str = "internal",
        source: str | None = None,
        run_id: str | None = None,
        author: str | None = None,
        redacted: bool = False,
        expires_at: str | None = None,
    ) -> None:
        """Persist governance metadata for a pattern key.

        Called after ``save()`` when provenance or governance attributes are
        available. Default implementation is a no-op — JSONStorage silently
        ignores this; PostgresStorage overrides to write the dedicated columns.

        Args:
            key: Storage key of the pattern (e.g. ``"patterns/abc123"``).
            classification: Data sensitivity level (``"internal"`` by default).
            source: Origin of the pattern (``'api'``, ``'sdk'``, ``'cli'``, ``'import'``).
            run_id: Caller-supplied correlation ID for this agent run.
            author: Identifier of the creator (key_id or service name).
            redacted: True if PII/secrets were removed before storage.
            expires_at: ISO-8601 UTC timestamp when this pattern expires (or None).
        """

    def delete_scope(self, tenant_id: str, project_id: str) -> int:
        """Delete all data keys for a tenant/project scope.

        Used by scoped deletion (GDPR Art. 17). Returns the number of keys
        deleted. Default implementation iterates ``list_keys`` — backends may
        override for bulk-delete efficiency.

        Args:
            tenant_id: Tenant to delete.
            project_id: Project to delete (``"*"`` means all projects in tenant).

        Returns:
            Number of keys deleted.
        """
        from engramia._context import get_scope, reset_scope, set_scope
        from engramia.types import Scope

        token = set_scope(Scope(tenant_id=tenant_id, project_id=project_id))
        try:
            keys = self.list_keys()
            for key in keys:
                self.delete(key)
            return len(keys)
        finally:
            reset_scope(token)

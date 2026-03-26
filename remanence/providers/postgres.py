"""PostgreSQL + pgvector storage backend.

Requires the ``postgres`` extra:
    pip install agent-brain[postgres]

Uses SQLAlchemy 2.x with a connection pool. Each method opens and closes
a connection from the pool — safe for concurrent access from multiple
threads (FastAPI threadpool workers).

Vector search uses pgvector's HNSW index via the ``<=>`` cosine distance
operator. Results are returned as (key, similarity) tuples where
similarity = 1 - cosine_distance.
"""

from __future__ import annotations

import logging

from remanence.providers.base import StorageBackend

_log = logging.getLogger(__name__)

_POSTGRES_INSTALL_MSG = (
    "PostgresStorage requires SQLAlchemy + psycopg2 + pgvector. Install with: pip install agent-brain[postgres]"
)


class PostgresStorage(StorageBackend):
    """Stores Brain data in PostgreSQL using a generic KV schema + pgvector.

    Table schema (created by Alembic migration 001_initial):
    - ``brain_data(key TEXT PK, data JSONB, updated_at TEXT)``
    - ``brain_embeddings(key TEXT PK, embedding vector(1536))``

    Writes are transactional. Vector search uses an HNSW index for
    sub-millisecond approximate nearest-neighbour queries.

    Args:
        database_url: PostgreSQL connection URL.
            Example: ``postgresql://user:pass@localhost:5432/brain``
            Also read from ``REMANENCE_DATABASE_URL`` env var if not provided.
        pool_size: SQLAlchemy connection pool size (default 5).
        embedding_dim: Dimension of embedding vectors (default 1536 for
            OpenAI text-embedding-3-small).
    """

    def __init__(
        self,
        database_url: str | None = None,
        pool_size: int = 5,
        embedding_dim: int = 1536,
    ) -> None:
        try:
            import os

            from sqlalchemy import create_engine, text
            from sqlalchemy.pool import QueuePool
        except ImportError:
            raise ImportError(_POSTGRES_INSTALL_MSG) from None

        url = database_url or os.environ.get("REMANENCE_DATABASE_URL")
        if not url:
            raise ValueError(
                "PostgresStorage requires a database URL. Pass database_url=... or set REMANENCE_DATABASE_URL env var."
            )

        self._embedding_dim = embedding_dim
        self._engine = create_engine(
            url,
            poolclass=QueuePool,
            pool_size=pool_size,
            max_overflow=10,
            pool_pre_ping=True,  # detect stale connections
        )
        self._text = text  # store reference for use in methods
        _log.info("PostgresStorage connected to %s", _redact_url(url))

    # ------------------------------------------------------------------
    # StorageBackend: key-value store
    # ------------------------------------------------------------------

    def load(self, key: str) -> dict | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                self._text("SELECT data FROM brain_data WHERE key = :key"),
                {"key": key},
            ).fetchone()
        return dict(row[0]) if row else None

    def save(self, key: str, data: dict | list) -> None:  # type: ignore[override]
        import json

        with self._engine.begin() as conn:
            conn.execute(
                self._text(
                    """
                    INSERT INTO brain_data (key, data, updated_at)
                    VALUES (:key, :data::jsonb, now()::text)
                    ON CONFLICT (key) DO UPDATE
                        SET data = EXCLUDED.data,
                            updated_at = EXCLUDED.updated_at
                    """
                ),
                {"key": key, "data": json.dumps(data)},
            )

    def list_keys(self, prefix: str = "") -> list[str]:
        with self._engine.connect() as conn:
            if prefix:
                safe_prefix = _escape_like(prefix)
                rows = conn.execute(
                    self._text("SELECT key FROM brain_data WHERE key LIKE :prefix ESCAPE '\\' ORDER BY key"),
                    {"prefix": f"{safe_prefix}%"},
                ).fetchall()
            else:
                rows = conn.execute(self._text("SELECT key FROM brain_data ORDER BY key")).fetchall()
        return [row[0] for row in rows]

    def delete(self, key: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                self._text("DELETE FROM brain_data WHERE key = :key"),
                {"key": key},
            )
            # brain_embeddings has no FK cascade in the migration — delete explicitly
            conn.execute(
                self._text("DELETE FROM brain_embeddings WHERE key = :key"),
                {"key": key},
            )

    # ------------------------------------------------------------------
    # StorageBackend: embedding index
    # ------------------------------------------------------------------

    def save_embedding(self, key: str, embedding: list[float]) -> None:
        if len(embedding) != self._embedding_dim:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self._embedding_dim}, "
                f"got {len(embedding)}. Ensure all embeddings use the same provider and model."
            )
        vec_str = _vec_to_pg(embedding)
        with self._engine.begin() as conn:
            conn.execute(
                self._text(
                    """
                    INSERT INTO brain_embeddings (key, embedding)
                    VALUES (:key, :embedding::vector)
                    ON CONFLICT (key) DO UPDATE
                        SET embedding = EXCLUDED.embedding
                    """
                ),
                {"key": key, "embedding": vec_str},
            )

    def search_similar(
        self,
        embedding: list[float],
        limit: int = 10,
        prefix: str = "",
    ) -> list[tuple[str, float]]:
        """ANN cosine search via pgvector HNSW index.

        Returns (key, similarity) pairs where similarity = 1 - cosine_distance.
        Results are already filtered by prefix and sorted by similarity descending.
        """
        if len(embedding) != self._embedding_dim:
            raise ValueError(
                f"Query embedding dimension {len(embedding)} does not match stored dimension {self._embedding_dim}."
            )
        vec_str = _vec_to_pg(embedding)
        with self._engine.connect() as conn:
            if prefix:
                safe_prefix = _escape_like(prefix)
                rows = conn.execute(
                    self._text(
                        """
                        SELECT key, 1 - (embedding <=> :vec::vector) AS similarity
                        FROM brain_embeddings
                        WHERE key LIKE :prefix ESCAPE '\\'
                        ORDER BY embedding <=> :vec::vector
                        LIMIT :limit
                        """
                    ),
                    {"vec": vec_str, "prefix": f"{safe_prefix}%", "limit": limit},
                ).fetchall()
            else:
                rows = conn.execute(
                    self._text(
                        """
                        SELECT key, 1 - (embedding <=> :vec::vector) AS similarity
                        FROM brain_embeddings
                        ORDER BY embedding <=> :vec::vector
                        LIMIT :limit
                        """
                    ),
                    {"vec": vec_str, "limit": limit},
                ).fetchall()
        return [(row[0], float(row[1])) for row in rows]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcard characters (%, _, \\) in *value*."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _vec_to_pg(embedding: list[float]) -> str:
    """Convert a Python float list to pgvector literal: ``[0.1,0.2,...]``."""
    return "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"


def _redact_url(url: str) -> str:
    """Replace password in a database URL with *** for logging."""
    import re

    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1***\2", url)

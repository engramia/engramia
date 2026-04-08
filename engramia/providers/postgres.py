# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""PostgreSQL + pgvector storage backend.

Requires the ``postgres`` extra:
    pip install engramia[postgres]

Uses SQLAlchemy 2.x with a connection pool. Each method opens and closes
a connection from the pool — safe for concurrent access from multiple
threads (FastAPI threadpool workers).

Vector search uses pgvector's HNSW index via the ``<=>`` cosine distance
operator. Results are returned as (key, similarity) tuples where
similarity = 1 - cosine_distance.

All queries are scoped to the current tenant and project via
``engramia._context.get_scope()``, which is set by the auth dependency at
the start of each request. This provides row-level isolation between tenants
without any application-level changes to the Memory API.
"""

from __future__ import annotations

import logging
from typing import Any

from engramia.providers.base import StorageBackend

_log = logging.getLogger(__name__)

_POSTGRES_INSTALL_MSG = (
    "PostgresStorage requires SQLAlchemy + psycopg2 + pgvector. Install with: pip install engramia[postgres]"
)


class PostgresStorage(StorageBackend):
    """Stores Engramia data in PostgreSQL using a generic KV schema + pgvector.

    Table schema (created by Alembic migrations):
    - ``memory_data(key TEXT PK, tenant_id TEXT, project_id TEXT, data JSONB, updated_at TEXT)``
    - ``memory_embeddings(key TEXT PK, tenant_id TEXT, project_id TEXT, embedding vector(1536))``

    All queries filter by the current scope (tenant_id, project_id) obtained
    from ``engramia._context.get_scope()``. This ensures complete data
    isolation between tenants — one tenant cannot read, search, or delete
    another tenant's patterns.

    Writes are transactional. Vector search uses an HNSW index for
    sub-millisecond approximate nearest-neighbour queries.

    Args:
        database_url: PostgreSQL connection URL.
            Example: ``postgresql://user:pass@localhost:5432/engramia``
            Also read from ``ENGRAMIA_DATABASE_URL`` env var if not provided.
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

        url = database_url or os.environ.get("ENGRAMIA_DATABASE_URL")
        if not url:
            raise ValueError(
                "PostgresStorage requires a database URL. Pass database_url=... or set ENGRAMIA_DATABASE_URL env var."
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
    # Internal helpers
    # ------------------------------------------------------------------

    def _scope_params(self) -> dict[str, str]:
        """Return {'tid': tenant_id, 'pid': project_id} for the current request."""
        from engramia._context import get_scope

        s = get_scope()
        return {"tid": s.tenant_id, "pid": s.project_id}

    # ------------------------------------------------------------------
    # StorageBackend: key-value store
    # ------------------------------------------------------------------

    def load(self, key: str) -> dict[str, Any] | None:
        sp = self._scope_params()
        with self._engine.connect() as conn:
            row = conn.execute(
                self._text("SELECT data FROM memory_data WHERE key = :key AND tenant_id = :tid AND project_id = :pid"),
                {"key": key, **sp},
            ).fetchone()
        return row[0] if row else None  # psycopg2 deserialises JSONB to dict/list directly

    def save(self, key: str, data: dict[str, Any] | list[Any]) -> None:
        import json

        sp = self._scope_params()
        with self._engine.begin() as conn:
            conn.execute(
                self._text(
                    """
                    INSERT INTO memory_data (key, tenant_id, project_id, data, updated_at)
                    VALUES (:key, :tid, :pid, CAST(:data AS jsonb), now()::text)
                    ON CONFLICT (tenant_id, project_id, key) DO UPDATE
                        SET data       = EXCLUDED.data,
                            updated_at = EXCLUDED.updated_at
                    """
                ),
                {"key": key, "data": json.dumps(data), **sp},
            )

    def list_keys(self, prefix: str = "") -> list[str]:
        sp = self._scope_params()
        with self._engine.connect() as conn:
            if prefix:
                safe_prefix = _escape_like(prefix)
                rows = conn.execute(
                    self._text(
                        "SELECT key FROM memory_data "
                        "WHERE key LIKE :prefix ESCAPE '\\' "
                        "AND tenant_id = :tid AND project_id = :pid "
                        "ORDER BY key"
                    ),
                    {"prefix": f"{safe_prefix}%", **sp},
                ).fetchall()
            else:
                rows = conn.execute(
                    self._text("SELECT key FROM memory_data WHERE tenant_id = :tid AND project_id = :pid ORDER BY key"),
                    sp,
                ).fetchall()
        return [row[0] for row in rows]

    def delete(self, key: str) -> None:
        sp = self._scope_params()
        with self._engine.begin() as conn:
            conn.execute(
                self._text("DELETE FROM memory_data WHERE key = :key AND tenant_id = :tid AND project_id = :pid"),
                {"key": key, **sp},
            )
            conn.execute(
                self._text("DELETE FROM memory_embeddings WHERE key = :key AND tenant_id = :tid AND project_id = :pid"),
                {"key": key, **sp},
            )

    def count_patterns(self, prefix: str = "patterns/") -> int:
        sp = self._scope_params()
        safe_prefix = _escape_like(prefix)
        with self._engine.connect() as conn:
            row = conn.execute(
                self._text(
                    "SELECT COUNT(*) FROM memory_data "
                    "WHERE key LIKE :prefix ESCAPE '\\' "
                    "AND tenant_id = :tid AND project_id = :pid"
                ),
                {"prefix": f"{safe_prefix}%", **sp},
            ).fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # StorageBackend: embedding index
    # ------------------------------------------------------------------

    def save_embedding(self, key: str, embedding: list[float]) -> None:
        if len(embedding) != self._embedding_dim:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self._embedding_dim}, "
                f"got {len(embedding)}. Ensure all embeddings use the same provider and model."
            )
        sp = self._scope_params()
        vec_str = _vec_to_pg(embedding)
        with self._engine.begin() as conn:
            conn.execute(
                self._text(
                    """
                    INSERT INTO memory_embeddings (key, tenant_id, project_id, embedding)
                    VALUES (:key, :tid, :pid, :vec::vector)
                    ON CONFLICT (tenant_id, project_id, key) DO UPDATE
                        SET embedding = EXCLUDED.embedding
                    """
                ),
                {"key": key, "vec": vec_str, **sp},
            )

    # ------------------------------------------------------------------
    # Governance (Phase 5.6)
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
        """Update governance metadata columns for a pattern row."""
        sp = self._scope_params()
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    self._text(
                        "UPDATE memory_data "
                        "SET classification = :cls, source = :src, run_id = :rid, "
                        "    author = :author, redacted = :redacted, expires_at = :expires "
                        "WHERE key = :key AND tenant_id = :tid AND project_id = :pid"
                    ),
                    {
                        "cls": classification,
                        "src": source,
                        "rid": run_id,
                        "author": author,
                        "redacted": redacted,
                        "expires": expires_at,
                        "key": key,
                        **sp,
                    },
                )
        except Exception as exc:
            _log.warning("save_pattern_meta failed for key %r: %s", key, exc)

    def delete_scope(self, tenant_id: str, project_id: str) -> int:
        """Bulk-delete all memory_data and memory_embeddings rows for a scope."""
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    self._text("DELETE FROM memory_embeddings WHERE tenant_id = :tid AND project_id = :pid"),
                    {"tid": tenant_id, "pid": project_id},
                )
                r = conn.execute(
                    self._text("DELETE FROM memory_data WHERE tenant_id = :tid AND project_id = :pid"),
                    {"tid": tenant_id, "pid": project_id},
                )
            return r.rowcount
        except Exception as exc:
            _log.error("delete_scope failed for %s/%s: %s", tenant_id, project_id, exc)
            raise

    def search_similar(
        self,
        embedding: list[float],
        limit: int = 10,
        prefix: str = "",
    ) -> list[tuple[str, float]]:
        """ANN cosine search via pgvector HNSW index, scoped to current tenant/project.

        Returns (key, similarity) pairs where similarity = 1 - cosine_distance.
        Results are filtered by scope and prefix, sorted by similarity descending.
        """
        if len(embedding) != self._embedding_dim:
            raise ValueError(
                f"Query embedding dimension {len(embedding)} does not match stored dimension {self._embedding_dim}."
            )
        sp = self._scope_params()
        vec_str = _vec_to_pg(embedding)
        with self._engine.connect() as conn:
            if prefix:
                safe_prefix = _escape_like(prefix)
                rows = conn.execute(
                    self._text(
                        """
                        SELECT key, 1 - (embedding <=> :vec::vector) AS similarity
                        FROM memory_embeddings
                        WHERE key LIKE :prefix ESCAPE '\\'
                          AND tenant_id = :tid
                          AND project_id = :pid
                        ORDER BY embedding <=> :vec::vector
                        LIMIT :limit
                        """
                    ),
                    {"prefix": f"{safe_prefix}%", "limit": limit, "vec": vec_str, **sp},
                ).fetchall()
            else:
                rows = conn.execute(
                    self._text(
                        """
                        SELECT key, 1 - (embedding <=> :vec::vector) AS similarity
                        FROM memory_embeddings
                        WHERE tenant_id = :tid
                          AND project_id = :pid
                        ORDER BY embedding <=> :vec::vector
                        LIMIT :limit
                        """
                    ),
                    {"limit": limit, "vec": vec_str, **sp},
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

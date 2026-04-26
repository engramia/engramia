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
import time
from typing import Any

from engramia.providers.base import StorageBackend
from engramia.telemetry import metrics as _metrics

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
            pool_recycle=1800,  # recycle connections after 30 min to avoid stale TCP behind firewalls
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
        t0 = time.perf_counter()
        sp = self._scope_params()
        with self._engine.connect() as conn:
            row = conn.execute(
                self._text("SELECT data FROM memory_data WHERE key = :key AND tenant_id = :tid AND project_id = :pid"),
                {"key": key, **sp},
            ).fetchone()
        _metrics.observe_storage("postgres", "load", time.perf_counter() - t0)
        return row[0] if row else None  # psycopg2 deserialises JSONB to dict/list directly

    def save(self, key: str, data: dict[str, Any] | list[Any]) -> None:
        import json

        t0 = time.perf_counter()
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
        _metrics.observe_storage("postgres", "save", time.perf_counter() - t0)

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
                    VALUES (:key, :tid, :pid, CAST(:vec AS vector))
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
        classification: str | None = None,
        source: str | None = None,
        run_id: str | None = None,
        author: str | None = None,
        redacted: bool | None = None,
        expires_at: str | None = None,
    ) -> None:
        """Update governance metadata columns for a pattern row.

        Only columns whose argument is non-None are updated. Pass an explicit
        value to overwrite; omit the kwarg to leave the existing value intact.
        Previously this method updated all columns unconditionally, clobbering
        unrelated metadata when a caller wanted to set only one field.
        """
        updates: dict[str, object] = {}
        if classification is not None:
            updates["classification"] = classification
        if source is not None:
            updates["source"] = source
        if run_id is not None:
            updates["run_id"] = run_id
        if author is not None:
            updates["author"] = author
        if redacted is not None:
            updates["redacted"] = redacted
        if expires_at is not None:
            updates["expires_at"] = expires_at
        if not updates:
            return

        sp = self._scope_params()
        set_parts = [f"{col} = :{col}" for col in updates]
        # Mirror governance metadata into the JSONB design blob so callers
        # that read pattern.design.classification (e.g. recall's filter in
        # routes.py) see the same value as the column. Without this mirror
        # the column and the JSONB diverge on every classify call: the
        # column updates, the JSONB stays frozen at learn-time, and the
        # recall classification filter looks at the wrong source.
        #
        # Pre-serialise the JSON-string form so the bind param ends up as
        # ``"confidential"`` (a JSONB scalar string) rather than
        # ``confidential`` (which would parse as a jsonb literal of an
        # invalid identifier and silently no-op).
        bind: dict[str, object] = {**updates, "key": key, **sp}
        # data column is sa.JSON, not JSONB — need explicit data::jsonb on the
        # input and ::json on the output for the assignment. Multiple jsonb_set
        # calls must chain into one expression because the SQL UPDATE can't
        # assign data twice.
        json_assignments: list[str] = []
        if "classification" in updates:
            import json as _json
            # Bind names without a leading underscore — SQLAlchemy 2.x's
            # text() parameter regex tolerates underscores but a few of our
            # adapter layers strip leading-underscore "private" identifiers
            # before forwarding to psycopg2, which would silently drop the
            # bind and leave the JSONB unchanged.
            json_assignments.append(("'{design,classification}'", ":cls_json"))
            bind["cls_json"] = _json.dumps(updates["classification"])
        if "source" in updates:
            import json as _json
            json_assignments.append(("'{design,source}'", ":src_json"))
            bind["src_json"] = _json.dumps(updates["source"])
        if json_assignments:
            # Use CAST(... AS ...) instead of the ::type shorthand. SQLAlchemy
            # text()'s bind-param regex has a `(?!:)` lookahead that drops
            # `:name::type` because the trailing `::` looks like another
            # parameter prefix. Spelled-out CAST has no `::` so each `:name`
            # is recognised cleanly.
            inner = "CAST(data AS jsonb)"
            for path, param in json_assignments:
                inner = f"jsonb_set({inner}, {path}, CAST({param} AS jsonb))"
            set_parts.append(f"data = CAST({inner} AS json)")
        set_clause = ", ".join(set_parts)
        sql = (
            f"UPDATE memory_data SET {set_clause} "
            "WHERE key = :key AND tenant_id = :tid AND project_id = :pid"
        )
        try:
            with self._engine.begin() as conn:
                result = conn.execute(self._text(sql), bind)
            if result.rowcount == 0:
                _log.warning(
                    "save_pattern_meta updated 0 rows for key=%r — pattern missing or scope mismatch",
                    key,
                )
        except Exception as exc:
            _log.warning("save_pattern_meta failed for key %r: %s", key, exc, exc_info=True)

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
                        SELECT key, 1 - (embedding <=> CAST(:vec AS vector)) AS similarity
                        FROM memory_embeddings
                        WHERE key LIKE :prefix ESCAPE '\\'
                          AND tenant_id = :tid
                          AND project_id = :pid
                        ORDER BY embedding <=> CAST(:vec AS vector)
                        LIMIT :limit
                        """
                    ),
                    {"prefix": f"{safe_prefix}%", "limit": limit, "vec": vec_str, **sp},
                ).fetchall()
            else:
                rows = conn.execute(
                    self._text(
                        """
                        SELECT key, 1 - (embedding <=> CAST(:vec AS vector)) AS similarity
                        FROM memory_embeddings
                        WHERE tenant_id = :tid
                          AND project_id = :pid
                        ORDER BY embedding <=> CAST(:vec AS vector)
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

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""SQLAlchemy 2.x models for PostgreSQL + pgvector storage backend.

Schema design:
- ``memory_data``       — generic key-value store (TEXT key, JSONB data)
- ``memory_embeddings`` — vector index (TEXT key, pgvector vector(1536))

The two tables share the same key namespace. ``memory_embeddings`` has a
foreign key to ``memory_data`` so deleting a data row cascades to its vector.

HNSW index on ``memory_embeddings.embedding`` enables sub-millisecond ANN
search via pgvector's ``<=>`` cosine distance operator.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MemoryData(Base):
    """Generic key-value store for all Engramia data objects."""

    __tablename__ = "memory_data"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class MemoryEmbedding(Base):
    """Embedding vectors stored separately for efficient pgvector indexing."""

    __tablename__ = "memory_embeddings"

    key: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
    )
    # Vector dimension is fixed at 1536 (OpenAI text-embedding-3-small).
    # pgvector requires a concrete dimension at DDL time.
    # Use the HNSW index below for approximate nearest-neighbour search.
    embedding: Mapped[list] = mapped_column(Vector(1536), nullable=False)


# HNSW index for cosine similarity search.
# m=16, ef_construction=64 are pgvector defaults — tune for dataset size.
hnsw_index = Index(
    "idx_memory_embeddings_hnsw",
    MemoryEmbedding.embedding,
    postgresql_using="hnsw",
    postgresql_with={"m": 16, "ef_construction": 64},
    postgresql_ops={"embedding": "vector_cosine_ops"},
)

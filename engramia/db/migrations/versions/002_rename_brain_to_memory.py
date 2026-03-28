# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Rename brain_* tables to memory_*.

Revision ID: 002
Revises: 001
Create Date: 2026-03-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "002"
down_revision: str = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop old index (references old table name)
    op.execute("DROP INDEX IF EXISTS idx_brain_embeddings_hnsw")

    # Rename tables
    op.rename_table("brain_data", "memory_data")
    op.rename_table("brain_embeddings", "memory_embeddings")

    # Recreate HNSW index with new name on renamed table
    op.execute(
        "CREATE INDEX idx_memory_embeddings_hnsw "
        "ON memory_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_memory_embeddings_hnsw")

    op.rename_table("memory_data", "brain_data")
    op.rename_table("memory_embeddings", "brain_embeddings")

    op.execute(
        "CREATE INDEX idx_brain_embeddings_hnsw "
        "ON brain_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

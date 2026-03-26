"""Initial schema: brain_data + brain_embeddings with HNSW index.

Revision ID: 001
Revises:
Create Date: 2026-03-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable pgvector extension (requires PostgreSQL with pgvector installed)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "brain_data",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("data", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.Text,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "brain_embeddings",
        sa.Column("key", sa.Text, primary_key=True),
        # pgvector vector type — 1536 dimensions (OpenAI text-embedding-3-small)
        sa.Column(
            "embedding",
            sa.Text,  # DDL handled via raw SQL below; SA doesn't know Vector type
            nullable=False,
        ),
    )

    # Re-create embedding column with proper pgvector type
    op.execute("ALTER TABLE brain_embeddings ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)")

    # HNSW index for approximate nearest-neighbour cosine search
    op.execute(
        "CREATE INDEX idx_brain_embeddings_hnsw "
        "ON brain_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_brain_embeddings_hnsw")
    op.drop_table("brain_embeddings")
    op.drop_table("brain_data")

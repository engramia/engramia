# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""A08 — Database Migration snippets (good / medium / bad).

Domain: Alembic migrations, schema changes, data backfills, zero-downtime patterns.
"""

GOOD: dict = {
    "eval_score": 9.1,
    "output": "Alembic migration: split users into accounts + profiles with backfill. Reversible, batched, zero-downtime compatible.",
    "code": '''\
"""Split users table into accounts and profiles.

Revision ID: a3f8c2d1e456
Revises: 98b1d4f7c890
Create Date: 2026-03-15 14:30:00.000000

Strategy:
  1. Create new tables (accounts, profiles)
  2. Backfill data in batches (avoid locking)
  3. Add foreign key constraints
  4. Old 'users' table kept for rollback safety — drop in next migration
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "a3f8c2d1e456"
down_revision = "98b1d4f7c890"
branch_labels = None
depends_on = None

BATCH_SIZE = 1000


def upgrade() -> None:
    # 1. Create new tables
    op.create_table(
        "accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_index("ix_profiles_account_id", "profiles", ["account_id"])

    # 2. Backfill in batches
    conn = op.get_bind()
    total = conn.execute(sa.text("SELECT count(*) FROM users")).scalar()

    for offset in range(0, total, BATCH_SIZE):
        conn.execute(sa.text("""
            WITH batch AS (
                SELECT id, email, password_hash, is_active, created_at, last_login_at,
                       display_name, bio, avatar_url
                FROM users
                ORDER BY id
                LIMIT :batch_size OFFSET :offset
            ),
            inserted_accounts AS (
                INSERT INTO accounts (id, email, password_hash, is_active, created_at, last_login_at)
                SELECT id, email, password_hash, is_active, created_at, last_login_at
                FROM batch
                RETURNING id
            )
            INSERT INTO profiles (account_id, display_name, bio, avatar_url)
            SELECT b.id, b.display_name, b.bio, b.avatar_url
            FROM batch b
        """), {"batch_size": BATCH_SIZE, "offset": offset})
        conn.commit()


def downgrade() -> None:
    op.drop_table("profiles")
    op.drop_table("accounts")
''',
}

MEDIUM: dict = {
    "eval_score": 6.0,
    "output": "Migration created for splitting users table.",
    "code": """\
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table("accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255)),
        sa.Column("password_hash", sa.String(255)),
    )
    op.create_table("profiles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id")),
        sa.Column("display_name", sa.String(100)),
    )
    # copy data
    op.execute("INSERT INTO accounts SELECT id, email, password_hash FROM users")
    op.execute("INSERT INTO profiles SELECT id, id, display_name FROM users")

def downgrade():
    op.drop_table("profiles")
    op.drop_table("accounts")
""",
}

BAD: dict = {
    "eval_score": 2.5,
    "output": "migration file",
    "code": """\
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.rename_table("users", "accounts")
    # TODO: create profiles table
    # TODO: move columns

def downgrade():
    op.rename_table("accounts", "users")
""",
}

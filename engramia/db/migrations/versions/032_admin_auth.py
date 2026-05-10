# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Admin Dashboard auth + audit tables.

Adds four tables that back the new operator/super-admin Admin Dashboard
(``Admin/`` repo) — entirely separate from tenant ``cloud_users`` and
tenant ``audit_log``:

  * ``admin_users``           — super-admin accounts (single user today;
                                schema admits multi-admin in Phase 4).
                                ``totp_secret`` is stored ciphertext and
                                decrypted at verification time using the
                                same AES-GCM primitive that protects
                                ``tenant_credentials`` (Phase 6.6).
  * ``admin_sessions``        — issued admin JWT pairs. ``totp_issued_at``
                                is the freshness anchor for the
                                ``require_fresh_totp(window=300)``
                                dependency that gates destructive admin
                                routes.
  * ``admin_login_attempts``  — append-only log of every login + TOTP
                                verification, success or failure.
                                Powers the brute-force lockout and
                                forensic review.
  * ``admin_audit_log``       — append-only trail of every admin action.
                                Distinct from tenant ``audit_log`` because
                                (a) retention is 7 years (SOC2) versus
                                tenant's Art.17-scrubbing policy, and
                                (b) admin actions can be cross-tenant or
                                tenant-less (e.g. ``pilot.approve`` runs
                                before a tenant exists).

JSONB ``detail`` follows the project-wide ``CAST(:p AS jsonb)`` +
``json.dumps()`` rule — see ``engramia.api.audit:144`` and
``MEMORY.md feedback_sqlalchemy_jsonb``.

Revision ID: 032
Revises: 031
Create Date: 2026-05-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers.
revision: str = "032"
down_revision: str | None = "031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    jsonb_type = sa.dialects.postgresql.JSONB() if is_postgres else sa.JSON()
    timestamptz = sa.dialects.postgresql.TIMESTAMP(timezone=True) if is_postgres else sa.DateTime()

    # ------------------------------------------------------------------
    # admin_users
    # ------------------------------------------------------------------
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.Text(), nullable=False),
        # bcrypt hash; matches existing ``cloud_users.password_hash`` choice.
        sa.Column("password_hash", sa.Text(), nullable=False),
        # AES-GCM ciphertext of the TOTP shared secret. The ``totp_enrolled``
        # flag tells the login flow whether to demand a code (false during
        # the brief window between bootstrap and first enrollment).
        sa.Column("totp_secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("totp_enrolled", sa.Boolean(), nullable=False, server_default=sa.false()),
        # active | locked | disabled. Lockouts are soft (``locked``) so the
        # CLI break-glass ``engramia admin reset-totp`` can flip back without
        # losing audit history attached to the row.
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", timestamptz, nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", timestamptz, nullable=True),
        sa.Column("last_login_ip", sa.Text(), nullable=True),
        sa.UniqueConstraint("email", name="uq_admin_users_email"),
        sa.CheckConstraint(
            "status IN ('active', 'locked', 'disabled')",
            name="ck_admin_users_status",
        ),
    )

    # ------------------------------------------------------------------
    # admin_sessions
    # ------------------------------------------------------------------
    # ``id`` doubles as the JWT ``jti`` — looking up a session by token
    # claim is one indexed read.
    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Text(), primary_key=True),  # uuid4 hex
        sa.Column(
            "admin_user_id",
            sa.Integer(),
            sa.ForeignKey("admin_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SHA-256 of refresh token plaintext. We never store the plaintext;
        # rotation = compare incoming hash, then issue a new row.
        sa.Column("refresh_token_hash", sa.Text(), nullable=False),
        sa.Column("issued_at", timestamptz, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", timestamptz, nullable=False),
        # ``totp_issued_at`` is the source of truth for the
        # require_fresh_totp(window=300) gate. ``/auth/totp/reauth`` advances
        # this timestamp without minting a new session.
        sa.Column("totp_issued_at", timestamptz, nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("revoked_at", timestamptz, nullable=True),
    )
    op.create_index(
        "idx_admin_sessions_user_active",
        "admin_sessions",
        ["admin_user_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    # ------------------------------------------------------------------
    # admin_login_attempts
    # ------------------------------------------------------------------
    op.create_table(
        "admin_login_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        # Email is captured verbatim — the row records *attempts* to log in
        # as a given identity, including ones for which no admin_user exists.
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("ip_address", sa.Text(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column(
            "stage",
            sa.Text(),
            nullable=False,
            comment="'password' | 'totp'",
        ),
        # Free-form failure reason. Examples:
        #   bad_password | bad_totp | unknown_email | locked | totp_not_enrolled
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("attempted_at", timestamptz, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "idx_admin_login_attempts_email_time",
        "admin_login_attempts",
        ["email", "attempted_at"],
    )
    op.create_index(
        "idx_admin_login_attempts_ip_time",
        "admin_login_attempts",
        ["ip_address", "attempted_at"],
    )

    # ------------------------------------------------------------------
    # admin_audit_log
    # ------------------------------------------------------------------
    # Two-row pattern is implemented as one row with status transitions:
    #   INSERT ... status='attempted'   (before action)
    #   UPDATE status='succeeded'|'failed', completed_at=now()  (after)
    # Failed-mid-action rows therefore stay visible as ``attempted`` —
    # exactly what we want for forensics on a crashed admin process.
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "actor_admin_user_id",
            sa.Integer(),
            sa.ForeignKey("admin_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=True),
        sa.Column("resource_id", sa.Text(), nullable=True),
        # Nullable + no FK: admin actions can target tenants that don't
        # exist yet (pilot.approve creates the tenant) or are already gone
        # (post-deletion forensic note). The split column also makes
        # cross-tenant queries cheap (``WHERE target_tenant_id = X``).
        sa.Column("target_tenant_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            comment="'attempted' | 'succeeded' | 'failed'",
        ),
        # Which Core endpoint the action was routed to — staging or prod.
        # Captured by the admin router from request.app.state at INSERT time.
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("ip_address", sa.Text(), nullable=False),
        # JSONB on PostgreSQL, JSON on SQLite. The application layer always
        # passes a ``json.dumps()``-ed string and the read path parses
        # again (mirrors engramia.api.audit pattern).
        sa.Column("detail", jsonb_type, nullable=True),
        sa.Column("created_at", timestamptz, nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", timestamptz, nullable=True),
    )
    op.create_index(
        "idx_admin_audit_log_action_time",
        "admin_audit_log",
        ["action", "created_at"],
    )
    op.create_index(
        "idx_admin_audit_log_actor_time",
        "admin_audit_log",
        ["actor_admin_user_id", "created_at"],
    )
    op.create_index(
        "idx_admin_audit_log_target_tenant",
        "admin_audit_log",
        ["target_tenant_id", "created_at"],
        postgresql_where=sa.text("target_tenant_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_admin_audit_log_target_tenant", table_name="admin_audit_log")
    op.drop_index("idx_admin_audit_log_actor_time", table_name="admin_audit_log")
    op.drop_index("idx_admin_audit_log_action_time", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")

    op.drop_index("idx_admin_login_attempts_ip_time", table_name="admin_login_attempts")
    op.drop_index("idx_admin_login_attempts_email_time", table_name="admin_login_attempts")
    op.drop_table("admin_login_attempts")

    op.drop_index("idx_admin_sessions_user_active", table_name="admin_sessions")
    op.drop_table("admin_sessions")

    op.drop_table("admin_users")

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Integration tests for the production cron CLI commands.

These two commands silently mutate live customer data:

  * ``engramia cleanup unverified-users`` — sends 7-day reminder emails and
    hard-deletes pending accounts after 14 days. A bug in the SQL window or
    in the dry-run gate could delete real users without warning.
  * ``engramia cleanup deleted-accounts`` — completes Phase 2 of the
    self-service deletion flow by hard-deleting cloud_user + tenant rows
    soft-deleted >= ``--grace-period-days`` ago. Required by GDPR Art.17
    storage-limitation; broken cron = compliance gap.

Both run from cron once a day on the production cloud DB. They had no
test coverage. These tests run against a throwaway pgvector container
with the full migration head applied.

Run:
    pytest -m postgres tests/test_cli/test_cleanup.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

pytestmark = pytest.mark.postgres


_MIGRATIONS_DIR = str(Path(__file__).parent.parent.parent / "engramia" / "db" / "migrations")

# Tables we touch — TRUNCATEd between tests for fast isolation.
_TEST_TABLES = (
    "account_deletion_requests",
    "email_verification_tokens",
    "api_keys",
    "projects",
    "cloud_users",
    "tenants",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_url():
    """Throwaway pgvector container, full alembic head applied once."""
    try:
        from alembic import command
        from alembic.config import Config
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers / alembic not installed")

    try:
        with PostgresContainer("pgvector/pgvector:0.7.4-pg16") as pg:
            url = pg.get_connection_url()
            cfg = Config()
            cfg.set_main_option("script_location", _MIGRATIONS_DIR)
            cfg.set_main_option("sqlalchemy.url", url)
            command.upgrade(cfg, "head")
            yield url
    except Exception as exc:
        pytest.skip(f"Postgres container failed: {exc}")


@pytest.fixture
def engine(pg_url):
    from sqlalchemy import create_engine, text

    eng = create_engine(pg_url, pool_pre_ping=True)
    # Wipe tenant/user-related rows before each test for full isolation.
    with eng.begin() as conn:
        for table in _TEST_TABLES:
            try:
                conn.execute(text(f"DELETE FROM {table}"))
            except Exception:
                pass  # table may not exist if a future migration removes it
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def cli_env(pg_url, monkeypatch, capsys):
    """Wire up CLI for a clean run — DB url, captured emails, console reset."""
    sent_emails: list[dict] = []

    def fake_send_email(to, subject, html, text=None):
        sent_emails.append({"to": to, "subject": subject, "html": html, "text": text})

    # The cleanup command imports send_email and reminder_email lazily inside
    # the function body, so the patch target is the source module.
    monkeypatch.setattr("engramia.email.send_email", fake_send_email)
    # Token issuance hits the DB; pass it through. _dashboard_url just reads
    # an env var so we'll pin it for predictable URLs in assertions.
    monkeypatch.setenv("ENGRAMIA_DASHBOARD_URL", "https://dashboard.test")
    monkeypatch.setenv("ENGRAMIA_DATABASE_URL", pg_url)

    return sent_emails


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_tenant(engine, tenant_id: str = "t-pending-1") -> str:
    """Minimal tenants row — `cloud_users.tenant_id` FK requires it.

    `tenants.name` is NOT NULL in the real schema (migration 003), so we
    pass a derivable label here even though the cleanup commands never
    read it.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenants (id, name) VALUES (:tid, :name) "
                "ON CONFLICT DO NOTHING"
            ),
            {"tid": tenant_id, "name": tenant_id},
        )
    return tenant_id


def _insert_pending_user(
    engine,
    *,
    email: str,
    created_days_ago: float,
    tenant_id: str | None = None,
    reminder_sent: bool = False,
    provider: str = "credentials",
    verified: bool = False,
) -> tuple[str, str]:
    """Insert a cloud_user with controllable created_at / reminder_sent_at."""
    from sqlalchemy import text

    tid = tenant_id or _insert_tenant(engine, f"t-{email.split('@')[0]}")
    if tenant_id:
        _insert_tenant(engine, tenant_id)

    created_at = datetime.now(tz=timezone.utc) - timedelta(days=created_days_ago)
    reminder_at = created_at + timedelta(hours=1) if reminder_sent else None

    with engine.begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO cloud_users "
                "(email, password_hash, tenant_id, name, provider, "
                " email_verified, created_at, reminder_sent_at) "
                "VALUES (:email, :pwd, :tid, :name, :prov, :v, :ca, :ra) "
                "RETURNING id"
            ),
            {
                "email": email,
                "pwd": "x" * 60,
                "tid": tid,
                "name": email.split("@")[0],
                "prov": provider,
                "v": verified,
                "ca": created_at,
                "ra": reminder_at,
            },
        )
        user_id = str(result.scalar())
    return user_id, tid


def _insert_soft_deleted_user(
    engine,
    *,
    email: str,
    deleted_days_ago: float,
    tenant_id: str | None = None,
) -> tuple[str, str]:
    """Insert a cloud_user that has been soft-deleted by /v1/me DELETE."""
    from sqlalchemy import text

    tid = tenant_id or _insert_tenant(engine, f"t-{email.split('@')[0]}")
    if tenant_id:
        _insert_tenant(engine, tenant_id)

    deleted_at = datetime.now(tz=timezone.utc) - timedelta(days=deleted_days_ago)
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO cloud_users "
                "(email, password_hash, tenant_id, name, provider, "
                " email_verified, deleted_at) "
                "VALUES (:email, :pwd, :tid, :name, 'credentials', true, :da) "
                "RETURNING id"
            ),
            {
                "email": email,
                "pwd": "x" * 60,
                "tid": tid,
                "name": email.split("@")[0],
                "da": deleted_at,
            },
        )
        user_id = str(result.scalar())
    return user_id, tid


def _user_exists(engine, user_id: str) -> bool:
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM cloud_users WHERE id = :uid"), {"uid": user_id}
        ).first()
    return row is not None


def _tenant_exists(engine, tenant_id: str) -> bool:
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM tenants WHERE id = :tid"), {"tid": tenant_id}
        ).first()
    return row is not None


def _reminder_sent_at(engine, user_id: str):
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT reminder_sent_at FROM cloud_users WHERE id = :uid"),
            {"uid": user_id},
        ).first()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# cleanup unverified-users
# ---------------------------------------------------------------------------


class TestCleanupUnverifiedUsersFlagValidation:
    """Pre-flight checks that don't touch the DB."""

    def test_missing_database_url_exits_1(self, monkeypatch, runner):
        from engramia.cli.main import app

        monkeypatch.delenv("ENGRAMIA_DATABASE_URL", raising=False)
        result = runner.invoke(app, ["cleanup", "unverified-users"])
        assert result.exit_code == 1
        assert "ENGRAMIA_DATABASE_URL not set" in result.output

    def test_delete_window_must_exceed_reminder_window(self, cli_env, runner):
        """A misconfigured cron (-d <= -r) would delete users before reminding."""
        from engramia.cli.main import app

        result = runner.invoke(
            app,
            ["cleanup", "unverified-users", "--reminder-after-days", "10", "--delete-after-days", "10"],
        )
        assert result.exit_code == 1
        assert "must be greater than" in result.output

    def test_delete_window_equal_reminder_window_rejected(self, cli_env, runner):
        from engramia.cli.main import app

        result = runner.invoke(
            app,
            ["cleanup", "unverified-users", "--reminder-after-days", "14", "--delete-after-days", "7"],
        )
        assert result.exit_code == 1


class TestCleanupUnverifiedUsersReminderStage:
    def test_user_in_reminder_window_gets_email_and_stamp(self, engine, cli_env, runner):
        from engramia.cli.main import app

        user_id, _ = _insert_pending_user(engine, email="reminder@e.cz", created_days_ago=8)

        result = runner.invoke(app, ["cleanup", "unverified-users"])
        assert result.exit_code == 0, result.output
        sent = cli_env
        assert len(sent) == 1, f"expected one email, got {sent}"
        assert sent[0]["to"] == "reminder@e.cz"
        # The stamp prevents duplicate reminders on the next run.
        assert _reminder_sent_at(engine, user_id) is not None

    def test_user_below_reminder_window_skipped(self, engine, cli_env, runner):
        """6-day-old account is too fresh — no reminder yet."""
        from engramia.cli.main import app

        _insert_pending_user(engine, email="too-fresh@e.cz", created_days_ago=6)

        result = runner.invoke(app, ["cleanup", "unverified-users"])
        assert result.exit_code == 0
        assert cli_env == []

    def test_user_already_reminded_not_emailed_again(self, engine, cli_env, runner):
        """`reminder_sent_at IS NULL` guards against duplicate emails."""
        from engramia.cli.main import app

        user_id, _ = _insert_pending_user(
            engine,
            email="already-reminded@e.cz",
            created_days_ago=10,
            reminder_sent=True,
        )
        old_stamp = _reminder_sent_at(engine, user_id)

        result = runner.invoke(app, ["cleanup", "unverified-users"])
        assert result.exit_code == 0
        assert cli_env == []
        # Stamp not overwritten.
        assert _reminder_sent_at(engine, user_id) == old_stamp

    def test_oauth_provider_user_skipped(self, engine, cli_env, runner):
        """`provider = 'credentials'` filter excludes OAuth users."""
        from engramia.cli.main import app

        _insert_pending_user(
            engine, email="google@e.cz", created_days_ago=10, provider="google"
        )

        result = runner.invoke(app, ["cleanup", "unverified-users"])
        assert result.exit_code == 0
        assert cli_env == []

    def test_verified_user_skipped(self, engine, cli_env, runner):
        from engramia.cli.main import app

        _insert_pending_user(
            engine, email="verified@e.cz", created_days_ago=10, verified=True
        )

        result = runner.invoke(app, ["cleanup", "unverified-users"])
        assert result.exit_code == 0
        assert cli_env == []


class TestCleanupUnverifiedUsersDeleteStage:
    def test_user_past_delete_window_is_hard_deleted(self, engine, cli_env, runner):
        from engramia.cli.main import app

        user_id, tid = _insert_pending_user(engine, email="goner@e.cz", created_days_ago=15)
        assert _user_exists(engine, user_id)

        result = runner.invoke(app, ["cleanup", "unverified-users"])
        assert result.exit_code == 0
        assert not _user_exists(engine, user_id)
        # Tenant cascaded.
        assert not _tenant_exists(engine, tid)

    def test_user_inside_delete_window_kept(self, engine, cli_env, runner):
        from engramia.cli.main import app

        user_id, _ = _insert_pending_user(engine, email="safe@e.cz", created_days_ago=10)

        result = runner.invoke(app, ["cleanup", "unverified-users"])
        assert result.exit_code == 0
        assert _user_exists(engine, user_id)

    def test_verified_user_past_delete_window_kept(self, engine, cli_env, runner):
        """email_verified=true is the hard guard — must never delete a verified user."""
        from engramia.cli.main import app

        user_id, _ = _insert_pending_user(
            engine, email="verified-old@e.cz", created_days_ago=30, verified=True
        )

        result = runner.invoke(app, ["cleanup", "unverified-users"])
        assert result.exit_code == 0
        assert _user_exists(engine, user_id)

    def test_oauth_user_past_delete_window_kept(self, engine, cli_env, runner):
        from engramia.cli.main import app

        user_id, _ = _insert_pending_user(
            engine, email="oauth-old@e.cz", created_days_ago=30, provider="google"
        )

        result = runner.invoke(app, ["cleanup", "unverified-users"])
        assert result.exit_code == 0
        assert _user_exists(engine, user_id)


class TestCleanupUnverifiedUsersDryRun:
    def test_dry_run_is_a_true_noop(self, engine, cli_env, runner):
        from engramia.cli.main import app

        # One in reminder window, one in delete window.
        rem_id, _ = _insert_pending_user(engine, email="rem@e.cz", created_days_ago=8)
        del_id, del_tid = _insert_pending_user(engine, email="del@e.cz", created_days_ago=20)

        result = runner.invoke(app, ["cleanup", "unverified-users", "--dry-run"])
        assert result.exit_code == 0
        # No email sent.
        assert cli_env == []
        # No reminder stamp written.
        assert _reminder_sent_at(engine, rem_id) is None
        # No deletion.
        assert _user_exists(engine, del_id)
        assert _tenant_exists(engine, del_tid)
        # But the output should mention both candidates so the operator can review.
        assert "rem@e.cz" in result.output
        assert "del@e.cz" in result.output


class TestCleanupUnverifiedUsersIdempotent:
    def test_running_twice_does_not_re_email_or_re_delete(self, engine, cli_env, runner):
        from engramia.cli.main import app

        _insert_pending_user(engine, email="rem@e.cz", created_days_ago=8)
        _insert_pending_user(engine, email="del@e.cz", created_days_ago=20)

        # First run.
        result = runner.invoke(app, ["cleanup", "unverified-users"])
        assert result.exit_code == 0
        first_emails = list(cli_env)
        assert len(first_emails) == 1

        # Second run — reminder already stamped, deletion already happened.
        result = runner.invoke(app, ["cleanup", "unverified-users"])
        assert result.exit_code == 0
        # No new emails.
        assert cli_env == first_emails


# ---------------------------------------------------------------------------
# cleanup deleted-accounts
# ---------------------------------------------------------------------------


class TestCleanupDeletedAccounts:
    def test_missing_database_url_exits_1(self, monkeypatch, runner):
        from engramia.cli.main import app

        monkeypatch.delenv("ENGRAMIA_DATABASE_URL", raising=False)
        result = runner.invoke(app, ["cleanup", "deleted-accounts"])
        assert result.exit_code == 1
        assert "ENGRAMIA_DATABASE_URL not set" in result.output

    def test_no_soft_deleted_users_exits_clean(self, engine, cli_env, runner):
        from engramia.cli.main import app

        result = runner.invoke(app, ["cleanup", "deleted-accounts"])
        assert result.exit_code == 0
        assert "Nothing to clean up" in result.output

    def test_user_past_grace_period_is_hard_deleted(self, engine, cli_env, runner):
        from engramia.cli.main import app

        user_id, tid = _insert_soft_deleted_user(
            engine, email="grace-over@e.cz", deleted_days_ago=31
        )
        assert _user_exists(engine, user_id)

        result = runner.invoke(app, ["cleanup", "deleted-accounts"])
        assert result.exit_code == 0
        assert not _user_exists(engine, user_id)
        assert not _tenant_exists(engine, tid)

    def test_user_inside_grace_period_kept(self, engine, cli_env, runner):
        """29-day-old soft-delete is still inside the 30-day default window."""
        from engramia.cli.main import app

        user_id, _ = _insert_soft_deleted_user(
            engine, email="grace-active@e.cz", deleted_days_ago=29
        )

        result = runner.invoke(app, ["cleanup", "deleted-accounts"])
        assert result.exit_code == 0
        assert _user_exists(engine, user_id)

    def test_active_user_never_touched(self, engine, cli_env, runner):
        """The whole filter is `deleted_at IS NOT NULL` — active users untouched."""
        from engramia.cli.main import app

        user_id, _ = _insert_pending_user(engine, email="active@e.cz", created_days_ago=2)

        result = runner.invoke(app, ["cleanup", "deleted-accounts"])
        assert result.exit_code == 0
        assert _user_exists(engine, user_id)

    def test_dry_run_keeps_user(self, engine, cli_env, runner):
        from engramia.cli.main import app

        user_id, tid = _insert_soft_deleted_user(
            engine, email="grace-over@e.cz", deleted_days_ago=45
        )

        result = runner.invoke(
            app, ["cleanup", "deleted-accounts", "--dry-run"]
        )
        assert result.exit_code == 0
        assert _user_exists(engine, user_id)
        assert _tenant_exists(engine, tid)
        assert "grace-over@e.cz" in result.output or user_id in result.output

    def test_custom_grace_period(self, engine, cli_env, runner):
        """--grace-period-days 7 catches a user soft-deleted 10 days ago."""
        from engramia.cli.main import app

        user_id, _ = _insert_soft_deleted_user(
            engine, email="short-grace@e.cz", deleted_days_ago=10
        )

        result = runner.invoke(
            app, ["cleanup", "deleted-accounts", "--grace-period-days", "7"]
        )
        assert result.exit_code == 0
        assert not _user_exists(engine, user_id)

    def test_idempotent_on_repeat_run(self, engine, cli_env, runner):
        from engramia.cli.main import app

        _insert_soft_deleted_user(engine, email="gone@e.cz", deleted_days_ago=60)

        runner.invoke(app, ["cleanup", "deleted-accounts"])
        # Second run — nothing to do, no error.
        result = runner.invoke(app, ["cleanup", "deleted-accounts"])
        assert result.exit_code == 0
        assert "Nothing to clean up" in result.output

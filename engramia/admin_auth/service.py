# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""High-level orchestrator for admin login + TOTP + sessions.

Splits the auth flow into two service methods so the FastAPI router can
keep its handlers thin:

  * :meth:`AdminAuthService.attempt_login` — verify password, return an
    :class:`LoginOutcome` describing what the client should do next
    (TOTP code expected, with intermediate token).

  * :meth:`AdminAuthService.attempt_totp` — verify TOTP, mint the access
    token + refresh token + session row.

Lockout policy: 5 failed password OR TOTP attempts in 15 min for a given
email → ``status='locked'``. Unlock via the CLI break-glass
``engramia admin reset-totp`` (or directly UPDATE
``admin_users SET status='active'`` for password lockout). The 15 min
window is a sliding aggregate over ``admin_login_attempts``.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import text
from sqlalchemy.engine import Engine

from engramia.admin_auth.passwords import verify_password
from engramia.admin_auth.tokens import (
    issue_admin_token,
    issue_intermediate_token,
)
from engramia.admin_auth.totp import decrypt_totp_secret, verify_totp_code

_log = logging.getLogger(__name__)

_LOCKOUT_THRESHOLD = 5
_LOCKOUT_WINDOW_MINUTES = 15
_REFRESH_TOKEN_TTL_DAYS = 1


@dataclass(frozen=True)
class LoginOutcome:
    """Result of the password step."""

    kind: Literal["totp_required", "invalid_credentials", "locked", "totp_not_enrolled"]
    intermediate_token: str | None = None
    # Only populated on ``invalid_credentials`` / ``locked`` so the router
    # can return a precise WWW-Authenticate-style error code.
    detail: str | None = None


@dataclass(frozen=True)
class TotpOutcome:
    """Result of the TOTP step."""

    kind: Literal["ok", "invalid_token", "invalid_code", "locked"]
    admin_jwt: str | None = None
    refresh_token: str | None = None
    expires_at: datetime | None = None
    totp_issued_at: int | None = None
    admin_user_id: int | None = None
    session_id: str | None = None
    detail: str | None = None


def _hash_refresh_token(token: str) -> str:
    """SHA-256 hex of an opaque refresh token. Plain SHA is fine — entropy lives in the token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AdminAuthService:
    """Orchestrates the password + TOTP flow against the admin tables."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Login attempt logging
    # ------------------------------------------------------------------

    def _log_attempt(
        self,
        *,
        email: str,
        ip: str,
        success: bool,
        stage: Literal["password", "totp"],
        failure_reason: str | None = None,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO admin_login_attempts "
                    "(email, ip_address, success, stage, failure_reason) "
                    "VALUES (:email, :ip, :ok, :stage, :reason)"
                ),
                {
                    "email": email.lower(),
                    "ip": ip,
                    "ok": success,
                    "stage": stage,
                    "reason": failure_reason,
                },
            )

    def _is_locked_out(self, email: str) -> bool:
        """Slide a 15-min window over recent failures for *email*."""
        cutoff = datetime.now(UTC) - timedelta(minutes=_LOCKOUT_WINDOW_MINUTES)
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT COUNT(*) FROM admin_login_attempts "
                    "WHERE email = :email AND success = false "
                    "  AND attempted_at >= :cutoff"
                ),
                {"email": email.lower(), "cutoff": cutoff},
            ).scalar_one()
        return int(row or 0) >= _LOCKOUT_THRESHOLD

    # ------------------------------------------------------------------
    # Step 1 — password
    # ------------------------------------------------------------------

    def attempt_login(self, *, email: str, password: str, ip: str) -> LoginOutcome:
        normalized = email.strip().lower()

        if self._is_locked_out(normalized):
            self._log_attempt(
                email=normalized, ip=ip, success=False,
                stage="password", failure_reason="locked",
            )
            return LoginOutcome(
                kind="locked",
                detail=(
                    "Too many failed attempts in the last "
                    f"{_LOCKOUT_WINDOW_MINUTES} minutes. Try again later or "
                    "run `engramia admin reset-totp` from the server."
                ),
            )

        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT id, password_hash, totp_enrolled, status "
                    "FROM admin_users WHERE email = :email"
                ),
                {"email": normalized},
            ).first()

        if row is None:
            self._log_attempt(
                email=normalized, ip=ip, success=False,
                stage="password", failure_reason="unknown_email",
            )
            return LoginOutcome(kind="invalid_credentials")

        admin_user_id, password_hash, totp_enrolled, status = row

        if status != "active":
            self._log_attempt(
                email=normalized, ip=ip, success=False,
                stage="password", failure_reason=f"status_{status}",
            )
            return LoginOutcome(kind="locked", detail=f"Account status: {status}")

        if not verify_password(password, password_hash):
            self._log_attempt(
                email=normalized, ip=ip, success=False,
                stage="password", failure_reason="bad_password",
            )
            return LoginOutcome(kind="invalid_credentials")

        if not totp_enrolled:
            # Password is right but TOTP enrollment never completed. Surface
            # a distinct error rather than silently allowing entry — the
            # bootstrap procedure must finish before login is possible.
            self._log_attempt(
                email=normalized, ip=ip, success=False,
                stage="password", failure_reason="totp_not_enrolled",
            )
            return LoginOutcome(
                kind="totp_not_enrolled",
                detail="Run `engramia admin bootstrap` to complete TOTP enrollment.",
            )

        self._log_attempt(email=normalized, ip=ip, success=True, stage="password")
        return LoginOutcome(
            kind="totp_required",
            intermediate_token=issue_intermediate_token(admin_user_id=admin_user_id),
        )

    # ------------------------------------------------------------------
    # Step 2 — TOTP
    # ------------------------------------------------------------------

    def attempt_totp(
        self,
        *,
        admin_user_id: int,
        code: str,
        ip: str,
        user_agent: str | None,
    ) -> TotpOutcome:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT email, totp_secret_ciphertext, totp_enrolled, status "
                    "FROM admin_users WHERE id = :id"
                ),
                {"id": admin_user_id},
            ).first()

        if row is None:
            return TotpOutcome(kind="invalid_token", detail="Unknown admin")
        email, encrypted_secret, totp_enrolled, status = row

        if status != "active":
            return TotpOutcome(kind="locked", detail=f"Account status: {status}")

        if self._is_locked_out(email):
            self._log_attempt(
                email=email, ip=ip, success=False,
                stage="totp", failure_reason="locked",
            )
            return TotpOutcome(kind="locked")

        if not totp_enrolled or not encrypted_secret:
            self._log_attempt(
                email=email, ip=ip, success=False,
                stage="totp", failure_reason="totp_not_enrolled",
            )
            return TotpOutcome(kind="invalid_token", detail="TOTP not enrolled")

        secret = decrypt_totp_secret(encrypted_secret, admin_user_id)
        if not verify_totp_code(secret, code):
            self._log_attempt(
                email=email, ip=ip, success=False,
                stage="totp", failure_reason="bad_totp",
            )
            return TotpOutcome(kind="invalid_code")

        # TOTP verified — mint a session.
        now = datetime.now(UTC)
        totp_issued_at_unix = int(now.timestamp())
        session_id = uuid.uuid4().hex
        refresh_token = secrets.token_urlsafe(48)
        expires_at = now + timedelta(days=_REFRESH_TOKEN_TTL_DAYS)

        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO admin_sessions "
                    "(id, admin_user_id, refresh_token_hash, issued_at, expires_at, "
                    " totp_issued_at, user_agent, ip_address) "
                    "VALUES (:id, :uid, :rth, :iat, :exp, :tia, :ua, :ip)"
                ),
                {
                    "id": session_id,
                    "uid": admin_user_id,
                    "rth": _hash_refresh_token(refresh_token),
                    "iat": now,
                    "exp": expires_at,
                    "tia": now,
                    "ua": user_agent,
                    "ip": ip,
                },
            )
            conn.execute(
                text(
                    "UPDATE admin_users SET last_login_at = :ts, last_login_ip = :ip "
                    "WHERE id = :id"
                ),
                {"ts": now, "ip": ip, "id": admin_user_id},
            )

        self._log_attempt(email=email, ip=ip, success=True, stage="totp")

        admin_jwt = issue_admin_token(
            admin_user_id=admin_user_id,
            session_id=session_id,
            totp_issued_at=totp_issued_at_unix,
        )
        return TotpOutcome(
            kind="ok",
            admin_jwt=admin_jwt,
            refresh_token=refresh_token,
            expires_at=expires_at,
            totp_issued_at=totp_issued_at_unix,
            admin_user_id=admin_user_id,
            session_id=session_id,
        )

    # ------------------------------------------------------------------
    # TOTP re-prompt (for fresh-TOTP gating on destructive actions)
    # ------------------------------------------------------------------

    def reauth_totp(
        self,
        *,
        admin_user_id: int,
        session_id: str,
        code: str,
        ip: str,
    ) -> TotpOutcome:
        """Verify TOTP again without minting a new session.

        Advances ``admin_sessions.totp_issued_at`` so the next admin token
        we mint via refresh carries an up-to-date freshness anchor; the
        currently-held token is *not* re-issued (the client keeps using
        it for the remainder of its 15-min TTL — the gate dependency
        re-reads ``totp_issued_at`` from the session row, not the token).
        """
        outcome = self.attempt_totp(
            admin_user_id=admin_user_id, code=code, ip=ip, user_agent=None,
        )
        if outcome.kind != "ok":
            return outcome
        # ``attempt_totp`` already inserted a fresh session row — that's
        # wrong for reauth, undo it. Cleaner alternative would be a
        # dedicated path, but this keeps lockout/logging in one place.
        with self._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM admin_sessions WHERE id = :id"),
                {"id": outcome.session_id},
            )
            conn.execute(
                text(
                    "UPDATE admin_sessions SET totp_issued_at = :ts "
                    "WHERE id = :sid AND revoked_at IS NULL"
                ),
                {"ts": datetime.now(UTC), "sid": session_id},
            )
        return TotpOutcome(
            kind="ok",
            totp_issued_at=outcome.totp_issued_at,
            admin_user_id=admin_user_id,
            session_id=session_id,
        )

    # ------------------------------------------------------------------
    # Refresh + logout
    # ------------------------------------------------------------------

    def refresh(self, *, refresh_token: str, ip: str) -> TotpOutcome:
        """Rotate the refresh token and mint a new admin access token.

        One-time-use semantics: the old refresh row is revoked atomically
        with issuing the new one; replay attempts hit a revoked row.
        """
        rth = _hash_refresh_token(refresh_token)
        now = datetime.now(UTC)

        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT id, admin_user_id, expires_at, revoked_at, totp_issued_at "
                    "FROM admin_sessions WHERE refresh_token_hash = :rth"
                ),
                {"rth": rth},
            ).first()

            if row is None:
                return TotpOutcome(kind="invalid_token", detail="Unknown refresh token")

            session_id, admin_user_id, expires_at, revoked_at, totp_issued_at = row
            if revoked_at is not None:
                # Replay attempt — revoke ALL sessions for this admin to
                # contain the blast radius. The user has to log in again.
                conn.execute(
                    text(
                        "UPDATE admin_sessions SET revoked_at = :ts "
                        "WHERE admin_user_id = :uid AND revoked_at IS NULL"
                    ),
                    {"ts": now, "uid": admin_user_id},
                )
                _log.warning(
                    "Admin refresh token replay detected (admin_user_id=%s); "
                    "all sessions revoked.",
                    admin_user_id,
                )
                return TotpOutcome(kind="invalid_token", detail="Refresh token replay")

            if expires_at < now:
                return TotpOutcome(kind="invalid_token", detail="Refresh token expired")

            # Rotate.
            new_session_id = uuid.uuid4().hex
            new_refresh = secrets.token_urlsafe(48)
            new_expires = now + timedelta(days=_REFRESH_TOKEN_TTL_DAYS)

            conn.execute(
                text("UPDATE admin_sessions SET revoked_at = :ts WHERE id = :id"),
                {"ts": now, "id": session_id},
            )
            conn.execute(
                text(
                    "INSERT INTO admin_sessions "
                    "(id, admin_user_id, refresh_token_hash, issued_at, expires_at, "
                    " totp_issued_at, ip_address) "
                    "VALUES (:id, :uid, :rth, :iat, :exp, :tia, :ip)"
                ),
                {
                    "id": new_session_id,
                    "uid": admin_user_id,
                    "rth": _hash_refresh_token(new_refresh),
                    "iat": now,
                    # Re-using the previous totp_issued_at: refresh does not
                    # re-establish freshness, only attempt_totp / reauth_totp
                    # advance it. Destructive gates therefore expire on the
                    # original 5-minute clock regardless of how many refreshes
                    # the user does.
                    "exp": new_expires,
                    "tia": totp_issued_at,
                    "ip": ip,
                },
            )

        admin_jwt = issue_admin_token(
            admin_user_id=admin_user_id,
            session_id=new_session_id,
            totp_issued_at=int(totp_issued_at.timestamp()),
        )
        return TotpOutcome(
            kind="ok",
            admin_jwt=admin_jwt,
            refresh_token=new_refresh,
            expires_at=new_expires,
            totp_issued_at=int(totp_issued_at.timestamp()),
            admin_user_id=admin_user_id,
            session_id=new_session_id,
        )

    def logout(self, *, session_id: str) -> None:
        """Revoke a session row. Idempotent — already-revoked rows are no-ops."""
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE admin_sessions SET revoked_at = now() "
                    "WHERE id = :id AND revoked_at IS NULL"
                ),
                {"id": session_id},
            )

    # ------------------------------------------------------------------
    # Session lookup (used by the FastAPI dependency to verify the
    # session is still active and read totp_issued_at fresh from the DB)
    # ------------------------------------------------------------------

    def session_freshness(self, *, session_id: str) -> datetime | None:
        """Return ``totp_issued_at`` for an active session, or None if revoked/missing."""
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT totp_issued_at FROM admin_sessions "
                    "WHERE id = :id AND revoked_at IS NULL "
                    "  AND expires_at > now()"
                ),
                {"id": session_id},
            ).first()
        return row[0] if row else None

    # ------------------------------------------------------------------
    # Bootstrap helper (used by the CLI; not exposed via REST)
    # ------------------------------------------------------------------

    def get_admin_user(self, *, email: str) -> dict | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT id, email, totp_enrolled, status, created_at "
                    "FROM admin_users WHERE email = :email"
                ),
                {"email": email.strip().lower()},
            ).first()
        if not row:
            return None
        return {
            "id": row[0],
            "email": row[1],
            "totp_enrolled": row[2],
            "status": row[3],
            "created_at": row[4],
        }


__all__ = ["AdminAuthService", "LoginOutcome", "TotpOutcome"]

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Admin Dashboard authentication subsystem.

Backs the operator/super-admin Admin Dashboard (``Admin/`` repo). Distinct
from ``engramia.api.cloud_auth`` (tenant-facing) on three axes:

  * Separate users table (``admin_users``) — admin identity is decoupled
    from tenant identity. The same email could in principle exist as both
    a tenant user and a super-admin without collision.
  * Separate JWT signing key (``ENGRAMIA_ADMIN_JWT_SECRET``) and issuer
    (``engramia-admin``). A tenant token cannot pass admin authentication
    even if the dispatch logic mis-routes — the issuer claim mismatches
    deterministically. Cf. ARCHITECTURE.md ADR-007.
  * TOTP-mandatory at every login. No password-only path. Destructive
    routes additionally require ``require_fresh_totp(window=300)``.

Public surface (re-exported from this package):

    AdminAuthService — high-level facade for the login + TOTP + session
                        + audit lockout flow. Wired into the FastAPI router
                        in ``engramia.api.admin.auth``.
    issue_admin_token / verify_admin_token — JWT helpers (separate secret
                        and issuer from the cloud-tenant pair in
                        ``engramia.api.cloud_auth``).
    hash_password / verify_password — bcrypt wrappers.
    enroll_totp / verify_totp_code — pyotp wrappers + secret encryption.

Tables (Alembic 032): ``admin_users``, ``admin_sessions``,
``admin_login_attempts``, ``admin_audit_log``.
"""

from engramia.admin_auth.passwords import hash_password, verify_password
from engramia.admin_auth.service import AdminAuthService, LoginOutcome, TotpOutcome
from engramia.admin_auth.tokens import (
    ADMIN_JWT_ISSUER,
    AdminTokenClaims,
    issue_admin_token,
    issue_intermediate_token,
    verify_admin_token,
    verify_intermediate_token,
)
from engramia.admin_auth.totp import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_totp_secret,
    provisioning_uri,
    qr_png_bytes,
    verify_totp_code,
)

__all__ = [
    "ADMIN_JWT_ISSUER",
    "AdminAuthService",
    "AdminTokenClaims",
    "LoginOutcome",
    "TotpOutcome",
    "decrypt_totp_secret",
    "encrypt_totp_secret",
    "generate_totp_secret",
    "hash_password",
    "issue_admin_token",
    "issue_intermediate_token",
    "provisioning_uri",
    "qr_png_bytes",
    "verify_admin_token",
    "verify_intermediate_token",
    "verify_password",
    "verify_totp_code",
]

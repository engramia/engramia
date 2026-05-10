# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Admin Dashboard REST surface.

Mounted at ``/v1/admin/*`` by ``engramia.api.app._register_routers``.

Auth-only in this initial drop (Phase 1 step 1):
  * ``/v1/admin/auth/login``      — password step → intermediate token
  * ``/v1/admin/auth/totp``       — TOTP step → admin JWT + refresh token
  * ``/v1/admin/auth/refresh``    — rotate refresh token
  * ``/v1/admin/auth/logout``     — revoke session
  * ``/v1/admin/auth/totp/reauth``— bump ``totp_issued_at`` for destructive gates
  * ``/v1/admin/auth/me``         — return the current admin's profile

Domain endpoints (users, pilots, billing, governance, credentials, ops,
audit) land in subsequent commits per the phasing in
``Admin/ARCHITECTURE.md`` § 15.
"""

from engramia.api.admin.auth import router

__all__ = ["router"]

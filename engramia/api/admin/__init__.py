# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Admin Dashboard REST surface — composed from per-domain sub-routers.

Mounted at ``/v1/admin/*`` by ``engramia.api.app._register_routers``.

Each sub-router declares its own ``/admin/<domain>`` prefix internally so
this module is just a thin top-level composer. Adding a new admin domain
(billing, governance, credentials, …) is one new ``router.include_router()``
call here.

Phase 1 (current) — auth, users, pilots, audit viewer, overview.
Phase 2 (planned) — billing, ops/cleanup.
Phase 3 (planned) — governance, credentials, observability.
"""

from fastapi import APIRouter

from engramia.api.admin.audit_viewer import router as audit_router
from engramia.api.admin.auth import router as auth_router
from engramia.api.admin.overview import router as overview_router
from engramia.api.admin.pilots import router as pilots_router
from engramia.api.admin.users import router as users_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(overview_router)
router.include_router(users_router)
router.include_router(pilots_router)
router.include_router(audit_router)

__all__ = ["router"]

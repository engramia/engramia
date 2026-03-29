# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""RBAC permission system for the Engramia API.

Four roles form a strict superset hierarchy:

    reader  ⊂  editor  ⊂  admin  ⊂  owner

Each role is granted an explicit set of permission strings that map 1-to-1
with API operations. ``require_permission(perm)`` returns a FastAPI dependency
that enforces the check before the route handler runs.

When ``request.state.auth_context`` is absent (env-var auth mode or dev mode),
no RBAC check is performed — all operations are permitted for backward
compatibility with single-key deployments.

Permission strings mirror route semantics exactly so that audit logs and error
messages are human-readable without a lookup table.
"""

from fastapi import Depends, HTTPException, Request, status

# ---------------------------------------------------------------------------
# Permission definitions
# ---------------------------------------------------------------------------

_READER_PERMS: frozenset[str] = frozenset(
    {
        "health",
        "metrics",
        "recall",
        "feedback:read",
        "skills:search",
        "jobs:list",
        "jobs:read",
    }
)

_EDITOR_PERMS: frozenset[str] = _READER_PERMS | frozenset(
    {
        "learn",
        "evaluate",
        "compose",
        "evolve",
        "analyze_failures",
        "skills:register",
        "aging",
        "feedback:decay",
        "jobs:cancel",
    }
)

_ADMIN_PERMS: frozenset[str] = _EDITOR_PERMS | frozenset(
    {
        "patterns:delete",
        "import",
        "export",
        "keys:create",
        "keys:list",
        "keys:revoke",
        "keys:rotate",
        # Phase 5.6: Data Governance
        "governance:read",
        "governance:write",
        "governance:admin",
        "governance:delete",
    }
)

# Owner has a wildcard — all current and future permissions.
_OWNER_PERMS: frozenset[str] = frozenset({"*"})

PERMISSIONS: dict[str, frozenset[str]] = {
    "reader": _READER_PERMS,
    "editor": _EDITOR_PERMS,
    "admin": _ADMIN_PERMS,
    "owner": _OWNER_PERMS,
}


# ---------------------------------------------------------------------------
# Dependency factory
# ---------------------------------------------------------------------------


def require_permission(perm: str):
    """Return a FastAPI dependency that enforces *perm* for DB-auth requests.

    No-op when ``request.state.auth_context`` is absent (env-var / dev mode).

    Args:
        perm: Permission string, e.g. ``'learn'``, ``'patterns:delete'``.

    Raises:
        HTTPException 403: If the authenticated role lacks the permission.
    """

    def _check(request: Request) -> None:
        ctx = getattr(request.state, "auth_context", None)
        if ctx is None:
            return  # env-var or dev mode — no RBAC enforcement
        role_perms = PERMISSIONS.get(ctx.role, frozenset())
        if "*" not in role_perms and perm not in role_perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{ctx.role}' does not have permission '{perm}'.",
            )

    return Depends(_check)

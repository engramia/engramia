# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Shared test factories for auth contexts, scopes, and app wiring.

Provides a single source of truth for constructing AuthContext, Scope,
and FastAPI dependency overrides across all test suites.  Every test file
that needs an auth context should import from here instead of building
its own ad-hoc helper.

Usage::

    from tests.factories import make_auth_ctx, make_auth_dep

    ctx = make_auth_ctx(role="admin", tenant_id="acme")
    dep = make_auth_dep(role="reader")
"""

from __future__ import annotations

from fastapi import Request

from engramia._context import set_scope
from engramia.types import AuthContext, Scope

# ---------------------------------------------------------------------------
# Auth context factory
# ---------------------------------------------------------------------------


def make_auth_ctx(
    role: str = "owner",
    tenant_id: str = "default",
    project_id: str = "default",
    key_id: str = "test-key-001",
    plan_tier: str = "developer",
    max_patterns: int | None = None,
) -> AuthContext:
    """Build an AuthContext with sensible defaults for tests.

    Default role is ``owner`` — the most permissive — so that tests which
    don't care about RBAC aren't blocked.  Tests that *do* care should
    pass the specific role they want to exercise.

    Default scope is ``default/default`` — matching the env-var auth mode
    and the ``mem`` fixture which stores patterns without explicit scope.
    Tests that care about multi-tenancy should pass explicit tenant/project.
    """
    return AuthContext(
        key_id=key_id,
        tenant_id=tenant_id,
        project_id=project_id,
        role=role,
        max_patterns=max_patterns,
        plan_tier=plan_tier,
        scope=Scope(tenant_id=tenant_id, project_id=project_id),
    )


# ---------------------------------------------------------------------------
# FastAPI dependency override factory
# ---------------------------------------------------------------------------


def make_auth_dep(
    role: str = "owner",
    tenant_id: str = "default",
    project_id: str = "default",
    **kwargs,
):
    """Return a ``require_auth`` override that injects a real AuthContext.

    The returned callable is **async** — matching the production
    ``require_auth`` signature.  This is critical: FastAPI dispatches sync
    route handlers to a thread pool, copying the *current* event-loop
    context.  If the dependency is sync it runs in a *different* thread-pool
    invocation whose contextvar changes are invisible to the handler.
    An async dependency runs in the event loop itself, so ``set_scope()``
    is visible when the handler thread copies the context.

    Sets both ``request.state.auth_context`` **and** the scope contextvar,
    mirroring what the production ``require_auth`` dependency does.

    Usage::

        from engramia.api.auth import require_auth
        app.dependency_overrides[require_auth] = make_auth_dep(role="reader")
    """

    async def _dep(request: Request) -> None:
        ctx = make_auth_ctx(role=role, tenant_id=tenant_id, project_id=project_id, **kwargs)
        request.state.auth_context = ctx
        set_scope(ctx.scope)

    return _dep

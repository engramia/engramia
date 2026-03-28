# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Request-scoped contextvar for tenant/project scope propagation.

The current Scope is set by the auth dependency at the start of each request
and read by storage backends to filter all queries to the correct tenant and
project — without threading the scope through every method signature.

FastAPI runs sync route handlers via anyio.to_thread.run_sync(), which copies
the active context, so contextvars set in async dependencies are visible inside
sync handlers and in the threadpool workers they invoke.

Usage (internal only — not part of the public API)::

    from engramia._context import get_scope, set_scope, reset_scope
    scope = get_scope()          # Scope(tenant_id=..., project_id=...)
    token = set_scope(new_scope) # returns a Token for cleanup
    reset_scope(token)           # restore previous scope
"""

from contextvars import ContextVar, Token

# Import deferred to avoid circular imports at module level.
# Types are resolved at call time.


def _default_scope():  # type: ignore[return]
    from engramia.types import Scope

    return Scope()


_scope_var: ContextVar = ContextVar("engramia_scope")


def get_scope():
    """Return the Scope active in the current request/task context.

    Returns the default Scope (tenant_id='default', project_id='default')
    when no scope has been set — i.e., in dev mode or env-var auth mode.
    """
    try:
        return _scope_var.get()
    except LookupError:
        return _default_scope()


def set_scope(scope) -> Token:  # type: ignore[type-arg]
    """Set the Scope for the current request/task. Returns a reset Token."""
    return _scope_var.set(scope)


def reset_scope(token: Token) -> None:
    """Restore the previous Scope using the Token returned by set_scope()."""
    _scope_var.reset(token)

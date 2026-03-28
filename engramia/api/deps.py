# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""FastAPI dependency injection for the Memory singleton and auth context.

The Memory instance is created once at app startup (in ``create_app()``)
and stored on ``app.state.memory``. Each request retrieves it via this
dependency — no per-request construction overhead.

The AuthContext is set by ``require_auth`` during the request lifecycle and
is available via ``get_auth_context`` in route handlers that need RBAC info
(e.g. for quota enforcement or audit logging).
"""

from fastapi import Request

from engramia import Memory
from engramia.types import AuthContext


def get_memory(request: Request) -> Memory:
    """Return the shared Memory instance from app state."""
    return request.app.state.memory


def get_auth_context(request: Request) -> AuthContext | None:
    """Return the current request's AuthContext, or None in env/dev auth mode.

    Present only in DB auth mode (ENGRAMIA_AUTH_MODE=db or auto with DB configured).
    Route handlers may use this to retrieve the RBAC role or quota limits.
    """
    return getattr(request.state, "auth_context", None)

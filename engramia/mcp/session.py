# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Per-MCP-session metadata held by the hosted transport.

The MCP SDK's :class:`StreamableHTTPSessionManager` already manages session
lifecycle (creation, idle timeout, cleanup) for the protocol layer. What it
does *not* know about is our policy state:

- which tenant owns this session (auth context)
- which connection-limiter slot it holds
- per-session counters for /metrics and audit

That metadata lives here. Two concrete vehicles:

1. :class:`SessionInit` — built in the FastAPI request handler before
   ``handle_request`` spawns a new ``run_server`` task. Stashed in a
   contextvar so the per-session lifespan callback can read it.

2. :func:`build_lifespan` — returns the async-context-manager callable that
   :class:`mcp.server.Server` invokes once per session. It pulls the
   :class:`SessionInit` from the contextvar at session-start time and yields
   a :class:`SessionMetadata` dict on which the tool callbacks operate. The
   ``finally`` block handles slot release and audit emission.

The handshake between request handler and lifespan is contextvar-based
because anyio task-spawning copies the parent task's contextvars at spawn
time — so a value set just before ``await self._task_group.start(run_server)``
is visible inside ``run_server`` and the lifespan it triggers.
"""

from __future__ import annotations

import contextlib
import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from engramia.mcp.tier_gate import AcquiredSlot, ConnectionLimiter
    from engramia.types import AuthContext

_log = logging.getLogger(__name__)


@dataclass
class SessionInit:
    """Initialisation payload prepared by the HTTP request handler before a
    new MCP session is spawned. Read once by the lifespan callback at
    session start, then discarded.

    Attributes:
        auth: The authenticated caller's context (tenant, project, role,
            tier, scope). Reused on every tool call within the session
            without re-authentication of the body — but the HTTP layer
            still re-validates the Bearer on every request.
        slot: The connection limiter slot acquired before spawn. Released
            on session close (graceful or idle).
        limiter: Reference to the limiter that issued the slot — used for
            release on the lifespan exit path.
        opened_at: Timestamp for audit + metrics.
    """

    auth: AuthContext
    slot: AcquiredSlot
    limiter: ConnectionLimiter
    opened_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


class SessionMetadata(TypedDict):
    """Live per-session state visible to tool callbacks via
    ``RequestContext.lifespan_context``.

    Tool callbacks (in :mod:`engramia.mcp.http_server`) read:

    - ``auth.tenant_id`` / ``auth.scope`` — to set the scope contextvar
      before invoking Memory operations.
    - ``auth.role`` — for RBAC checks via the existing PERMISSIONS dict.
    - ``auth.plan_tier`` — for tier-gate checks on individual tools.

    The dict is populated by :func:`build_lifespan` from the
    :class:`SessionInit` posted by the request handler. Mutating fields
    (counters, last activity) live here so the lifespan exit handler can
    log a final summary.
    """

    auth: AuthContext
    slot: AcquiredSlot
    opened_at: datetime
    tool_calls: int


# ---------------------------------------------------------------------------
# Contextvar handshake between FastAPI request handler and SDK lifespan.
# ---------------------------------------------------------------------------

_PENDING_SESSION_INIT: ContextVar[SessionInit | None] = ContextVar(
    "engramia_mcp_pending_session_init", default=None
)


def stash_pending_init(init: SessionInit) -> object:
    """Set the pending init for the *current* asyncio task. The MCP SDK
    spawns a child task to host the new session; that child copies our
    contextvar via anyio's standard task-spawn semantics.

    Returns:
        The contextvar token. The HTTP handler MUST call :func:`reset_pending_init`
        after ``handle_request`` returns to avoid leaking the init into
        unrelated subsequent code paths in the same task.
    """
    return _PENDING_SESSION_INIT.set(init)


def reset_pending_init(token: object) -> None:
    """Reset the contextvar set by :func:`stash_pending_init`."""
    _PENDING_SESSION_INIT.reset(token)  # type: ignore[arg-type]


def take_pending_init() -> SessionInit | None:
    """Read-and-clear the pending init. Called from inside the lifespan
    callback exactly once per new session.
    """
    init = _PENDING_SESSION_INIT.get()
    if init is not None:
        # We don't reset here — the contextvar is per-task; the request
        # handler that set it will reset on its own scope exit. Leaving the
        # value set inside the spawned task is harmless because there's
        # only ever one session per spawned task.
        pass
    return init


# ---------------------------------------------------------------------------
# Lifespan factory.
# ---------------------------------------------------------------------------


def build_lifespan(audit_log_event):  # type: ignore[no-untyped-def]
    """Build the lifespan callable to pass into :class:`mcp.server.Server`.

    *audit_log_event* is a callable ``(action: str, *, auth, detail) -> None``
    used to emit ``mcp_session_opened`` / ``mcp_session_closed`` audit rows.
    Wrapped to allow injection in tests; in production this is
    :func:`engramia.api.audit.log_db_event` partially-applied with the
    auth engine.
    """
    # Local import to avoid circular dependency at module load time.
    from engramia.mcp import metrics as _metrics

    @contextlib.asynccontextmanager
    async def _lifespan(server) -> AsyncIterator[SessionMetadata]:  # type: ignore[no-untyped-def]
        init = take_pending_init()
        if init is None:
            # No pending init — should not happen in production because the
            # HTTP layer always sets one before spawning. Tolerate it for
            # robustness: yield a sentinel session with no auth so any tool
            # call inside this session fails closed.
            _log.error(
                "MCP lifespan started without SessionInit in contextvar — "
                "this is a bug; failing the session closed."
            )
            raise RuntimeError("MCP session started without authentication context")

        meta: SessionMetadata = {
            "auth": init.auth,
            "slot": init.slot,
            "opened_at": init.opened_at,
            "tool_calls": 0,
        }

        try:
            audit_log_event(
                "mcp_session_opened",
                auth=init.auth,
                detail={
                    "plan_tier": init.auth.plan_tier,
                },
            )
        except Exception:  # pragma: no cover  — audit failure must not bring session down
            _log.exception("Failed to emit mcp_session_opened audit event")

        _metrics.MCP_ACTIVE_SESSIONS.labels(plan_tier=init.auth.plan_tier).inc()

        try:
            yield meta
        finally:
            _metrics.MCP_ACTIVE_SESSIONS.labels(plan_tier=init.auth.plan_tier).dec()
            # Release the connection slot regardless of how we got here
            # (graceful close, idle timeout, exception).
            try:
                await init.slot.release()
            except Exception:  # pragma: no cover
                _log.exception("Failed to release MCP connection slot")

            try:
                audit_log_event(
                    "mcp_session_closed",
                    auth=init.auth,
                    detail={
                        "plan_tier": init.auth.plan_tier,
                        "tool_calls": meta["tool_calls"],
                        "duration_seconds": (
                            datetime.now(tz=UTC) - init.opened_at
                        ).total_seconds(),
                    },
                )
            except Exception:  # pragma: no cover
                _log.exception("Failed to emit mcp_session_closed audit event")

    return _lifespan

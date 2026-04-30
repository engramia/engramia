# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Hosted MCP server using Streamable HTTP transport.

Mounts a Starlette sub-app at ``/v1/mcp`` on the FastAPI app behind a
feature flag (``ENGRAMIA_MCP_HOSTED_ENABLED=true``). The sub-app speaks
the MCP Streamable HTTP wire protocol (single-endpoint variant from spec
2025-03-26): POST for client→server JSON-RPC, GET upgrades to SSE for
server→client notifications, DELETE for explicit session termination.

Why a sub-app rather than a plain FastAPI route:

- The MCP SDK's :class:`StreamableHTTPSessionManager` exposes a raw ASGI
  ``handle_request(scope, receive, send)`` interface. Routing it through
  FastAPI's ``Request`` abstraction requires reaching internal attributes
  (``_send``) that aren't part of the public API. A sub-app keeps us at
  the ASGI layer end-to-end.
- The session manager has its own ``run()`` lifecycle that must be entered
  alongside the app's startup. A Starlette sub-app has a first-class
  ``lifespan`` parameter for exactly this.

Layering — top to bottom:

    FastAPI app (parent middlewares: SecurityHeaders, RateLimit, ...)
        |
        v
    Starlette sub-app (mounted at /v1/mcp)
        |
        v   ASGI handler in this file: auth + tier gate + connection limit
        |
        v
    StreamableHTTPSessionManager  (MCP SDK; session lifecycle, idle timeout)
        |
        v
    Server.list_tools / Server.call_tool  (this module's callbacks)
        |
        v
    dispatch.dispatch_to_memory  (shared with stdio)

Per-session state lives in two places:

- The MCP SDK manages the session-id, the read/write streams, and the idle
  cancel-scope.
- Our :class:`SessionMetadata` (in ``session.py``) carries the auth context
  and connection-limiter slot. It's pulled out of the ``request_ctx``
  contextvar's ``lifespan_context`` field by the tool callbacks.

The handshake: the request handler stashes a :class:`SessionInit` in a
contextvar before calling ``handle_request``, and the SDK-spawned lifespan
task reads it back at session start (anyio copies the parent task's
contextvars at spawn time).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from typing import TYPE_CHECKING, Any

import mcp.types as mcp_types
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Route

from engramia._context import reset_scope, set_scope
from engramia.api import audit as _audit
from engramia.api.permissions import PERMISSIONS
from engramia.mcp import dispatch as _dispatch_mod
from engramia.mcp import metrics as _metrics
from engramia.mcp import session as _session_mod
from engramia.mcp import tools as _tools_mod
from engramia.mcp.errors import (
    ConnectionLimitExceeded,
    TierGateError,
    ToolNotFoundError,
    ToolPermissionError,
)
from engramia.mcp.tier_gate import (
    AcquiredSlot,
    ConnectionLimiter,
    make_limiter_from_env,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI
    from starlette.types import Receive, Scope, Send

    from engramia.types import AuthContext

_log = logging.getLogger(__name__)

#: Path the MCP transport is mounted at (relative to /v1).
MCP_MOUNT_PATH = "/v1/mcp"


# ---------------------------------------------------------------------------
# App back-reference for callbacks that don't see Starlette requests
# (MCP tool callbacks need to reach app.state.memory and app.state.billing).
# ---------------------------------------------------------------------------


class _AppHolder:
    """Mutable holder so :func:`mount_hosted_mcp` can install the app
    before the closures inside ``_build_mcp_server`` run.
    """

    app: FastAPI | None = None


_APP_HOLDER = _AppHolder()


# ---------------------------------------------------------------------------
# Audit helper.
# ---------------------------------------------------------------------------


def _make_audit_emitter(engine):  # type: ignore[no-untyped-def]
    """Build a callable ``(action, *, auth, detail) -> None`` that emits an
    audit log line and (when engine is set) an audit_log DB row.
    """

    def _emit(action: str, *, auth: AuthContext, detail: dict[str, Any] | None = None) -> None:
        try:
            _audit._audit_log.warning(
                "AUDIT %s",
                json.dumps(
                    {
                        "audit": True,
                        "event": action,
                        "tenant_id": auth.tenant_id,
                        "project_id": auth.project_id,
                        "key_id": auth.key_id,
                        "role": auth.role,
                        "plan_tier": auth.plan_tier,
                        "detail": detail or {},
                    },
                    default=str,
                ),
            )
        except Exception:  # pragma: no cover
            _log.exception("Failed to emit MCP audit log line")

        if engine is None:
            return

        try:
            _audit.log_db_event(
                engine,
                tenant_id=auth.tenant_id,
                project_id=auth.project_id,
                action=action,
                key_id=auth.key_id,
                resource_type="mcp_session",
            )
        except Exception:  # pragma: no cover
            _log.exception("Failed to write MCP audit DB event")

    return _emit


# ---------------------------------------------------------------------------
# Server callbacks — list_tools / call_tool. One Server instance per process.
# Per-session state arrives via request_context.lifespan_context.
# ---------------------------------------------------------------------------


def _build_mcp_server(audit_emit) -> Server:  # type: ignore[no-untyped-def]
    server: Server = Server(
        "engramia-hosted",
        lifespan=_session_mod.build_lifespan(audit_emit),
    )

    @server.list_tools()
    async def _list_tools() -> list[mcp_types.Tool]:
        ctx = server.request_context  # type: ignore[attr-defined]
        meta: _session_mod.SessionMetadata = ctx.lifespan_context  # type: ignore[assignment]
        auth = meta["auth"]
        role_perms = PERMISSIONS.get(auth.role, frozenset())
        return _tools_mod.tools_for(auth.plan_tier, role_perms)

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[mcp_types.TextContent]:
        ctx = server.request_context  # type: ignore[attr-defined]
        meta: _session_mod.SessionMetadata = ctx.lifespan_context  # type: ignore[assignment]
        auth = meta["auth"]

        try:
            entry = _tools_mod.get_entry(name)
            if entry is None:
                raise ToolNotFoundError(f"Unknown tool: {name!r}")

            # Tier gate at the per-tool level (tools/list already filters,
            # but a misbehaving client may call a hidden tool name directly
            # — defence in depth).
            if not _tools_mod.tier_satisfies(auth.plan_tier, entry.min_tier):
                raise TierGateError(
                    f"Tool '{name}' requires {entry.min_tier} tier or higher.",
                    current_tier=auth.plan_tier,
                    required_tier=entry.min_tier,
                )

            # RBAC — same gate the REST API uses.
            role_perms = PERMISSIONS.get(auth.role, frozenset())
            if "*" not in role_perms and entry.permission not in role_perms:
                raise ToolPermissionError(
                    tool=name,
                    required_permission=entry.permission,
                    role=auth.role,
                )

            # Quota — mirror REST behaviour (OQ-002 resolved).
            await _enforce_quota(entry, auth)

            # Bind tenant scope for the duration of the Memory call.
            scope_token = set_scope(auth.scope)
            try:
                memory = _APP_HOLDER.app.state.memory  # type: ignore[union-attr]
                result = await asyncio.to_thread(_dispatch_mod.dispatch_to_memory, memory, name, arguments)
            finally:
                reset_scope(scope_token)

            meta["tool_calls"] += 1

            _metrics.MCP_TOOL_CALLS_TOTAL.labels(tool=name, plan_tier=auth.plan_tier, status="ok").inc()

            audit_emit(
                "mcp_tool_called",
                auth=auth,
                detail={"tool": name, "status": "ok"},
            )

            return [
                mcp_types.TextContent(
                    type="text",
                    text=_dispatch_mod.format_result_text(result),
                )
            ]

        except TierGateError as exc:
            _metrics.MCP_TOOL_CALLS_TOTAL.labels(tool=name, plan_tier=auth.plan_tier, status="tier_blocked").inc()
            audit_emit(
                "mcp_tool_blocked_by_tier",
                auth=auth,
                detail={
                    "tool": name,
                    "current_tier": exc.current_tier,
                    "required_tier": exc.required_tier,
                },
            )
            return [
                mcp_types.TextContent(
                    type="text",
                    text=(
                        f"This tool requires the {exc.required_tier} tier "
                        f"or higher. Your tenant is on the {exc.current_tier} "
                        "tier. Upgrade in the dashboard to enable it."
                    ),
                )
            ]

        except ToolPermissionError as exc:
            audit_emit(
                "mcp_tool_rbac_denied",
                auth=auth,
                detail={
                    "tool": name,
                    "required_permission": exc.required_permission,
                    "role": exc.role,
                },
            )
            return [mcp_types.TextContent(type="text", text=str(exc))]

        except ToolNotFoundError as exc:
            return [mcp_types.TextContent(type="text", text=str(exc))]

        except StarletteHTTPException as exc:
            # Quota errors raise HTTPException; convert to MCP-level error.
            audit_emit(
                "mcp_tool_quota_exceeded",
                auth=auth,
                detail={"tool": name, "status_code": exc.status_code},
            )
            detail_str = exc.detail.get("message", str(exc.detail)) if isinstance(exc.detail, dict) else str(exc.detail)
            return [
                mcp_types.TextContent(
                    type="text",
                    text=f"Quota exceeded: {detail_str}",
                )
            ]

        except Exception as exc:  # pragma: no cover
            _log.exception("MCP tool %r failed unexpectedly", name)
            audit_emit(
                "mcp_tool_error",
                auth=auth,
                detail={"tool": name, "error_class": type(exc).__name__},
            )
            return [mcp_types.TextContent(type="text", text=f"Error: {exc}")]

    return server


async def _enforce_quota(entry: _tools_mod.ToolEntry, auth: AuthContext) -> None:  # type: ignore[no-untyped-def]
    """Mirror REST quota checks: eval_runs hit BillingService.check_eval_runs;
    patterns hit BillingService.check_patterns(tenant_id, current_count).
    """
    if entry.quota_kind == "none":
        return

    app = _APP_HOLDER.app
    if app is None:  # pragma: no cover  — only in unit tests that skip mount
        return

    billing_svc = getattr(app.state, "billing_service", None)
    if billing_svc is None:
        return  # dev / JSON storage mode — no enforcement

    if entry.quota_kind == "eval_runs":
        await asyncio.to_thread(billing_svc.check_eval_runs, auth.tenant_id)
        return

    if entry.quota_kind == "patterns":
        memory = app.state.memory

        def _count_and_check() -> None:
            current = memory.metrics.pattern_count
            billing_svc.check_patterns(auth.tenant_id, current)

        await asyncio.to_thread(_count_and_check)


# ---------------------------------------------------------------------------
# ASGI handler — auth + tier gate + connection limit + delegate.
# ---------------------------------------------------------------------------


def _make_asgi_handler(
    *,
    manager: StreamableHTTPSessionManager,
    limiter: ConnectionLimiter,
    audit_emit,  # type: ignore[no-untyped-def]
):
    """Build the ASGI handler for the mounted sub-app's single route."""

    async def _handler(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # pragma: no cover
            await _send_status(scope, send, 400, b"Only HTTP transport supported")
            return

        method = scope.get("method", "")
        headers = _ascii_headers(scope.get("headers", []))

        # Authenticate by replaying a synthetic FastAPI ``require_auth`` call.
        # We can't use Depends here because we're outside the FastAPI request
        # cycle, so we call into the auth module directly.
        auth = await _authenticate_from_scope(scope, headers)

        # Existing-session detection by header presence.
        session_id_header = headers.get("mcp-session-id")
        is_new_session = session_id_header is None and method == "POST"

        # Tier gate + connection limit only when we have an auth context AND
        # this is a new session. Existing sessions piggy-back on the slot
        # they already hold.
        slot: AcquiredSlot | None = None
        token = None
        if auth is not None and is_new_session:
            if not _tools_mod.tier_satisfies(auth.plan_tier, _tools_mod.MIN_TIER_FOR_HOSTED_MCP):
                _metrics.MCP_TIER_REJECTIONS_TOTAL.labels(plan_tier=auth.plan_tier).inc()
                audit_emit(
                    "mcp_session_tier_rejected",
                    auth=auth,
                    detail={"plan_tier": auth.plan_tier},
                )
                await _send_json(
                    scope,
                    send,
                    402,
                    {
                        "error": "tier_too_low",
                        "message": (
                            f"Hosted MCP requires the {_tools_mod.MIN_TIER_FOR_HOSTED_MCP} "
                            f"tier or higher. Your tenant is on the {auth.plan_tier} "
                            "tier. Upgrade in the dashboard to enable hosted MCP."
                        ),
                        "current_tier": auth.plan_tier,
                        "required_tier": _tools_mod.MIN_TIER_FOR_HOSTED_MCP,
                    },
                )
                return

            try:
                slot = await limiter.acquire(auth.tenant_id, auth.plan_tier)
            except ConnectionLimitExceeded as exc:
                _metrics.MCP_CONNECTION_LIMIT_REJECTIONS_TOTAL.labels(plan_tier=auth.plan_tier).inc()
                audit_emit(
                    "mcp_connection_limit_exceeded",
                    auth=auth,
                    detail={"used": exc.used, "cap": exc.cap},
                )
                await _send_json(
                    scope,
                    send,
                    429,
                    {
                        "error": "connection_limit_exceeded",
                        "message": str(exc),
                        "used": exc.used,
                        "cap": exc.cap,
                        "plan_tier": exc.plan_tier,
                    },
                    extra_headers={"retry-after": "60"},
                )
                return

            init = _session_mod.SessionInit(auth=auth, slot=slot, limiter=limiter)
            token = _session_mod.stash_pending_init(init)

        try:
            await manager.handle_request(scope, receive, send)
        finally:
            if token is not None:
                _session_mod.reset_pending_init(token)

    return _handler


# ---------------------------------------------------------------------------
# Manual auth — reach into the existing auth.py from inside an ASGI handler
# without going through FastAPI's Depends machinery.
# ---------------------------------------------------------------------------


async def _authenticate_from_scope(scope: Scope, headers: dict[str, str]) -> AuthContext | None:
    """Authenticate using the same logic the REST API uses.

    Returns:
        The AuthContext on successful auth. ``None`` when the deployment
        is in env-var or dev auth mode (no per-key context). Raises
        :class:`StarletteHTTPException` (401/403) on bad credentials —
        callers catch and convert to ASGI response.
    """
    from fastapi import Request as FastAPIRequest

    from engramia.api.auth import require_auth

    # Build a minimal FastAPI Request so require_auth can read its state.
    # We don't need a body; auth only inspects headers.
    request = FastAPIRequest(scope, receive=_noop_receive)
    try:
        await require_auth(request)
    except Exception:
        raise
    return getattr(request.state, "auth_context", None)


async def _noop_receive() -> dict[str, Any]:
    """Receive callable that returns an empty body — auth doesn't read it."""
    return {"type": "http.request", "body": b"", "more_body": False}


# ---------------------------------------------------------------------------
# ASGI helpers.
# ---------------------------------------------------------------------------


def _ascii_headers(raw_headers: list) -> dict[str, str]:
    """Convert ASGI raw headers (list of [bytes, bytes]) to a lower-cased
    dict for easy lookup. ASGI specifies header names are lowercase but be
    defensive.
    """
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in raw_headers}


async def _send_status(scope: Scope, send: Send, status_code: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [(b"content-type", b"text/plain; charset=utf-8")],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


async def _send_json(
    scope: Scope,
    send: Send,
    status_code: int,
    payload: dict[str, Any],
    *,
    extra_headers: dict[str, str] | None = None,
) -> None:
    body = json.dumps(payload).encode("utf-8")
    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    if extra_headers:
        for k, v in extra_headers.items():
            headers.append((k.encode("ascii"), v.encode("ascii")))
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": headers,
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


# ---------------------------------------------------------------------------
# Public entry point — mount onto a FastAPI app.
# ---------------------------------------------------------------------------


def mount_hosted_mcp(app: FastAPI) -> Starlette | None:
    """Wire the hosted MCP sub-app onto *app* at ``/v1/mcp``.

    Returns the Starlette sub-app if mounted, ``None`` if the feature flag
    is off. Idempotent at the level the operator cares about — calling it
    twice during app construction is a programming error.

    Reads:
        ENGRAMIA_MCP_HOSTED_ENABLED        feature flag (default false)
        ENGRAMIA_MCP_SESSION_IDLE_SECONDS  idle timeout (default 1800)
        ENGRAMIA_MCP_LIMITER_BACKEND       limiter backend (default inmemory)
        ENGRAMIA_MCP_LIMITS_TEAM/BUSINESS/ENTERPRISE  per-tier session caps
    """
    enabled = os.environ.get("ENGRAMIA_MCP_HOSTED_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    if not enabled:
        _log.info("Hosted MCP disabled (ENGRAMIA_MCP_HOSTED_ENABLED=false). /v1/mcp not mounted.")
        return None

    idle_seconds = float(os.environ.get("ENGRAMIA_MCP_SESSION_IDLE_SECONDS", "1800"))
    limiter = make_limiter_from_env(dict(os.environ))
    audit_emit = _make_audit_emitter(getattr(app.state, "auth_engine", None))

    server = _build_mcp_server(audit_emit)
    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=False,
        stateless=False,  # ADR-002
        session_idle_timeout=idle_seconds,
    )

    # Install app back-ref so MCP callbacks can reach app.state.{memory, billing_service}.
    _APP_HOLDER.app = app

    handler = _make_asgi_handler(
        manager=manager,
        limiter=limiter,
        audit_emit=audit_emit,
    )

    @contextlib.asynccontextmanager
    async def _lifespan(_: Starlette) -> AsyncIterator[None]:
        async with manager.run():
            yield

    sub = Starlette(
        lifespan=_lifespan,
        routes=[Route("/", handler, methods=["POST", "GET", "DELETE"])],
    )

    # Mount path matches MCP_MOUNT_PATH; FastAPI / Starlette dispatches
    # ``POST /v1/mcp`` and ``POST /v1/mcp/`` to this sub-app's "/" route.
    app.mount(MCP_MOUNT_PATH, sub)
    _log.info(
        "Hosted MCP mounted at %s (idle_timeout=%ss, limiter=%s)",
        MCP_MOUNT_PATH,
        int(idle_seconds),
        type(limiter).__name__,
    )
    return sub

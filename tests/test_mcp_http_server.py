# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""End-to-end tests for engramia.mcp.http_server — hosted MCP transport.

We don't run a full MCP client handshake — that's an SDK integration test
and would need a live event loop with the streaming transport up. Instead
we test the HTTP-layer policy gates (tier rejection, connection limit,
mount) by exercising the ASGI handler directly with crafted scopes. The
SDK delegate is mocked so we can assert it's reached only on the happy
path.
"""

import json
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# tests/test_mcp.py and tests/test_mcp_transport.py register *fake* MCP
# package stubs in sys.modules to import the stdio server without the SDK.
# Those stubs are non-package ModuleType objects, which breaks our real
# import of ``mcp.server.streamable_http_manager``. Wipe them so the real
# mcp package (which the test environment does have installed) is imported
# by ``http_server`` below.
#
# We deliberately do NOT evict ``engramia.mcp.*`` modules here — doing so
# would invalidate function references already imported by the other test
# files (``call_tool`` etc), breaking their patches. ``http_server`` has
# its own ``from mcp.server import Server`` import path and only needs the
# real ``mcp`` package, not fresh tools/dispatch instances.
for _mcp_mod in [m for m in list(sys.modules) if m == "mcp" or m.startswith("mcp.")]:
    sys.modules.pop(_mcp_mod, None)


@pytest.fixture()
def hosted_mcp_env(monkeypatch):
    monkeypatch.setenv("ENGRAMIA_MCP_HOSTED_ENABLED", "true")
    monkeypatch.setenv("ENGRAMIA_AUTH_MODE", "dev")
    monkeypatch.setenv("ENGRAMIA_ALLOW_NO_AUTH", "true")
    monkeypatch.setenv("ENGRAMIA_STORAGE", "json")
    monkeypatch.setenv("ENGRAMIA_DATA_PATH", "./engramia_data_test_mcp_http")
    monkeypatch.setenv("ENGRAMIA_LLM_PROVIDER", "none")
    monkeypatch.setenv("ENGRAMIA_EMBEDDING_MODEL", "none")
    yield


def _http_scope(method: str, path: str, headers: dict[str, str] | None = None) -> dict:
    """Build a minimal ASGI HTTP scope for the handler under test."""
    raw_headers = []
    for k, v in (headers or {}).items():
        raw_headers.append((k.encode("latin-1"), v.encode("latin-1")))
    return {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode("latin-1"),
        "query_string": b"",
        "headers": raw_headers,
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
    }


class _CapturingSend:
    """Records ASGI send messages so the test can assert the response."""

    def __init__(self):
        self.messages: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)

    @property
    def status(self) -> int | None:
        for m in self.messages:
            if m["type"] == "http.response.start":
                return m["status"]
        return None

    @property
    def body(self) -> bytes:
        chunks = [m["body"] for m in self.messages if m["type"] == "http.response.body"]
        return b"".join(chunks)

    def json(self) -> dict:
        return json.loads(self.body)


async def _empty_receive() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}


def test_mount_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENGRAMIA_MCP_HOSTED_ENABLED", raising=False)
    from fastapi import FastAPI

    from engramia.mcp.http_server import mount_hosted_mcp

    app = FastAPI()
    result = mount_hosted_mcp(app)
    assert result is None


def test_mount_enabled_returns_subapp(hosted_mcp_env):
    from fastapi import FastAPI

    from engramia.mcp.http_server import mount_hosted_mcp

    app = FastAPI()
    result = mount_hosted_mcp(app)
    assert result is not None
    # Mounted at /v1/mcp
    mounts = [r for r in app.routes if getattr(r, "path", None) == "/v1/mcp"]
    assert len(mounts) == 1


@pytest.mark.asyncio
async def test_handler_rejects_pro_tier_with_402(hosted_mcp_env):
    from engramia.mcp import http_server
    from engramia.mcp.tier_gate import InMemoryConnectionLimiter
    from engramia.types import AuthContext, Scope

    limiter = InMemoryConnectionLimiter()
    sdk_mock = AsyncMock()  # would be called only on happy path
    audit_calls = []

    def _audit(action, *, auth, detail=None):
        audit_calls.append((action, auth.tenant_id, detail or {}))

    handler = http_server._make_asgi_handler(
        manager=MagicMock(handle_request=sdk_mock),
        limiter=limiter,
        audit_emit=_audit,
    )

    auth = AuthContext(
        key_id="k1",
        tenant_id="t-pro",
        project_id="p1",
        role="owner",
        plan_tier="pro",  # below team — should be rejected
        scope=Scope(tenant_id="t-pro", project_id="p1"),
    )

    # Patch _authenticate_from_scope to return our auth without going
    # through real auth machinery.
    async def _fake_auth(scope, headers):
        return auth

    import engramia.mcp.http_server as mod

    original = mod._authenticate_from_scope
    mod._authenticate_from_scope = _fake_auth
    try:
        send = _CapturingSend()
        await handler(_http_scope("POST", "/"), _empty_receive, send)
    finally:
        mod._authenticate_from_scope = original

    assert send.status == 402
    body = send.json()
    assert body["error"] == "tier_too_low"
    assert body["current_tier"] == "pro"
    assert body["required_tier"] == "team"

    sdk_mock.assert_not_called()
    assert any(a == "mcp_session_tier_rejected" for a, _, _ in audit_calls)


@pytest.mark.asyncio
async def test_handler_rejects_when_connection_limit_exceeded(hosted_mcp_env):
    from engramia.mcp import http_server
    from engramia.mcp.tier_gate import InMemoryConnectionLimiter
    from engramia.types import AuthContext, Scope

    # Cap of 1 so the second request exceeds.
    limiter = InMemoryConnectionLimiter(tier_limits={"team": 1})
    sdk_mock = AsyncMock()

    def _audit(action, *, auth, detail=None):
        return None

    handler = http_server._make_asgi_handler(
        manager=MagicMock(handle_request=sdk_mock),
        limiter=limiter,
        audit_emit=_audit,
    )

    auth = AuthContext(
        key_id="k",
        tenant_id="t",
        project_id="p",
        role="owner",
        plan_tier="team",
        scope=Scope(tenant_id="t", project_id="p"),
    )

    async def _fake_auth(scope, headers):
        return auth

    import engramia.mcp.http_server as mod

    mod._authenticate_from_scope = _fake_auth
    try:
        # First open succeeds (acquires the only slot). The SDK is stubbed
        # to no-op — but we never release the slot, so the second open
        # will see used=1, cap=1.
        send1 = _CapturingSend()
        await handler(_http_scope("POST", "/"), _empty_receive, send1)
        assert send1.status is None  # SDK handled it; our handler didn't write.

        send2 = _CapturingSend()
        await handler(_http_scope("POST", "/"), _empty_receive, send2)
        assert send2.status == 429
        body = send2.json()
        assert body["error"] == "connection_limit_exceeded"
        assert body["used"] == 1
        assert body["cap"] == 1
    finally:
        mod._authenticate_from_scope = (
            __import__("engramia.mcp.http_server", fromlist=["_authenticate_from_scope"])
            ._authenticate_from_scope
        )


@pytest.mark.asyncio
async def test_handler_passes_through_when_no_auth_context(hosted_mcp_env):
    """env-var / dev auth modes: auth=None, no tier-gate enforced. Handler
    just delegates to the SDK."""
    from engramia.mcp import http_server
    from engramia.mcp.tier_gate import InMemoryConnectionLimiter

    sdk_mock = AsyncMock()

    handler = http_server._make_asgi_handler(
        manager=MagicMock(handle_request=sdk_mock),
        limiter=InMemoryConnectionLimiter(),
        audit_emit=lambda *a, **kw: None,
    )

    async def _fake_auth(scope, headers):
        return None  # dev / env-var mode

    import engramia.mcp.http_server as mod

    original = mod._authenticate_from_scope
    mod._authenticate_from_scope = _fake_auth
    try:
        send = _CapturingSend()
        await handler(_http_scope("POST", "/"), _empty_receive, send)
        sdk_mock.assert_awaited_once()
        # No tier gate, no error response.
        assert send.status is None
    finally:
        mod._authenticate_from_scope = original

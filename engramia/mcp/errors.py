# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Hosted MCP error taxonomy.

Distinct from REST API errors because MCP wraps tool failures in JSON-RPC
result-with-isError instead of HTTP status codes. The classes below are used
by ``dispatch.dispatch_tool`` to signal *why* a call failed; the HTTP layer
in ``http_server`` maps them to either MCP error responses or HTTP status
codes depending on whether the failure happened before or during MCP protocol
processing.
"""

from __future__ import annotations


class MCPError(Exception):
    """Base for all hosted-MCP-specific failures."""


class TierGateError(MCPError):
    """Raised when a tenant's plan tier is insufficient for an operation.

    Two distinct contexts:

    - During session ``initialize``: tenant tier < ``team`` → HTTP 402.
    - During ``tools/call``: tool's ``min_tier`` not satisfied → MCP-level
      tool error (``isError: true``) rather than HTTP error, so MCP clients
      surface the upgrade prompt cleanly.
    """

    def __init__(self, message: str, *, current_tier: str, required_tier: str) -> None:
        super().__init__(message)
        self.current_tier = current_tier
        self.required_tier = required_tier


class ConnectionLimitExceeded(MCPError):
    """Raised by ``ConnectionLimiter`` when tenant has hit its concurrent-
    session cap (5 / 25 / 100 by tier). Mapped to HTTP 429."""

    def __init__(self, *, tenant_id: str, plan_tier: str, used: int, cap: int) -> None:
        super().__init__(
            f"Tenant connection limit reached ({used}/{cap} for {plan_tier} tier)."
        )
        self.tenant_id = tenant_id
        self.plan_tier = plan_tier
        self.used = used
        self.cap = cap


class ToolNotFoundError(MCPError, ValueError):
    """Unknown tool name.

    Inherits :class:`ValueError` for backward compatibility with the
    pre-refactor stdio dispatch which raised plain ``ValueError`` on unknown
    tool names. New code should catch :class:`ToolNotFoundError` directly.
    """


class ToolPermissionError(MCPError):
    """Caller's RBAC role is missing the permission required by the tool.

    Mirrors the existing :class:`engramia.exceptions.AuthorizationError` but
    surfaces it as an MCP tool error rather than an HTTP 403, since MCP has
    no transport-level RBAC.
    """

    def __init__(self, *, tool: str, required_permission: str, role: str) -> None:
        super().__init__(
            f"Role '{role}' does not have permission '{required_permission}' "
            f"required by tool '{tool}'."
        )
        self.tool = tool
        self.required_permission = required_permission
        self.role = role

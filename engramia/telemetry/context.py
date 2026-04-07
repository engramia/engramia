# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Request-scoped contextvar for request/trace ID propagation.

A unique request ID is generated per HTTP request in RequestIDMiddleware
and stored here so that all layers (routes, providers, job workers) can
include it in logs and spans without threading it through every call.

Usage::

    from engramia.telemetry.context import get_request_id, set_request_id, reset_request_id
    rid = get_request_id()          # "" when not inside a request
    token = set_request_id("uuid")  # returns Token for cleanup
    reset_request_id(token)
"""

from contextvars import ContextVar, Token

_request_id_var: ContextVar[str] = ContextVar("engramia_request_id", default="")


def get_request_id() -> str:
    """Return the request ID active in the current async/thread context.

    Returns an empty string when called outside a request context
    (e.g. background threads, CLI, tests without middleware).
    """
    return _request_id_var.get()


def set_request_id(request_id: str) -> Token[str]:
    """Set the request ID for the current context. Returns a reset Token."""
    return _request_id_var.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    """Restore the previous request ID using the Token from set_request_id()."""
    _request_id_var.reset(token)

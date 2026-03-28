# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""FastAPI dependency injection for the Memory singleton.

The Memory instance is created once at app startup (in ``create_app()``)
and stored on ``app.state.memory``. Each request retrieves it via this
dependency — no per-request construction overhead.
"""

from fastapi import Request

from engramia import Memory


def get_memory(request: Request) -> Memory:
    """Return the shared Memory instance from app state."""
    return request.app.state.memory

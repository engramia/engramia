"""FastAPI dependency injection for the Memory singleton.

The Memory instance is created once at app startup (in ``create_app()``)
and stored on ``app.state.brain``. Each request retrieves it via this
dependency — no per-request construction overhead.
"""

from fastapi import Request

from engramia import Memory


def get_brain(request: Request) -> Memory:
    """Return the shared Memory instance from app state."""
    return request.app.state.brain

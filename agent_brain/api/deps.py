"""FastAPI dependency injection for the Brain singleton.

The Brain instance is created once at app startup (in ``create_app()``)
and stored on ``app.state.brain``. Each request retrieves it via this
dependency — no per-request construction overhead.
"""

from fastapi import Request

from agent_brain import Brain


def get_brain(request: Request) -> Brain:
    """Return the shared Brain instance from app state."""
    return request.app.state.brain

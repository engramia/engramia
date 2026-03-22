"""Bearer token authentication for the Agent Brain API.

Keys are loaded from the ``BRAIN_API_KEYS`` environment variable as a
comma-separated list.  If the variable is not set, the API runs in
unauthenticated dev mode and all requests are accepted.

Usage:
    # Authenticated request
    curl -H "Authorization: Bearer my-secret-key" http://localhost:8000/metrics
"""

import logging
import os

from fastapi import HTTPException, Request, status

_log = logging.getLogger(__name__)


def _load_api_keys() -> set[str]:
    raw = os.environ.get("BRAIN_API_KEYS", "")
    keys = {k.strip() for k in raw.split(",") if k.strip()}
    if not keys:
        _log.warning(
            "BRAIN_API_KEYS is not set — API is running in unauthenticated dev mode. "
            "Set BRAIN_API_KEYS=key1,key2 before exposing this service publicly."
        )
    return keys


# Loaded once at import time; restart required to pick up new keys
_API_KEYS: set[str] = _load_api_keys()


async def require_auth(request: Request) -> None:
    """FastAPI dependency that validates the Bearer token.

    Attach to a route with ``dependencies=[Depends(require_auth)]``.
    No-op when ``BRAIN_API_KEYS`` is empty (dev mode).
    """
    if not _API_KEYS:
        return  # dev mode — no auth

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Expected: Bearer <key>",
        )
    token = auth_header[len("Bearer "):]
    if token not in _API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )

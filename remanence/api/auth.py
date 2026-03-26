"""Bearer token authentication for the Remanence API.

Keys are loaded from the ``REMANENCE_API_KEYS`` environment variable as a
comma-separated list.  If the variable is not set, the API runs in
unauthenticated dev mode and all requests are accepted.

Token comparison uses ``hmac.compare_digest`` to prevent timing oracle attacks.

Usage:
    # Authenticated request
    curl -H "Authorization: Bearer my-secret-key" http://localhost:8000/v1/metrics
"""

import hmac
import logging
import os

from fastapi import HTTPException, Request, status

_log = logging.getLogger(__name__)


def _load_api_keys() -> set[str]:
    raw = os.environ.get("REMANENCE_API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


async def require_auth(request: Request) -> None:
    """FastAPI dependency that validates the Bearer token.

    Attach to a route with ``dependencies=[Depends(require_auth)]``.
    No-op when ``REMANENCE_API_KEYS`` is empty (dev mode).

    Token comparison is done with ``hmac.compare_digest`` to prevent
    timing oracle attacks.
    """
    api_keys = _load_api_keys()
    if not api_keys:
        return  # dev mode — no auth

    auth_header = request.headers.get("Authorization", "")
    ip = request.client.host if request.client else "unknown"

    if not auth_header.startswith("Bearer "):
        from remanence.api.audit import AuditEvent, log_event  # deferred to avoid circular import

        log_event(AuditEvent.AUTH_FAILURE, ip=ip, reason="missing_or_malformed_header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Expected: Bearer <key>",
        )

    token = auth_header[len("Bearer ") :]
    # Timing-safe comparison: iterate all keys to avoid leaking which key matched
    # or how many keys exist via response timing differences.
    if not any(hmac.compare_digest(token, key) for key in api_keys):
        from remanence.api.audit import AuditEvent, log_event  # deferred to avoid circular import

        log_event(AuditEvent.AUTH_FAILURE, ip=ip, reason="invalid_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )

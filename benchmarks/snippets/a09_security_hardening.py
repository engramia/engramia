# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""A09 — Security Hardening snippets (good / medium / bad).

Domain: Rate limiting, CSRF, input sanitization, auth endpoint hardening.
"""

GOOD: dict = {
    "eval_score": 9.2,
    "output": "Added rate limiting (sliding window), CSRF double-submit, and input sanitization middleware to auth endpoints.",
    "code": '''\
import hashlib
import logging
import re
import secrets
import time
from collections import defaultdict
from functools import wraps
from typing import Callable

from fastapi import HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)


# --- Rate Limiting (sliding window counter) ---

class RateLimiter:
    """In-memory sliding window rate limiter.

    Args:
        max_requests: Maximum requests per window.
        window_seconds: Window duration in seconds.
    """

    def __init__(self, max_requests: int = 10, window_seconds: int = 60) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self._window
        hits = self._hits[key]
        self._hits[key] = [t for t in hits if t > cutoff]
        if len(self._hits[key]) >= self._max:
            return False
        self._hits[key].append(now)
        return True


auth_limiter = RateLimiter(max_requests=5, window_seconds=60)


async def rate_limit_middleware(request: Request, call_next):
    if request.url.path.startswith("/auth/"):
        client_ip = request.client.host if request.client else "unknown"
        if not auth_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for %s on %s", client_ip, request.url.path)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Try again later.",
                headers={"Retry-After": "60"},
            )
    return await call_next(request)


# --- CSRF Protection (double-submit cookie) ---

CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


async def csrf_middleware(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        cookie_token = request.cookies.get(CSRF_COOKIE)
        header_token = request.headers.get(CSRF_HEADER)
        if not cookie_token or not header_token:
            raise HTTPException(status_code=403, detail="CSRF token missing")
        if not secrets.compare_digest(cookie_token, header_token):
            raise HTTPException(status_code=403, detail="CSRF token mismatch")

    response = await call_next(request)

    if CSRF_COOKIE not in request.cookies:
        token = secrets.token_urlsafe(32)
        response.set_cookie(
            CSRF_COOKIE, token, httponly=False, samesite="strict", secure=True
        )
    return response


# --- Input Sanitization ---

_DANGEROUS_PATTERNS = [
    re.compile(r"<script", re.IGNORECASE),
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"on\\w+=", re.IGNORECASE),
    re.compile(r"\\x00"),
]


def sanitize_input(value: str) -> str:
    """Strip dangerous patterns from user input.

    Removes script tags, javascript: URIs, inline event handlers,
    and null bytes. Does NOT strip valid HTML — use a template
    engine with auto-escaping for output.
    """
    for pattern in _DANGEROUS_PATTERNS:
        value = pattern.sub("", value)
    return value.strip()
''',
}

MEDIUM: dict = {
    "eval_score": 5.5,
    "output": "Added basic rate limiting to login endpoint.",
    "code": """\
from collections import defaultdict
import time
from fastapi import HTTPException

_attempts = defaultdict(list)

def check_rate_limit(ip, max_attempts=5, window=60):
    now = time.time()
    _attempts[ip] = [t for t in _attempts[ip] if now - t < window]
    if len(_attempts[ip]) >= max_attempts:
        raise HTTPException(status_code=429, detail="Too many attempts")
    _attempts[ip].append(now)
""",
}

BAD: dict = {
    "eval_score": 2.2,
    "output": "added security",
    "code": """\
from fastapi import Request

async def security_check(request: Request, call_next):
    # block bad requests
    if "script" in str(request.url):
        return Response("blocked", status_code=400)
    return await call_next(request)
""",
}

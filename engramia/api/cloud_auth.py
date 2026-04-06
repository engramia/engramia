# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Cloud user registration and authentication endpoints.

Supports email/password credentials and OAuth (Google/Apple).
On registration, automatically creates:
  - A new tenant (slug from email prefix, unique)
  - A 'default' project
  - An API key  (engramia-<32 hex chars>)
  - A cloud_user record

JWT tokens:
  Access token:  1 hour  — claims: sub, tenant_id, email, role, type
  Refresh token: 30 days — same claims, type='refresh'
  Secret: ENGRAMIA_JWT_SECRET env var (ephemeral auto-generated if absent)

Rate limiting: POST /auth/register is capped at 5 requests/minute per IP
via an in-process fixed-window counter.
"""

import collections
import hashlib
import logging
import os
import re
import secrets
import threading
import time
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

_log = logging.getLogger(__name__)

router = APIRouter(tags=["Cloud Auth"])

# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

_JWT_SECRET: str | None = None
_JWT_SECRET_LOCK = threading.Lock()

_ACCESS_TOKEN_EXPIRE_SECONDS = 3600  # 1 hour
_REFRESH_TOKEN_EXPIRE_SECONDS = 30 * 86400  # 30 days


def _get_jwt_secret() -> str:
    global _JWT_SECRET
    with _JWT_SECRET_LOCK:
        if _JWT_SECRET is None:
            secret = os.environ.get("ENGRAMIA_JWT_SECRET", "").strip()
            if not secret:
                secret = secrets.token_hex(32)
                _log.warning(
                    "ENGRAMIA_JWT_SECRET not set — generated ephemeral secret. "
                    "Tokens will be invalidated on server restart. "
                    "Set ENGRAMIA_JWT_SECRET for production."
                )
            _JWT_SECRET = secret
        return _JWT_SECRET


def _make_token(
    user_id: str,
    tenant_id: str,
    email: str,
    role: str = "owner",
    *,
    is_refresh: bool = False,
) -> str:
    import jwt  # PyJWT

    now = int(time.time())
    exp = now + (_REFRESH_TOKEN_EXPIRE_SECONDS if is_refresh else _ACCESS_TOKEN_EXPIRE_SECONDS)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "email": email,
        "role": role,
        "type": "refresh" if is_refresh else "access",
        "iat": now,
        "exp": exp,
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")


def _decode_token(token: str, *, require_refresh: bool = False) -> dict:
    import jwt  # PyJWT

    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired.") from None
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.") from None

    token_type = payload.get("type")
    if require_refresh and token_type != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token required.")
    if not require_refresh and token_type == "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Access token required; got refresh token."
        )

    return payload


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Expected: Bearer <token>",
        )
    return auth[len("Bearer ") :]


# ---------------------------------------------------------------------------
# Password helpers (bcrypt — never plain compare)
# ---------------------------------------------------------------------------


def _hash_password(password: str) -> str:
    import bcrypt

    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, password_hash: str) -> bool:
    import bcrypt

    return bcrypt.checkpw(password.encode(), password_hash.encode())


# ---------------------------------------------------------------------------
# Rate limiting: /auth/register — max 5 requests/minute per IP
# ---------------------------------------------------------------------------

_register_rate: collections.OrderedDict[tuple[str, int], int] = collections.OrderedDict()
_register_rate_lock = threading.Lock()
_REGISTER_RATE_LIMIT = 5
_REGISTER_RATE_WINDOW = 60  # seconds


def _check_register_rate(ip: str) -> None:
    window = int(time.time()) // _REGISTER_RATE_WINDOW
    key = (ip, window)
    with _register_rate_lock:
        count = _register_rate.get(key, 0) + 1
        _register_rate[key] = count
        # Evict windows older than the previous complete window
        stale = [(h, w) for h, w in list(_register_rate) if w < window - 1]
        for sk in stale:
            _register_rate.pop(sk, None)
    if count > _REGISTER_RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Please try again in a minute.",
        )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _require_engine(request: Request):
    engine = getattr(request.app.state, "auth_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cloud auth requires a database connection (ENGRAMIA_DATABASE_URL must be configured).",
        )
    return engine


def _generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, display_prefix, sha256_hash). Format: engramia-<32 hex>."""
    suffix = secrets.token_hex(16)  # 32 hex chars
    full_key = f"engramia-{suffix}"
    display_prefix = f"engramia-{suffix[:8]}..."
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    return full_key, display_prefix, key_hash


def _make_tenant_slug(email_prefix: str, engine) -> str:
    """Generate a unique tenant slug from the email prefix."""
    from sqlalchemy import text

    slug_base = re.sub(r"[^a-z0-9]", "-", email_prefix.lower()).strip("-")[:24]
    if not slug_base:
        return uuid.uuid4().hex[:32]

    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM tenants WHERE id = :id LIMIT 1"),
            {"id": slug_base},
        ).fetchone()

    if exists is None:
        return slug_base
    return f"{slug_base}-{uuid.uuid4().hex[:8]}"


def _create_registration(
    engine,
    *,
    email: str,
    password_hash: str | None,
    name: str | None,
    provider: str,
    provider_id: str | None,
    email_verified: bool = False,
) -> dict:
    """Create tenant, project, cloud_user, and API key in a single transaction.

    Returns dict with user_id, tenant_id, project_id, api_key.
    """
    from sqlalchemy import text

    email_prefix = email.split("@")[0]
    tenant_id = _make_tenant_slug(email_prefix, engine)
    project_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    api_key_id = str(uuid.uuid4())
    full_key, display_prefix, key_hash = _generate_api_key()

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tenants (id, name, plan_tier, created_at) VALUES (:id, :name, 'free', now()::text)"),
            {"id": tenant_id, "name": name or email},
        )
        conn.execute(
            text(
                "INSERT INTO projects (id, tenant_id, name, max_patterns, created_at) "
                "VALUES (:id, :tid, 'default', 10000, now()::text)"
            ),
            {"id": project_id, "tid": tenant_id},
        )
        conn.execute(
            text(
                "INSERT INTO cloud_users "
                "(id, email, password_hash, tenant_id, name, provider, provider_id, "
                "email_verified, created_at) "
                "VALUES (:id, :email, :pw_hash, :tid, :name, :provider, :pid, :ev, now())"
            ),
            {
                "id": user_id,
                "email": email,
                "pw_hash": password_hash,
                "tid": tenant_id,
                "name": name,
                "provider": provider,
                "pid": provider_id,
                "ev": email_verified,
            },
        )
        conn.execute(
            text(
                "INSERT INTO api_keys "
                "(id, tenant_id, project_id, name, key_prefix, key_hash, role, "
                "max_patterns, created_at) "
                "VALUES (:id, :tid, :pid, 'Default API Key', :prefix, :hash, 'owner', "
                "NULL, now()::text)"
            ),
            {
                "id": api_key_id,
                "tid": tenant_id,
                "pid": project_id,
                "prefix": display_prefix,
                "hash": key_hash,
            },
        )

    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "api_key": full_key,
    }


# ---------------------------------------------------------------------------
# OAuth token verification
# ---------------------------------------------------------------------------


def _verify_google_token(
    id_token: str,
    fallback_email: str | None,
    fallback_name: str | None,
) -> tuple[str | None, str, str | None]:
    """Verify Google ID token via tokeninfo endpoint.

    Returns (email, provider_sub, name).
    """
    import json
    import urllib.error
    import urllib.parse
    import urllib.request

    url = "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode({"id_token": id_token})
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # nosec B310
            data = json.loads(resp.read())
    except urllib.error.HTTPError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Google token.") from None
    except Exception as exc:
        _log.warning("Google token verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Google token verification failed."
        ) from None

    email = data.get("email") or fallback_email
    provider_id = str(data.get("sub", ""))
    name = data.get("name") or fallback_name
    return email, provider_id, name


def _verify_apple_token(
    id_token: str,
    fallback_email: str | None,
    fallback_name: str | None,
) -> tuple[str | None, str, str | None]:
    """Decode Apple ID token (JWT payload only — no signature verification).

    Production deployments should verify against Apple's JWKS endpoint at
    https://appleid.apple.com/auth/keys.
    """
    import base64
    import json

    try:
        parts = id_token.split(".")
        if len(parts) != 3:
            raise ValueError("not a JWT")
        padding = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + padding))
        email = payload.get("email") or fallback_email
        provider_id = str(payload.get("sub", ""))
        return email, provider_id, fallback_name
    except Exception as exc:
        _log.warning("Apple token decode failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Apple token verification failed."
        ) from None


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: str
    password: str


class OAuthRequest(BaseModel):
    provider: Literal["google", "apple"]
    provider_token: str
    name: str | None = None
    email: str | None = None


class RegisterResponse(BaseModel):
    user_id: str
    email: str
    tenant_id: str
    access_token: str
    refresh_token: str
    api_key: str


class LoginResponse(BaseModel):
    user_id: str
    email: str
    tenant_id: str
    access_token: str
    refresh_token: str


class MeResponse(BaseModel):
    user_id: str
    email: str
    tenant_id: str
    name: str | None
    provider: str
    created_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new cloud user",
    description=(
        "Creates a user account with email/password. "
        "Automatically provisions a new tenant, 'default' project, and API key. "
        "Rate-limited to 5 requests/minute per IP."
    ),
)
def register(body: RegisterRequest, request: Request) -> RegisterResponse:
    ip = request.client.host if request.client else "unknown"
    _check_register_rate(ip)

    if not _EMAIL_RE.match(body.email):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid email address.")

    engine = _require_engine(request)

    from sqlalchemy import text

    from engramia.api.audit import AuditEvent, log_db_event, log_event

    email = body.email.lower()

    with engine.connect() as conn:
        existing = conn.execute(
            text("SELECT 1 FROM cloud_users WHERE email = :email"),
            {"email": email},
        ).fetchone()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")

    password_hash = _hash_password(body.password)
    result = _create_registration(
        engine,
        email=email,
        password_hash=password_hash,
        name=body.name,
        provider="credentials",
        provider_id=None,
    )

    access_token = _make_token(user_id=result["user_id"], tenant_id=result["tenant_id"], email=email)
    refresh_token = _make_token(user_id=result["user_id"], tenant_id=result["tenant_id"], email=email, is_refresh=True)

    log_event(AuditEvent.KEY_CREATED, key_id=result["user_id"], source="cloud_register", ip=ip)
    log_db_event(
        engine,
        tenant_id=result["tenant_id"],
        project_id=result["project_id"],
        action="cloud_register",
        resource_type="cloud_user",
        resource_id=result["user_id"],
        ip_address=ip,
    )
    _log.info("Cloud user registered: %s tenant=%s", email, result["tenant_id"])

    return RegisterResponse(
        user_id=result["user_id"],
        email=email,
        tenant_id=result["tenant_id"],
        access_token=access_token,
        refresh_token=refresh_token,
        api_key=result["api_key"],
    )


@router.post("/login", response_model=LoginResponse, summary="Login with email and password")
def login(body: LoginRequest, request: Request) -> LoginResponse:
    from sqlalchemy import text

    from engramia.api.audit import AuditEvent, log_event

    engine = _require_engine(request)
    ip = request.client.host if request.client else "unknown"
    email = body.email.lower()

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, password_hash, tenant_id FROM cloud_users WHERE email = :email AND provider = 'credentials'"
            ),
            {"email": email},
        ).fetchone()

    if row is None:
        log_event(AuditEvent.AUTH_FAILURE, ip=ip, reason="unknown_email")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    user_id, stored_hash, tenant_id = str(row[0]), row[1], str(row[2])

    if not stored_hash or not _verify_password(body.password, stored_hash):
        log_event(AuditEvent.AUTH_FAILURE, ip=ip, reason="wrong_password")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE cloud_users SET last_login_at = now() WHERE id = :id"),
            {"id": user_id},
        )

    access_token = _make_token(user_id=user_id, tenant_id=tenant_id, email=email)
    refresh_token = _make_token(user_id=user_id, tenant_id=tenant_id, email=email, is_refresh=True)

    return LoginResponse(
        user_id=user_id,
        email=email,
        tenant_id=tenant_id,
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.get("/me", response_model=MeResponse, summary="Get current user info from JWT")
def me(request: Request) -> MeResponse:
    from sqlalchemy import text

    token = _bearer_token(request)
    payload = _decode_token(token)

    engine = _require_engine(request)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, email, tenant_id, name, provider, created_at FROM cloud_users WHERE id = :id"),
            {"id": payload["sub"]},
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    return MeResponse(
        user_id=str(row[0]),
        email=str(row[1]),
        tenant_id=str(row[2]),
        name=row[3],
        provider=str(row[4]),
        created_at=str(row[5]),
    )


@router.post(
    "/oauth",
    response_model=RegisterResponse,
    status_code=status.HTTP_200_OK,
    summary="OAuth login or registration (Google/Apple)",
)
def oauth_login(body: OAuthRequest, request: Request) -> RegisterResponse:
    from sqlalchemy import text

    from engramia.api.audit import AuditEvent, log_event

    engine = _require_engine(request)
    ip = request.client.host if request.client else "unknown"

    if body.provider == "google":
        email, provider_id, name = _verify_google_token(body.provider_token, body.email, body.name)
    else:
        email, provider_id, name = _verify_apple_token(body.provider_token, body.email, body.name)

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not determine email from provider token.",
        )

    email = email.lower()

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, tenant_id FROM cloud_users "
                "WHERE email = :email OR (provider = :provider AND provider_id = :pid) "
                "LIMIT 1"
            ),
            {"email": email, "provider": body.provider, "pid": provider_id},
        ).fetchone()

    if row is not None:
        user_id, tenant_id = str(row[0]), str(row[1])
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE cloud_users SET last_login_at = now() WHERE id = :id"),
                {"id": user_id},
            )
        access_token = _make_token(user_id=user_id, tenant_id=tenant_id, email=email)
        refresh_token = _make_token(user_id=user_id, tenant_id=tenant_id, email=email, is_refresh=True)
        return RegisterResponse(
            user_id=user_id,
            email=email,
            tenant_id=tenant_id,
            access_token=access_token,
            refresh_token=refresh_token,
            api_key="",
        )

    result = _create_registration(
        engine,
        email=email,
        password_hash=None,
        name=name or body.name,
        provider=body.provider,
        provider_id=provider_id,
        email_verified=True,
    )
    access_token = _make_token(user_id=result["user_id"], tenant_id=result["tenant_id"], email=email)
    refresh_token = _make_token(user_id=result["user_id"], tenant_id=result["tenant_id"], email=email, is_refresh=True)

    log_event(
        AuditEvent.KEY_CREATED,
        key_id=result["user_id"],
        source="cloud_oauth",
        provider=body.provider,
        ip=ip,
    )
    return RegisterResponse(
        user_id=result["user_id"],
        email=email,
        tenant_id=result["tenant_id"],
        access_token=access_token,
        refresh_token=refresh_token,
        api_key=result["api_key"],
    )


@router.post("/refresh", summary="Refresh access token using a refresh token")
def refresh(request: Request) -> dict:
    token = _bearer_token(request)
    payload = _decode_token(token, require_refresh=True)
    access_token = _make_token(
        user_id=payload["sub"],
        tenant_id=payload["tenant_id"],
        email=payload["email"],
        role=payload.get("role", "owner"),
    )
    return {"access_token": access_token}


@router.post("/logout", summary="Logout (client-side token invalidation)")
def logout() -> dict:
    # JWTs are stateless — discard tokens on the client side.
    # For server-side invalidation, back this endpoint with a Redis blocklist.
    return {"message": "Logged out successfully. Discard your access and refresh tokens."}

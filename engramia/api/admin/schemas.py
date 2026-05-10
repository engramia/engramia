# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Pydantic request/response models for ``/v1/admin/*``."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    """Always returned with HTTP 200 even on bad creds — the ``kind`` field
    is the source of truth so the frontend can branch deterministically
    without parsing error strings.
    """

    kind: str  # 'totp_required' | 'invalid_credentials' | 'locked' | 'totp_not_enrolled'
    intermediate_token: str | None = None
    detail: str | None = None


class TotpRequest(BaseModel):
    intermediate_token: str = Field(min_length=1)
    code: str = Field(min_length=6, max_length=8)  # 6 digits + tolerate trailing whitespace


class TotpResponse(BaseModel):
    kind: str  # 'ok' | 'invalid_token' | 'invalid_code' | 'locked'
    admin_jwt: str | None = None
    refresh_token: str | None = None
    refresh_expires_at: datetime | None = None
    totp_issued_at: int | None = None  # Unix ts
    detail: str | None = None


class ReauthTotpRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class ReauthTotpResponse(BaseModel):
    kind: str  # 'ok' | 'invalid_code' | 'locked'
    totp_issued_at: int | None = None
    detail: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class RefreshResponse(BaseModel):
    kind: str
    admin_jwt: str | None = None
    refresh_token: str | None = None
    refresh_expires_at: datetime | None = None
    detail: str | None = None


class LogoutResponse(BaseModel):
    ok: bool = True


class MeResponse(BaseModel):
    id: int
    email: EmailStr
    status: str
    totp_enrolled: bool
    last_login_at: datetime | None = None
    last_login_ip: str | None = None

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for _cloud_jwt_auth fail-fast behaviour.

Cloud JWTs (issued by /auth/login) are accepted as an alternate to api_key
Bearer tokens. Every cloud tenant is provisioned with a 'default' project
in the same registration transaction (see _create_registration in
cloud_auth.py). When that row is missing or the engine is misconfigured,
_cloud_jwt_auth must fail closed (HTTP 500) instead of synthesising a
placeholder project_id that would silently desynchronise scope filtering.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from engramia.api.auth import _cloud_jwt_auth

pytestmark = pytest.mark.security


_FAKE_PAYLOAD = {
    "sub": "user-abc",
    "tenant_id": "testuser",
    "email": "test@example.com",
    "role": "owner",
    "type": "access",
}


def _make_request(engine):
    request = MagicMock()
    request.app.state.auth_engine = engine
    request.client.host = "127.0.0.1"
    request.state = MagicMock()
    return request


@patch("engramia.api.cloud_auth._decode_token", return_value=_FAKE_PAYLOAD)
def test_cloud_jwt_auth_resolves_default_project(mock_decode):
    """Happy path: 'default' project row exists, scope is built from it."""
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value.fetchone.return_value = ("proj-real-id",)

    request = _make_request(engine)
    _cloud_jwt_auth(request, "fake.jwt.token")

    assert request.state.auth_context.project_id == "proj-real-id"
    assert request.state.auth_context.tenant_id == "testuser"


@patch("engramia.api.cloud_auth._decode_token", return_value=_FAKE_PAYLOAD)
def test_cloud_jwt_auth_500_when_engine_missing(mock_decode):
    """No DB engine on app state → 500 (deploy is misconfigured, fail closed)."""
    request = _make_request(engine=None)

    with pytest.raises(HTTPException) as exc_info:
        _cloud_jwt_auth(request, "fake.jwt.token")

    assert exc_info.value.status_code == 500
    assert "database engine not configured" in exc_info.value.detail


@patch("engramia.api.cloud_auth._decode_token", return_value=_FAKE_PAYLOAD)
def test_cloud_jwt_auth_500_when_default_project_missing(mock_decode):
    """Tenant has a JWT but no 'default' project row → 500 (regression guard).

    Pre-2026-05 this branch silently fell back to project_id=f'default-{tenant_id}'.
    The synthetic value would let queries succeed but spread tenant data across
    a shadow project_id that no real row matches — scope filtering would still
    be tenant-tight, but cross-deploy promotions/exports would diverge.
    """
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value.fetchone.return_value = None

    request = _make_request(engine)

    with pytest.raises(HTTPException) as exc_info:
        _cloud_jwt_auth(request, "fake.jwt.token")

    assert exc_info.value.status_code == 500
    assert "default project missing" in exc_info.value.detail


@patch("engramia.api.cloud_auth._decode_token", return_value=_FAKE_PAYLOAD)
def test_cloud_jwt_auth_500_on_db_error(mock_decode):
    """Project lookup raises (DB connection issue, etc.) → 500, never recover."""
    engine = MagicMock()
    engine.connect.side_effect = RuntimeError("connection refused")

    request = _make_request(engine)

    with pytest.raises(HTTPException) as exc_info:
        _cloud_jwt_auth(request, "fake.jwt.token")

    assert exc_info.value.status_code == 500
    assert "project lookup error" in exc_info.value.detail

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Integration tests for the GDPR DSR HTTP routes.

The class-level ``DSRTracker`` is well-covered by
``tests/test_governance_dsr.py`` (29 tests). This file covers what those
tests do not: the three FastAPI routes that wrap the tracker:

  - ``POST /v1/governance/dsr``        — requires ``governance:write``
  - ``GET  /v1/governance/dsr``        — requires ``governance:read``
  - ``PATCH /v1/governance/dsr/{id}``  — requires ``governance:write``

Specifically:
  - RBAC enforcement matrix (reader/editor → 403; admin/owner → 200/201)
  - Tenant isolation: list returns only your-tenant DSRs; PATCH on a
    different tenant's DSR returns 403 (not 404, so info is not leaked)
  - Pydantic validation: bogus request_type / status → 422
  - 404 on unknown ``dsr_id``
  - The status state-machine: pending → in_progress → completed
  - Filter/limit query params propagate to the tracker
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engramia import Memory
from engramia.api.auth import require_auth
from engramia.api.governance import router as gov_router
from engramia.providers.json_storage import JSONStorage
from tests.conftest import FakeEmbeddings
from tests.factories import make_auth_dep

pytestmark = pytest.mark.security


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_dsr_in_memory_store():
    """Reset the module-level dev fallback between tests for full isolation."""
    from engramia.governance import dsr as dsr_module

    dsr_module._mem_store.clear()
    yield
    dsr_module._mem_store.clear()


@pytest.fixture
def storage(tmp_path) -> JSONStorage:
    return JSONStorage(path=tmp_path)


def _make_app(
    storage,
    role: str = "admin",
    tenant_id: str = "tenant-a",
    project_id: str = "proj-a",
) -> FastAPI:
    app = FastAPI()
    mem = Memory(embeddings=FakeEmbeddings(), storage=storage)
    app.state.memory = mem
    # auth_engine = None → DSRTracker uses its in-memory store. Perfect for
    # exercising the HTTP layer without provisioning a Postgres container.
    app.state.auth_engine = None
    app.dependency_overrides[require_auth] = make_auth_dep(
        role=role, tenant_id=tenant_id, project_id=project_id
    )
    app.include_router(gov_router, prefix="/v1")
    return app


def _client(storage, role="admin", tenant_id="tenant-a", project_id="proj-a") -> TestClient:
    return TestClient(_make_app(storage, role, tenant_id, project_id))


_VALID_BODY = {
    "request_type": "access",
    "subject_email": "subject@example.com",
    "handler_notes": "Filed via support@",
}


# ---------------------------------------------------------------------------
# POST /v1/governance/dsr — create
# ---------------------------------------------------------------------------


class TestCreateDSRPermissions:
    def test_reader_forbidden(self, storage):
        resp = _client(storage, "reader").post("/v1/governance/dsr", json=_VALID_BODY)
        assert resp.status_code == 403
        assert "governance:write" in resp.json()["detail"]

    def test_editor_forbidden(self, storage):
        resp = _client(storage, "editor").post("/v1/governance/dsr", json=_VALID_BODY)
        assert resp.status_code == 403

    def test_admin_can_create(self, storage):
        resp = _client(storage, "admin").post("/v1/governance/dsr", json=_VALID_BODY)
        assert resp.status_code == 201, resp.text

    def test_owner_can_create(self, storage):
        resp = _client(storage, "owner").post("/v1/governance/dsr", json=_VALID_BODY)
        assert resp.status_code == 201


class TestCreateDSRValidation:
    def test_unknown_request_type_returns_422(self, storage):
        resp = _client(storage, "admin").post(
            "/v1/governance/dsr", json={**_VALID_BODY, "request_type": "delete-me-now"}
        )
        assert resp.status_code == 422

    def test_missing_request_type_returns_422(self, storage):
        body = dict(_VALID_BODY)
        body.pop("request_type")
        resp = _client(storage, "admin").post("/v1/governance/dsr", json=body)
        assert resp.status_code == 422

    def test_subject_email_too_long_returns_422(self, storage):
        resp = _client(storage, "admin").post(
            "/v1/governance/dsr",
            json={**_VALID_BODY, "subject_email": "a" * 400},
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("rt", ["access", "erasure", "portability", "rectification"])
    def test_all_canonical_request_types_accepted(self, storage, rt):
        resp = _client(storage, "admin").post(
            "/v1/governance/dsr", json={**_VALID_BODY, "request_type": rt}
        )
        assert resp.status_code == 201, f"{rt} should be valid: {resp.text}"
        assert resp.json()["request_type"] == rt


class TestCreateDSRBody:
    def test_response_carries_pending_status_and_due_at(self, storage):
        resp = _client(storage, "admin").post("/v1/governance/dsr", json=_VALID_BODY)
        body = resp.json()
        assert body["status"] == "pending"
        assert body["tenant_id"] == "tenant-a"
        assert body["subject_email"] == "subject@example.com"
        # 30-day SLA — due_at must be after created_at.
        assert body["due_at"] > body["created_at"]
        assert body["overdue"] is False

    def test_response_id_is_uuid_like(self, storage):
        import re

        resp = _client(storage, "admin").post("/v1/governance/dsr", json=_VALID_BODY)
        body = resp.json()
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            body["id"],
        )


# ---------------------------------------------------------------------------
# GET /v1/governance/dsr — list
# ---------------------------------------------------------------------------


class TestListDSRPermissions:
    def test_reader_forbidden(self, storage):
        resp = _client(storage, "reader").get("/v1/governance/dsr")
        assert resp.status_code == 403
        assert "governance:read" in resp.json()["detail"]

    def test_editor_forbidden(self, storage):
        resp = _client(storage, "editor").get("/v1/governance/dsr")
        assert resp.status_code == 403

    def test_admin_can_list(self, storage):
        resp = _client(storage, "admin").get("/v1/governance/dsr")
        assert resp.status_code == 200
        assert resp.json()["requests"] == []

    def test_owner_can_list(self, storage):
        resp = _client(storage, "owner").get("/v1/governance/dsr")
        assert resp.status_code == 200


class TestListDSRTenantIsolation:
    def test_tenant_a_cannot_see_tenant_b_dsrs(self, storage):
        # Tenant A creates a DSR.
        _client(storage, "admin", tenant_id="tenant-a").post(
            "/v1/governance/dsr", json={**_VALID_BODY, "subject_email": "a@a.cz"}
        )
        # Tenant B creates a DSR.
        _client(storage, "admin", tenant_id="tenant-b").post(
            "/v1/governance/dsr", json={**_VALID_BODY, "subject_email": "b@b.cz"}
        )

        # Tenant A listing must see ONLY their own row.
        resp = _client(storage, "admin", tenant_id="tenant-a").get(
            "/v1/governance/dsr"
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["requests"][0]["subject_email"] == "a@a.cz"
        assert body["requests"][0]["tenant_id"] == "tenant-a"

    def test_pending_counts_scoped_to_tenant(self, storage):
        for _ in range(3):
            _client(storage, "admin", tenant_id="tenant-a").post(
                "/v1/governance/dsr", json=_VALID_BODY
            )
        # Tenant B has 1, distinct.
        _client(storage, "admin", tenant_id="tenant-b").post(
            "/v1/governance/dsr", json=_VALID_BODY
        )

        resp = _client(storage, "admin", tenant_id="tenant-a").get(
            "/v1/governance/dsr"
        )
        body = resp.json()
        assert body["total"] == 3
        # Pending counts should reflect only tenant-a's open DSRs.
        assert body["pending_counts"].get("pending", 0) == 3


class TestListDSRFilters:
    def test_status_filter_pattern_validated(self, storage):
        resp = _client(storage, "admin").get(
            "/v1/governance/dsr", params={"status": "garbage"}
        )
        assert resp.status_code == 422

    def test_overdue_only_filter(self, storage):
        # Create a fresh one — never overdue under default 30-day SLA.
        _client(storage, "admin").post("/v1/governance/dsr", json=_VALID_BODY)
        resp = _client(storage, "admin").get(
            "/v1/governance/dsr", params={"overdue_only": "true"}
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_limit_bounded(self, storage):
        # limit=0 → 422 (ge=1)
        resp = _client(storage, "admin").get("/v1/governance/dsr", params={"limit": 0})
        assert resp.status_code == 422
        # limit=501 → 422 (le=500)
        resp = _client(storage, "admin").get("/v1/governance/dsr", params={"limit": 501})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /v1/governance/dsr/{id} — update
# ---------------------------------------------------------------------------


def _create_and_get_id(storage, role="admin", tenant_id="tenant-a") -> str:
    resp = _client(storage, role, tenant_id=tenant_id).post(
        "/v1/governance/dsr", json=_VALID_BODY
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


class TestUpdateDSRPermissions:
    def test_reader_forbidden(self, storage):
        dsr_id = _create_and_get_id(storage)
        resp = _client(storage, "reader").patch(
            f"/v1/governance/dsr/{dsr_id}",
            json={"status": "in_progress"},
        )
        assert resp.status_code == 403

    def test_editor_forbidden(self, storage):
        dsr_id = _create_and_get_id(storage)
        resp = _client(storage, "editor").patch(
            f"/v1/governance/dsr/{dsr_id}", json={"status": "in_progress"}
        )
        assert resp.status_code == 403

    def test_admin_can_update_own_tenant(self, storage):
        dsr_id = _create_and_get_id(storage)
        resp = _client(storage, "admin").patch(
            f"/v1/governance/dsr/{dsr_id}", json={"status": "in_progress"}
        )
        assert resp.status_code == 200


class TestUpdateDSRStateMachine:
    def test_pending_to_in_progress_to_completed(self, storage):
        dsr_id = _create_and_get_id(storage)
        c = _client(storage, "admin")

        r1 = c.patch(f"/v1/governance/dsr/{dsr_id}", json={"status": "in_progress"})
        assert r1.status_code == 200
        assert r1.json()["status"] == "in_progress"

        r2 = c.patch(
            f"/v1/governance/dsr/{dsr_id}",
            json={"status": "completed", "handler_notes": "All data exported."},
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "completed"
        assert r2.json()["completed_at"] is not None

    def test_invalid_status_returns_422(self, storage):
        dsr_id = _create_and_get_id(storage)
        resp = _client(storage, "admin").patch(
            f"/v1/governance/dsr/{dsr_id}", json={"status": "deleted"}
        )
        assert resp.status_code == 422

    def test_handler_notes_appended(self, storage):
        dsr_id = _create_and_get_id(storage)
        c = _client(storage, "admin")
        c.patch(f"/v1/governance/dsr/{dsr_id}", json={"status": "in_progress", "handler_notes": "Step 1"})
        r2 = c.patch(f"/v1/governance/dsr/{dsr_id}", json={"status": "completed", "handler_notes": "Step 2"})
        body = r2.json()
        # Append, not replace — both notes must be visible.
        assert "Step 1" in body["handler_notes"]
        assert "Step 2" in body["handler_notes"]


class TestUpdateDSRNotFoundAndCrossTenant:
    def test_unknown_dsr_id_returns_404(self, storage):
        resp = _client(storage, "admin").patch(
            "/v1/governance/dsr/00000000-0000-0000-0000-000000000000",
            json={"status": "in_progress"},
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_other_tenant_dsr_returns_403(self, storage):
        """Tenant B may not modify Tenant A's DSR — info must not leak as 404."""
        dsr_id = _create_and_get_id(storage, role="admin", tenant_id="tenant-a")
        resp = _client(storage, "admin", tenant_id="tenant-b").patch(
            f"/v1/governance/dsr/{dsr_id}", json={"status": "in_progress"}
        )
        assert resp.status_code == 403
        assert "your tenant" in resp.json()["detail"].lower()

    def test_owner_cross_tenant_still_403(self, storage):
        """`owner` role does NOT mean 'all tenants' — wildcard is per-permission."""
        dsr_id = _create_and_get_id(storage, role="admin", tenant_id="tenant-a")
        resp = _client(storage, "owner", tenant_id="tenant-b").patch(
            f"/v1/governance/dsr/{dsr_id}", json={"status": "in_progress"}
        )
        assert resp.status_code == 403

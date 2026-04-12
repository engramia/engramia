# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""P0-4 + P0-5: RBAC enforcement tests for governance endpoints.

Root cause patched: the existing TestGovernanceAPI fixture uses
    app.dependency_overrides[require_auth] = lambda: None
which leaves request.state.auth_context = None, causing every
"if auth_ctx is not None" guard in governance.py to be silently skipped.
These tests set a real AuthContext so the permission and ownership checks
are exercised.

P0-4 — require_permission guards on governance endpoints:
  - reader / editor → 403 on governance:read (GET /retention)
  - reader / editor → 403 on governance:write (PUT /patterns/.../classify)
  - reader / editor → 403 on governance:delete (DELETE /projects/{id})
  - admin → 200 on governance:read endpoints
  - admin → 403 on cross-project delete (project_id != own project)
  - admin → 200 on own-project delete
  - owner → 200 on any-project delete (wildcard role)

P0-5 — DELETE /v1/governance/tenants/{tenant_id}:
  - admin → 403 (lacks "*" permission)
  - owner of tenant-a trying to delete tenant-b → 403
  - owner deleting own tenant → 200
"""

import time

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
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def storage(tmp_path) -> JSONStorage:
    return JSONStorage(path=tmp_path)


@pytest.fixture
def mem(storage) -> Memory:
    return Memory(embeddings=FakeEmbeddings(), storage=storage)


def _make_app(
    storage,
    role: str,
    tenant_id: str = "tenant-a",
    project_id: str = "proj-a",
) -> FastAPI:
    """Governance-only app with real RBAC (auth_context properly injected)."""
    app = FastAPI()
    mem = Memory(embeddings=FakeEmbeddings(), storage=storage)
    app.state.memory = mem
    app.state.auth_engine = None  # no DB — governance service layer uses JSON storage

    app.dependency_overrides[require_auth] = make_auth_dep(role=role, tenant_id=tenant_id, project_id=project_id)
    app.include_router(gov_router, prefix="/v1")
    return app


def _client(storage, role, tenant_id="tenant-a", project_id="proj-a") -> TestClient:
    return TestClient(_make_app(storage, role, tenant_id, project_id))


# ---------------------------------------------------------------------------
# P0-4a: require_permission guards — GET /v1/governance/retention
# Requires "governance:read" — admin only
# ---------------------------------------------------------------------------


class TestRetentionReadPermission:
    def test_reader_cannot_read_retention(self, storage):
        resp = _client(storage, "reader").get("/v1/governance/retention")
        assert resp.status_code == 403
        assert "governance:read" in resp.json()["detail"]

    def test_editor_cannot_read_retention(self, storage):
        resp = _client(storage, "editor").get("/v1/governance/retention")
        assert resp.status_code == 403

    def test_admin_can_read_retention(self, storage):
        resp = _client(storage, "admin").get("/v1/governance/retention")
        assert resp.status_code == 200

    def test_owner_can_read_retention(self, storage):
        resp = _client(storage, "owner").get("/v1/governance/retention")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# P0-4b: require_permission guards — PUT /v1/governance/retention
# Requires "governance:write"
# ---------------------------------------------------------------------------


class TestRetentionWritePermission:
    def test_reader_cannot_set_retention(self, storage):
        resp = _client(storage, "reader").put("/v1/governance/retention", json={"retention_days": 90})
        assert resp.status_code == 403

    def test_editor_cannot_set_retention(self, storage):
        resp = _client(storage, "editor").put("/v1/governance/retention", json={"retention_days": 90})
        assert resp.status_code == 403

    def test_admin_gets_501_not_403(self, storage):
        # Admin has governance:write — endpoint returns 501 (no DB engine), not 403
        resp = _client(storage, "admin").put("/v1/governance/retention", json={"retention_days": 90})
        assert resp.status_code == 501  # DB required, not a permission issue


# ---------------------------------------------------------------------------
# P0-4c: require_permission guards — PUT /v1/governance/patterns/.../classify
# Requires "governance:write"
# ---------------------------------------------------------------------------


class TestClassifyPermission:
    def _stored_key(self, mem: Memory) -> str:
        """Learn a pattern in the tenant-a scope used by _client()."""
        from engramia._context import reset_scope, set_scope
        from engramia.types import Scope

        token = set_scope(Scope(tenant_id="tenant-a", project_id="proj-a"))
        try:
            mem.learn(task="RBAC classify test", code="pass", eval_score=7.0)
            matches = mem.recall(task="RBAC classify test", limit=1)
            return matches[0].pattern_key
        finally:
            reset_scope(token)

    def test_reader_cannot_classify(self, storage, mem):
        key = self._stored_key(mem)
        resp = _client(storage, "reader").put(
            f"/v1/governance/patterns/{key}/classify",
            json={"classification": "confidential"},
        )
        assert resp.status_code == 403

    def test_editor_cannot_classify(self, storage, mem):
        key = self._stored_key(mem)
        resp = _client(storage, "editor").put(
            f"/v1/governance/patterns/{key}/classify",
            json={"classification": "confidential"},
        )
        assert resp.status_code == 403

    def test_admin_can_classify(self, storage, mem):
        key = self._stored_key(mem)
        resp = _client(storage, "admin").put(
            f"/v1/governance/patterns/{key}/classify",
            json={"classification": "confidential"},
        )
        assert resp.status_code == 200
        assert resp.json()["classification"] == "confidential"


# ---------------------------------------------------------------------------
# P0-4d: require_permission guards — DELETE /v1/governance/projects/{id}
# Requires "governance:delete"
# ---------------------------------------------------------------------------


class TestProjectDeletePermission:
    def test_reader_cannot_delete_project(self, storage):
        resp = _client(storage, "reader").delete("/v1/governance/projects/proj-a")
        assert resp.status_code == 403

    def test_editor_cannot_delete_project(self, storage):
        resp = _client(storage, "editor").delete("/v1/governance/projects/proj-a")
        assert resp.status_code == 403

    def test_admin_can_delete_own_project(self, storage):
        # Admin (project_id=proj-a) deletes proj-a → 200
        resp = _client(storage, "admin", project_id="proj-a").delete("/v1/governance/projects/proj-a")
        assert resp.status_code == 200

    def test_admin_cannot_delete_other_project(self, storage):
        """Critical security check: admin scoped to proj-a cannot delete proj-b."""
        resp = _client(storage, "admin", project_id="proj-a").delete("/v1/governance/projects/proj-b")
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert "owner" in detail.lower() or "cross-project" in detail.lower() or "own project" in detail.lower()

    def test_owner_can_delete_any_project(self, storage):
        """Owner role bypasses the cross-project guard."""
        # Owner scoped to proj-a deletes proj-b — must succeed
        resp = _client(storage, "owner", project_id="proj-a").delete("/v1/governance/projects/proj-b")
        # 200 (project may be empty but deletion succeeds)
        assert resp.status_code == 200

    def test_admin_403_error_mentions_role(self, storage):
        resp = _client(storage, "admin", project_id="proj-a").delete("/v1/governance/projects/proj-b")
        assert resp.status_code == 403
        assert "admin" in resp.json()["detail"].lower() or "owner" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# P0-4e: require_permission guards — POST /v1/governance/retention/apply
# Requires "governance:admin"
# ---------------------------------------------------------------------------


class TestRetentionApplyPermission:
    def test_reader_cannot_apply_retention(self, storage):
        resp = _client(storage, "reader").post("/v1/governance/retention/apply", json={"dry_run": True})
        assert resp.status_code == 403

    def test_editor_cannot_apply_retention(self, storage):
        resp = _client(storage, "editor").post("/v1/governance/retention/apply", json={"dry_run": True})
        assert resp.status_code == 403

    def test_admin_can_apply_retention(self, storage):
        resp = _client(storage, "admin").post("/v1/governance/retention/apply", json={"dry_run": True})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# P0-5: DELETE /v1/governance/tenants/{tenant_id}
# Requires "*" (owner-only wildcard)
# ---------------------------------------------------------------------------


class TestTenantDeletePermission:
    def test_reader_cannot_delete_tenant(self, storage):
        resp = _client(storage, "reader").delete("/v1/governance/tenants/tenant-a")
        assert resp.status_code == 403

    def test_editor_cannot_delete_tenant(self, storage):
        resp = _client(storage, "editor").delete("/v1/governance/tenants/tenant-a")
        assert resp.status_code == 403

    def test_admin_cannot_delete_tenant(self, storage):
        """Admin has governance:delete but NOT '*' — must be blocked."""
        resp = _client(storage, "admin").delete("/v1/governance/tenants/tenant-a")
        assert resp.status_code == 403

    def test_owner_can_delete_own_tenant(self, storage):
        """Owner of tenant-a can delete tenant-a."""
        resp = _client(storage, "owner", tenant_id="tenant-a").delete("/v1/governance/tenants/tenant-a")
        assert resp.status_code == 200

    def test_owner_cannot_delete_foreign_tenant(self, storage):
        """Critical: owner of tenant-a must not be able to delete tenant-b."""
        resp = _client(storage, "owner", tenant_id="tenant-a").delete("/v1/governance/tenants/tenant-b")
        assert resp.status_code == 403
        assert "own tenant" in resp.json()["detail"].lower()

    def test_owner_delete_returns_deletion_summary(self, storage):
        # Seed a pattern for tenant-a so the response has something to report
        storage.save(
            "patterns/tenant_del_test",
            {
                "task": "tenant delete test",
                "design": {},
                "success_score": 7.0,
                "reuse_count": 0,
                "timestamp": time.time(),
            },
        )
        resp = _client(storage, "owner", tenant_id="tenant-a").delete("/v1/governance/tenants/tenant-a")
        assert resp.status_code == 200
        data = resp.json()
        # Response must include deletion summary fields
        assert "patterns_deleted" in data
        assert "tenant_id" in data

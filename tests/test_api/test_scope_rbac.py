# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for Phase 5.1 + 5.2: scope isolation and RBAC permission system.

Covers:
- Scope contextvar: get/set/reset, default scope, per-request isolation
- JSONStorage scope-aware paths: default scope backward compat, non-default scope subdirs
- JSONStorage cross-scope isolation: data written in one scope not visible in another
- RBAC permissions: require_permission dependency for each role
- Auth: env-var dev mode still works (backward compat)
- Quota enforcement: 429 when count >= max_patterns
"""

import os
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engramia import Memory
from engramia._context import get_scope, reset_scope, set_scope
from engramia.api.permissions import PERMISSIONS
from engramia.providers.json_storage import JSONStorage
from engramia.types import AuthContext, Scope
from tests.conftest import FakeEmbeddings
from tests.factories import make_auth_dep

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_auth_env():
    """Reset auth env vars after each test to prevent leakage."""
    yield
    os.environ.pop("ENGRAMIA_API_KEYS", None)
    os.environ.pop("ENGRAMIA_ALLOW_NO_AUTH", None)


@pytest.fixture
def tmp_storage(tmp_path):
    return JSONStorage(path=tmp_path)


@pytest.fixture
def make_memory(tmp_path):
    def _make(tenant_id="default", project_id="default"):
        storage = JSONStorage(path=tmp_path)
        return Memory(embeddings=FakeEmbeddings(), storage=storage)

    return _make


def _make_auth_app(role: str = "editor", max_patterns: int | None = None):
    """Build a minimal FastAPI app with a pre-set auth_context (no real DB)."""
    from engramia.api.auth import require_auth
    from engramia.api.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/v1")

    app.dependency_overrides[require_auth] = make_auth_dep(
        role=role,
        tenant_id="acme",
        project_id="prod",
        max_patterns=max_patterns,
    )
    return app


# ---------------------------------------------------------------------------
# Scope contextvar tests
# ---------------------------------------------------------------------------


class TestScopeContextvar:
    def test_default_scope_is_default_tenant_project(self):
        scope = get_scope()
        assert scope.tenant_id == "default"
        assert scope.project_id == "default"

    def test_set_scope_changes_current_scope(self):
        new_scope = Scope(tenant_id="acme", project_id="prod")
        token = set_scope(new_scope)
        try:
            assert get_scope().tenant_id == "acme"
            assert get_scope().project_id == "prod"
        finally:
            reset_scope(token)

    def test_reset_scope_restores_previous(self):
        original = get_scope()
        token = set_scope(Scope(tenant_id="x", project_id="y"))
        reset_scope(token)
        restored = get_scope()
        assert restored.tenant_id == original.tenant_id
        assert restored.project_id == original.project_id

    def test_scope_is_thread_local(self):
        """Each thread starts with its own (default) scope."""
        results: list[str] = []

        def worker(tid: str):
            token = set_scope(Scope(tenant_id=tid, project_id="p"))
            try:
                results.append(get_scope().tenant_id)
            finally:
                reset_scope(token)

        threads = [threading.Thread(target=worker, args=(f"tenant-{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each thread should have seen its own tenant
        assert sorted(results) == sorted([f"tenant-{i}" for i in range(5)])


# ---------------------------------------------------------------------------
# JSONStorage scope isolation tests
# ---------------------------------------------------------------------------


class TestJSONStorageScopeIsolation:
    def test_default_scope_uses_root_directly(self, tmp_path):
        """Default scope writes to {root}/patterns/key.json (backward compat)."""
        storage = JSONStorage(path=tmp_path)
        storage.save("patterns/test", {"data": "hello"})
        # File should be at root level, not in a subdirectory
        assert (tmp_path / "patterns" / "test.json").exists()

    def test_non_default_scope_uses_subdirectory(self, tmp_path):
        """Non-default scope writes to {root}/{tenant}/{project}/patterns/key.json."""
        storage = JSONStorage(path=tmp_path)
        token = set_scope(Scope(tenant_id="acme", project_id="prod"))
        try:
            storage.save("patterns/test", {"data": "acme"})
            assert (tmp_path / "acme" / "prod" / "patterns" / "test.json").exists()
        finally:
            reset_scope(token)

    def test_cross_scope_data_isolation(self, tmp_path):
        """Data written in scope A is NOT visible when reading in scope B."""
        storage = JSONStorage(path=tmp_path)

        # Write in scope A
        token_a = set_scope(Scope(tenant_id="tenant-a", project_id="proj"))
        try:
            storage.save("patterns/secret", {"payload": "tenant-a secret"})
        finally:
            reset_scope(token_a)

        # Read in scope B — must return None
        token_b = set_scope(Scope(tenant_id="tenant-b", project_id="proj"))
        try:
            result = storage.load("patterns/secret")
            assert result is None, "Cross-tenant data leak: tenant-b read tenant-a's data"
        finally:
            reset_scope(token_b)

    def test_default_scope_does_not_see_tenant_data(self, tmp_path):
        """Default scope cannot read data written by a named tenant."""
        storage = JSONStorage(path=tmp_path)

        token = set_scope(Scope(tenant_id="acme", project_id="prod"))
        try:
            storage.save("patterns/private", {"secret": True})
        finally:
            reset_scope(token)

        # In default scope, key must not exist
        result = storage.load("patterns/private")
        assert result is None

    def test_list_keys_scoped(self, tmp_path):
        """list_keys() only returns keys within the current scope."""
        storage = JSONStorage(path=tmp_path)

        # Write in tenant-a
        token_a = set_scope(Scope(tenant_id="tenant-a", project_id="p"))
        try:
            storage.save("patterns/a1", {"x": 1})
            storage.save("patterns/a2", {"x": 2})
        finally:
            reset_scope(token_a)

        # Write in tenant-b
        token_b = set_scope(Scope(tenant_id="tenant-b", project_id="p"))
        try:
            storage.save("patterns/b1", {"x": 3})
        finally:
            reset_scope(token_b)

        # List from tenant-a should only see a1, a2
        token_a2 = set_scope(Scope(tenant_id="tenant-a", project_id="p"))
        try:
            keys = storage.list_keys("patterns/")
            assert sorted(keys) == ["patterns/a1", "patterns/a2"]
        finally:
            reset_scope(token_a2)

    def test_delete_scoped(self, tmp_path):
        """delete() in scope A cannot remove data from scope B."""
        storage = JSONStorage(path=tmp_path)

        # Write in tenant-a
        token_a = set_scope(Scope(tenant_id="tenant-a", project_id="p"))
        try:
            storage.save("patterns/victim", {"v": 1})
        finally:
            reset_scope(token_a)

        # Try to delete with same key from tenant-b (should silently no-op)
        token_b = set_scope(Scope(tenant_id="tenant-b", project_id="p"))
        try:
            storage.delete("patterns/victim")
        finally:
            reset_scope(token_b)

        # Data in tenant-a must still exist
        token_a2 = set_scope(Scope(tenant_id="tenant-a", project_id="p"))
        try:
            result = storage.load("patterns/victim")
            assert result == {"v": 1}
        finally:
            reset_scope(token_a2)

    def test_count_patterns_scoped(self, tmp_path):
        """count_patterns() only counts keys in the current scope."""
        storage = JSONStorage(path=tmp_path)

        token_a = set_scope(Scope(tenant_id="t-a", project_id="p"))
        try:
            storage.save("patterns/x1", {})
            storage.save("patterns/x2", {})
            storage.save("patterns/x3", {})
        finally:
            reset_scope(token_a)

        # Default scope sees 0
        assert storage.count_patterns("patterns/") == 0

        # tenant-a sees 3
        token_a2 = set_scope(Scope(tenant_id="t-a", project_id="p"))
        try:
            assert storage.count_patterns("patterns/") == 3
        finally:
            reset_scope(token_a2)

    def test_embedding_search_scoped(self, tmp_path):
        """search_similar() only searches embeddings in the current scope."""
        storage = JSONStorage(path=tmp_path)
        vec = [0.1] * 10 + [0.0] * 22  # 32-dim fake vector

        # Save embedding in scope A
        token_a = set_scope(Scope(tenant_id="t-search-a", project_id="p"))
        try:
            storage.save("patterns/emb", {})
            storage.save_embedding("patterns/emb", vec)
        finally:
            reset_scope(token_a)

        # Search from scope B must return nothing
        token_b = set_scope(Scope(tenant_id="t-search-b", project_id="p"))
        try:
            results = storage.search_similar(vec, limit=5)
            assert results == [], f"Cross-scope embedding leak: {results}"
        finally:
            reset_scope(token_b)


# ---------------------------------------------------------------------------
# RBAC permission tests
# ---------------------------------------------------------------------------


@pytest.mark.security
class TestPermissions:
    def test_reader_cannot_learn(self):
        assert "learn" not in PERMISSIONS["reader"]

    def test_reader_can_recall(self):
        assert "recall" in PERMISSIONS["reader"]

    def test_editor_can_learn(self):
        assert "learn" in PERMISSIONS["editor"]

    def test_editor_cannot_delete_any_pattern(self):
        assert "patterns:delete" not in PERMISSIONS["editor"]

    def test_editor_has_delete_own_permission(self):
        assert "patterns:delete_own" in PERMISSIONS["editor"]

    def test_admin_can_delete_and_manage_keys(self):
        assert "patterns:delete" in PERMISSIONS["admin"]
        assert "keys:create" in PERMISSIONS["admin"]
        assert "keys:revoke" in PERMISSIONS["admin"]

    def test_owner_has_wildcard(self):
        assert "*" in PERMISSIONS["owner"]

    def test_hierarchy_is_strict_subset(self):
        """reader ⊂ editor ⊂ admin."""
        assert PERMISSIONS["reader"] < PERMISSIONS["editor"]
        assert PERMISSIONS["editor"] < PERMISSIONS["admin"]

    def test_permission_dependency_allows_correct_role(self, tmp_path):
        """An editor role can call /learn."""
        storage = JSONStorage(path=tmp_path)
        app = _make_auth_app(role="editor")
        app.state.memory = Memory(embeddings=FakeEmbeddings(), storage=storage)

        client = TestClient(app)
        resp = client.post(
            "/v1/learn",
            json={"task": "test task", "code": "print('hi')", "eval_score": 8.0},
        )
        assert resp.status_code == 200

    def test_permission_dependency_blocks_wrong_role(self, tmp_path):
        """A reader role cannot call /learn (requires 'learn' permission)."""
        storage = JSONStorage(path=tmp_path)
        app = _make_auth_app(role="reader")
        app.state.memory = Memory(embeddings=FakeEmbeddings(), storage=storage)

        client = TestClient(app)
        resp = client.post(
            "/v1/learn",
            json={"task": "test task", "code": "print('hi')", "eval_score": 8.0},
        )
        assert resp.status_code == 403
        assert "reader" in resp.json()["detail"]

    def test_reader_can_call_health(self, tmp_path):
        storage = JSONStorage(path=tmp_path)
        app = _make_auth_app(role="reader")
        app.state.memory = Memory(embeddings=FakeEmbeddings(), storage=storage)

        client = TestClient(app)
        resp = client.get("/v1/health")
        assert resp.status_code == 200

    def test_reader_cannot_delete_pattern(self, tmp_path):
        storage = JSONStorage(path=tmp_path)
        app = _make_auth_app(role="reader")
        app.state.memory = Memory(embeddings=FakeEmbeddings(), storage=storage)

        client = TestClient(app)
        resp = client.delete("/v1/patterns/patterns/some-key")
        assert resp.status_code == 403

    def test_editor_can_delete_own_pattern(self, tmp_path):
        """Editor can delete a pattern they authored."""
        from engramia.api.auth import require_auth

        storage = JSONStorage(path=tmp_path)
        app = _make_auth_app(role="editor")
        mem = Memory(embeddings=FakeEmbeddings(), storage=storage)
        app.state.memory = mem

        # Override auth with key_id matching the author
        app.dependency_overrides[require_auth] = make_auth_dep(
            role="editor", key_id="editor-key-1",
            tenant_id="acme", project_id="prod",
        )

        client = TestClient(app)
        # Learn a pattern (will be authored by editor-key-1 via learn route)
        resp = client.post("/v1/learn", json={
            "task": "Editor's own pattern", "code": "pass", "eval_score": 7.0,
        })
        assert resp.status_code == 200

        resp = client.post("/v1/recall", json={"task": "Editor's own pattern", "limit": 1})
        key = resp.json()["matches"][0]["pattern_key"]

        # Delete own pattern — should succeed
        resp = client.delete(f"/v1/patterns/{key}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_editor_cannot_delete_others_pattern(self, tmp_path):
        """Editor cannot delete a pattern created by a different key."""
        from engramia.api.auth import require_auth

        storage = JSONStorage(path=tmp_path)
        app = _make_auth_app(role="editor")
        mem = Memory(embeddings=FakeEmbeddings(), storage=storage)
        app.state.memory = mem

        # Learn as admin-key-1
        app.dependency_overrides[require_auth] = make_auth_dep(
            role="admin", key_id="admin-key-1",
            tenant_id="acme", project_id="prod",
        )
        client = TestClient(app)
        resp = client.post("/v1/learn", json={
            "task": "Admin's pattern", "code": "pass", "eval_score": 8.0,
        })
        assert resp.status_code == 200
        resp = client.post("/v1/recall", json={"task": "Admin's pattern", "limit": 1})
        key = resp.json()["matches"][0]["pattern_key"]

        # Switch to editor with different key_id
        app.dependency_overrides[require_auth] = make_auth_dep(
            role="editor", key_id="editor-key-2",
            tenant_id="acme", project_id="prod",
        )
        client = TestClient(app)
        resp = client.delete(f"/v1/patterns/{key}")
        assert resp.status_code == 403
        assert "editors can only delete" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Quota enforcement tests
# ---------------------------------------------------------------------------


@pytest.mark.security
class TestQuotaEnforcement:
    def test_quota_exceeded_returns_429(self, tmp_path):
        """When pattern count >= max_patterns, /learn returns 429."""
        storage = JSONStorage(path=tmp_path)
        # Pre-fill with patterns in the scope the auth dep will use (acme/prod)
        scope = Scope(tenant_id="acme", project_id="prod")
        token = set_scope(scope)
        try:
            for i in range(3):
                storage.save(f"patterns/existing_{i}", {"task": f"task {i}", "design": {}})
        finally:
            reset_scope(token)

        app = _make_auth_app(role="editor", max_patterns=3)
        app.state.memory = Memory(embeddings=FakeEmbeddings(), storage=storage)

        client = TestClient(app)
        resp = client.post(
            "/v1/learn",
            json={"task": "new task that exceeds quota", "code": "x=1", "eval_score": 7.0},
        )
        assert resp.status_code == 429
        body = resp.json()
        assert body["detail"]["error"] == "quota_exceeded"
        assert body["detail"]["current"] == 3
        assert body["detail"]["limit"] == 3

    def test_quota_not_enforced_without_auth_context(self, tmp_path):
        """In env-var auth mode (no auth_context), quota is never enforced."""
        from engramia.api.routes import router

        os.environ.pop("ENGRAMIA_API_KEYS", None)
        os.environ["ENGRAMIA_ALLOW_NO_AUTH"] = "true"
        storage = JSONStorage(path=tmp_path)
        # Fill beyond any quota
        for i in range(20):
            storage.save(f"patterns/existing_{i}", {"task": f"task {i}", "design": {}})

        app = FastAPI()
        app.include_router(router, prefix="/v1")
        app.state.memory = Memory(embeddings=FakeEmbeddings(), storage=storage)

        client = TestClient(app)
        # Should succeed — no quota in env-var mode
        resp = client.post(
            "/v1/learn",
            json={"task": "no quota task", "code": "x=1", "eval_score": 7.0},
        )
        assert resp.status_code == 200

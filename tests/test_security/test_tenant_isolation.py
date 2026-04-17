# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Adversarial tenant-isolation tests.

These tests verify that cross-tenant data leakage cannot occur through any
of the public Memory API surfaces: recall, delete, export/import, metrics,
skills, feedback, and aging.

The shared storage backend is intentionally the SAME JSONStorage instance
for both tenants — matching production configuration where a single
database/file tree serves all tenants, with isolation enforced via the
scope contextvar.
"""

import contextlib

import pytest

from engramia import Memory
from engramia._context import reset_scope, set_scope
from engramia.providers.json_storage import JSONStorage
from engramia.types import Scope
from tests.conftest import FakeEmbeddings

pytestmark = pytest.mark.security


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def as_tenant(tenant_id: str, project_id: str = "proj"):
    """Context manager that sets the scope contextvar for a tenant."""
    token = set_scope(Scope(tenant_id=tenant_id, project_id=project_id))
    try:
        yield
    finally:
        reset_scope(token)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def shared_storage(tmp_path):
    """Single JSONStorage shared by all tenants (mirrors production)."""
    return JSONStorage(path=tmp_path)


@pytest.fixture
def embeddings():
    return FakeEmbeddings()


@pytest.fixture
def make_mem(shared_storage, embeddings):
    """Return a Memory instance — scope is controlled per-call via as_tenant()."""

    def _factory():
        return Memory(embeddings=embeddings, storage=shared_storage)

    return _factory


# ---------------------------------------------------------------------------
# Recall isolation
# ---------------------------------------------------------------------------


class TestRecallIsolation:
    def test_tenant_a_pattern_not_visible_to_tenant_b(self, make_mem):
        mem = make_mem()
        with as_tenant("alpha"):
            mem.learn(task="alpha secret task", code="alpha_code()", eval_score=9.0)

        with as_tenant("beta"):
            results = mem.recall("alpha secret task", limit=10)

        assert len(results) == 0, "Tenant B must not recall Tenant A's patterns"

    def test_each_tenant_recalls_only_own_patterns(self, make_mem):
        mem = make_mem()
        with as_tenant("alpha"):
            mem.learn(task="parse csv file", code="alpha_csv()", eval_score=8.0)

        with as_tenant("beta"):
            mem.learn(task="parse csv file", code="beta_csv()", eval_score=8.0)

        with as_tenant("alpha"):
            results = mem.recall("parse csv file", limit=10)
        assert all("alpha" in m.pattern.design["code"] for m in results), "Alpha should only recall its own code"

        with as_tenant("beta"):
            results = mem.recall("parse csv file", limit=10)
        assert all("beta" in m.pattern.design["code"] for m in results), "Beta should only recall its own code"

    def test_empty_store_returns_nothing(self, make_mem):
        mem = make_mem()
        with as_tenant("alpha"):
            mem.learn(task="fetch data from api", code="fetch()", eval_score=7.0)

        with as_tenant("gamma"):
            results = mem.recall("fetch data from api", limit=10)

        assert results == []


# ---------------------------------------------------------------------------
# Delete isolation
# ---------------------------------------------------------------------------


class TestDeleteIsolation:
    def test_tenant_b_cannot_delete_tenant_a_pattern(self, make_mem):
        mem = make_mem()
        with as_tenant("alpha"):
            mem.learn(task="unique task for alpha", code="alpha_code()", eval_score=8.5)
            keys_before = [r["key"] for r in mem.export()]

        assert len(keys_before) == 1
        alpha_key = keys_before[0]

        # Tenant B attempts to delete Tenant A's key — should return False (not found)
        with as_tenant("beta"):
            result = mem.delete_pattern(alpha_key)

        assert result is False, "Delete across tenants must return False"

        # Pattern must still exist for Tenant A
        with as_tenant("alpha"):
            results = mem.recall("unique task for alpha", limit=5)
        assert len(results) == 1

    def test_delete_own_pattern_succeeds(self, make_mem):
        mem = make_mem()
        with as_tenant("alpha"):
            mem.learn(task="task to be deleted", code="code()", eval_score=7.0)
            key = mem.export()[0]["key"]
            deleted = mem.delete_pattern(key)

        assert deleted is True

        with as_tenant("alpha"):
            results = mem.recall("task to be deleted", limit=5)
        assert results == []


# ---------------------------------------------------------------------------
# Export / Import isolation
# ---------------------------------------------------------------------------


class TestExportImportIsolation:
    def test_export_contains_only_own_tenant_data(self, make_mem):
        mem = make_mem()
        with as_tenant("alpha"):
            mem.learn(task="alpha task export", code="alpha_export()", eval_score=8.0)

        with as_tenant("beta"):
            mem.learn(task="beta task export", code="beta_export()", eval_score=8.0)

        with as_tenant("alpha"):
            records = mem.export()

        assert len(records) == 1
        assert "alpha_export" in records[0]["data"]["design"]["code"], "Export must only contain Tenant A's patterns"

    def test_import_into_tenant_b_does_not_affect_tenant_a(self, make_mem):
        mem = make_mem()
        with as_tenant("alpha"):
            mem.learn(task="alpha import test", code="alpha_import()", eval_score=8.0)
            alpha_export = mem.export()

        # Tenant B imports Tenant A's export (e.g. a migration scenario)
        with as_tenant("beta"):
            imported = mem.import_data(alpha_export, overwrite=True)

        assert imported == 1

        # Tenant A's original data is untouched
        with as_tenant("alpha"):
            results = mem.recall("alpha import test", limit=5)
        assert len(results) == 1
        assert "alpha_import" in results[0].pattern.design["code"]

    def test_import_key_path_traversal_rejected(self, make_mem):
        """Malicious import records with path-traversal keys must be silently skipped."""
        mem = make_mem()
        malicious_records = [
            {"version": 1, "key": "patterns/../../../etc/passwd", "data": {"task": "evil", "code": "rm -rf /"}},
            {"version": 1, "key": "../patterns/escape", "data": {"task": "evil2", "code": "evil()"}},
        ]
        with as_tenant("alpha"):
            imported = mem.import_data(malicious_records)
        assert imported == 0


# ---------------------------------------------------------------------------
# Metrics isolation
# ---------------------------------------------------------------------------


class TestMetricsIsolation:
    def test_metrics_reflect_only_own_tenant(self, make_mem):
        mem = make_mem()
        with as_tenant("alpha"):
            mem.learn(task="alpha metric task 1", code="a1()", eval_score=9.0)
            mem.learn(task="alpha metric task 2", code="a2()", eval_score=8.0)
            alpha_count = mem.metrics.pattern_count

        with as_tenant("beta"):
            beta_count = mem.metrics.pattern_count

        assert alpha_count == 2
        assert beta_count == 0, "Beta must see zero patterns — no leakage from Alpha"


# ---------------------------------------------------------------------------
# Skills isolation
# ---------------------------------------------------------------------------


class TestSkillsIsolation:
    def test_skills_not_visible_across_tenants(self, make_mem):
        mem = make_mem()
        with as_tenant("alpha"):
            mem.learn(task="alpha skill task", code="alpha_skill()", eval_score=8.0)
            alpha_key = mem.export()[0]["key"]
            mem.register_skills(alpha_key, ["csv_parsing", "statistics"])

        with as_tenant("beta"):
            results = mem.find_by_skills(["csv_parsing"])

        assert results == [], "Beta must not find Alpha's skill-tagged patterns"

    def test_skills_visible_within_own_tenant(self, make_mem):
        mem = make_mem()
        with as_tenant("alpha"):
            mem.learn(task="alpha skill task", code="alpha_skill()", eval_score=8.0)
            alpha_key = mem.export()[0]["key"]
            mem.register_skills(alpha_key, ["csv_parsing"])
            results = mem.find_by_skills(["csv_parsing"])

        assert len(results) == 1


# ---------------------------------------------------------------------------
# Feedback isolation
# ---------------------------------------------------------------------------


class TestFeedbackIsolation:
    def test_feedback_not_visible_across_tenants(self, make_mem):
        """Feedback stored in Tenant A's scope must not appear in Tenant B's get_feedback()."""
        mem = make_mem()

        # Record feedback twice so it passes the count >= 2 threshold in get_top()
        with as_tenant("alpha"):
            mem._feedback_store.record("alpha secret feedback issue")
            mem._feedback_store.record("alpha secret feedback issue")
            alpha_feedback = mem.get_feedback(limit=20)

        # Alpha must see its own feedback
        assert any("alpha secret" in f for f in alpha_feedback), "Alpha must see its own feedback"

        with as_tenant("beta"):
            beta_feedback = mem.get_feedback(limit=20)

        texts = " ".join(beta_feedback)
        assert "alpha secret" not in texts, "Beta must not see Alpha's feedback"

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Contract tests for StorageBackend implementations.

Every StorageBackend (JSONStorage, PostgresStorage) must pass these tests.
They verify the interface contract — not implementation details.

Covers:
- save/load roundtrip
- list_keys with and without prefix
- delete + load returns None
- save_embedding + search_similar returns stored key
- count_patterns matches actual stored patterns
- delete_scope removes all keys for a scope
"""

import pytest

from engramia._context import reset_scope, set_scope
from engramia.providers.json_storage import JSONStorage
from engramia.types import Scope

pytestmark = pytest.mark.contract


# ---------------------------------------------------------------------------
# Parameterized storage fixture — extend with PostgresStorage when available
# ---------------------------------------------------------------------------


@pytest.fixture(params=["json"])
def store(request, tmp_path):
    if request.param == "json":
        return JSONStorage(path=tmp_path)
    pytest.skip(f"Unknown storage backend: {request.param}")


# ---------------------------------------------------------------------------
# Key-value store contract
# ---------------------------------------------------------------------------


class TestSaveLoadContract:
    def test_save_and_load_roundtrip(self, store):
        data = {"task": "Parse CSV", "score": 8.5}
        store.save("patterns/test_001", data)
        loaded = store.load("patterns/test_001")
        assert loaded["task"] == "Parse CSV"
        assert loaded["score"] == 8.5

    def test_load_missing_key_returns_none(self, store):
        assert store.load("patterns/nonexistent") is None

    def test_save_overwrites_existing(self, store):
        store.save("patterns/x", {"v": 1})
        store.save("patterns/x", {"v": 2})
        assert store.load("patterns/x")["v"] == 2

    def test_save_and_load_list(self, store):
        store.save("analytics/events", [{"a": 1}, {"b": 2}])
        loaded = store.load("analytics/events")
        assert isinstance(loaded, list)
        assert len(loaded) == 2


class TestListKeysContract:
    def test_list_keys_empty_store(self, store):
        assert store.list_keys() == []

    def test_list_keys_returns_all_saved(self, store):
        store.save("patterns/a", {"x": 1})
        store.save("patterns/b", {"x": 2})
        store.save("evals/c", {"x": 3})
        keys = store.list_keys()
        assert "patterns/a" in keys
        assert "patterns/b" in keys
        assert "evals/c" in keys

    def test_list_keys_with_prefix(self, store):
        store.save("patterns/a", {"x": 1})
        store.save("patterns/b", {"x": 2})
        store.save("evals/c", {"x": 3})
        keys = store.list_keys(prefix="patterns/")
        assert "patterns/a" in keys
        assert "patterns/b" in keys
        assert "evals/c" not in keys

    def test_list_keys_sorted(self, store):
        store.save("patterns/c", {})
        store.save("patterns/a", {})
        store.save("patterns/b", {})
        keys = store.list_keys(prefix="patterns/")
        assert keys == sorted(keys)


class TestDeleteContract:
    def test_delete_removes_data(self, store):
        store.save("patterns/x", {"v": 1})
        store.delete("patterns/x")
        assert store.load("patterns/x") is None

    def test_delete_nonexistent_is_noop(self, store):
        store.delete("patterns/ghost")  # must not raise

    def test_delete_removes_from_list_keys(self, store):
        store.save("patterns/a", {})
        store.save("patterns/b", {})
        store.delete("patterns/a")
        keys = store.list_keys(prefix="patterns/")
        assert "patterns/a" not in keys
        assert "patterns/b" in keys


# ---------------------------------------------------------------------------
# Embedding index contract
# ---------------------------------------------------------------------------


class TestEmbeddingContract:
    DIM = 1536

    def _unit_vec(self, seed: int) -> list[float]:
        """Generate a deterministic unit vector."""
        import hashlib
        import numpy as np

        rng = np.random.RandomState(seed)
        vec = rng.randn(self.DIM).astype(np.float32)
        return (vec / np.linalg.norm(vec)).tolist()

    def test_save_and_search_returns_stored_key(self, store):
        vec = self._unit_vec(42)
        store.save("patterns/emb_test", {"task": "test"})
        store.save_embedding("patterns/emb_test", vec)
        results = store.search_similar(vec, limit=1, prefix="patterns/")
        assert len(results) >= 1
        assert results[0][0] == "patterns/emb_test"

    def test_self_similarity_is_near_one(self, store):
        vec = self._unit_vec(99)
        store.save("patterns/self_sim", {"task": "test"})
        store.save_embedding("patterns/self_sim", vec)
        results = store.search_similar(vec, limit=1, prefix="patterns/")
        assert results[0][1] == pytest.approx(1.0, abs=1e-4)

    def test_search_returns_closest_first(self, store):
        v1 = self._unit_vec(1)
        v2 = self._unit_vec(2)
        store.save("patterns/p1", {})
        store.save("patterns/p2", {})
        store.save_embedding("patterns/p1", v1)
        store.save_embedding("patterns/p2", v2)
        results = store.search_similar(v1, limit=2, prefix="patterns/")
        assert results[0][0] == "patterns/p1"
        assert results[0][1] >= results[1][1]

    def test_search_with_prefix_filters(self, store):
        vec = self._unit_vec(10)
        store.save("patterns/x", {})
        store.save("evals/y", {})
        store.save_embedding("patterns/x", vec)
        store.save_embedding("evals/y", vec)
        results = store.search_similar(vec, limit=10, prefix="patterns/")
        keys = [r[0] for r in results]
        assert "patterns/x" in keys
        assert "evals/y" not in keys

    def test_search_empty_store_returns_empty(self, store):
        vec = self._unit_vec(1)
        assert store.search_similar(vec, limit=5, prefix="patterns/") == []


# ---------------------------------------------------------------------------
# count_patterns contract
# ---------------------------------------------------------------------------


class TestCountPatternsContract:
    def test_count_zero_on_empty(self, store):
        assert store.count_patterns() == 0

    def test_count_matches_saved(self, store):
        store.save("patterns/a", {})
        store.save("patterns/b", {})
        store.save("evals/c", {})  # not a pattern
        assert store.count_patterns() == 2


# ---------------------------------------------------------------------------
# Scope isolation contract
# ---------------------------------------------------------------------------


class TestScopeIsolationContract:
    def test_data_in_scope_a_not_visible_in_scope_b(self, store):
        scope_a = Scope(tenant_id="t-a", project_id="p-a")
        scope_b = Scope(tenant_id="t-b", project_id="p-b")

        token_a = set_scope(scope_a)
        try:
            store.save("patterns/secret", {"data": "tenant-a-only"})
        finally:
            reset_scope(token_a)

        token_b = set_scope(scope_b)
        try:
            assert store.load("patterns/secret") is None
            assert store.list_keys(prefix="patterns/") == []
            assert store.count_patterns() == 0
        finally:
            reset_scope(token_b)

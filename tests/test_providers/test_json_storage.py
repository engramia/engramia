"""Unit tests for JSONStorage."""

import numpy as np
import pytest

from remanence.providers.json_storage import JSONStorage


@pytest.fixture
def storage(tmp_path) -> JSONStorage:
    return JSONStorage(path=tmp_path)


class TestKeyValue:
    def test_save_and_load(self, storage):
        storage.save("foo/bar", {"x": 1})
        assert storage.load("foo/bar") == {"x": 1}

    def test_load_missing_key_returns_none(self, storage):
        assert storage.load("does/not/exist") is None

    def test_save_overwrites(self, storage):
        storage.save("k", {"v": 1})
        storage.save("k", {"v": 2})
        assert storage.load("k") == {"v": 2}

    def test_save_unicode(self, storage):
        storage.save("unicode", {"name": "Marek Čermák", "emoji": "🧠"})
        assert storage.load("unicode")["name"] == "Marek Čermák"

    def test_list_keys_empty(self, storage):
        assert storage.list_keys() == []

    def test_list_keys(self, storage):
        storage.save("patterns/a", {})
        storage.save("patterns/b", {})
        storage.save("other/c", {})
        assert storage.list_keys() == ["other/c", "patterns/a", "patterns/b"]

    def test_list_keys_with_prefix(self, storage):
        storage.save("patterns/a", {})
        storage.save("other/b", {})
        assert storage.list_keys(prefix="patterns") == ["patterns/a"]

    def test_delete_existing(self, storage):
        storage.save("to_delete", {"v": 1})
        storage.delete("to_delete")
        assert storage.load("to_delete") is None

    def test_delete_missing_is_noop(self, storage):
        storage.delete("no_such_key")  # should not raise

    def test_atomic_write_leaves_no_tmp(self, storage, tmp_path):
        storage.save("atomic_test", {"v": 1})
        tmp_files = list(tmp_path.rglob("*.tmp"))
        assert tmp_files == []


class TestEmbeddingIndex:
    def _vec(self, dim: int = 4, seed: int = 0) -> list[float]:
        rng = np.random.RandomState(seed)
        v = rng.randn(dim).astype(np.float32)
        return (v / np.linalg.norm(v)).tolist()

    def test_save_and_search_exact(self, storage):
        vec = self._vec(seed=1)
        storage.save_embedding("patterns/a", vec)
        results = storage.search_similar(vec, limit=1)
        assert len(results) == 1
        key, score = results[0]
        assert key == "patterns/a"
        assert score == pytest.approx(1.0, abs=1e-5)

    def test_search_returns_sorted_by_similarity(self, storage):
        v1 = self._vec(seed=1)
        v2 = self._vec(seed=2)
        v3 = self._vec(seed=3)
        storage.save_embedding("a", v1)
        storage.save_embedding("b", v2)
        storage.save_embedding("c", v3)
        results = storage.search_similar(v1, limit=3)
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_with_prefix(self, storage):
        vec = self._vec(seed=1)
        storage.save_embedding("patterns/a", vec)
        storage.save_embedding("other/b", vec)
        results = storage.search_similar(vec, limit=5, prefix="patterns")
        keys = [k for k, _ in results]
        assert "other/b" not in keys
        assert "patterns/a" in keys

    def test_search_limit(self, storage):
        vec = self._vec(seed=42)
        for i in range(10):
            storage.save_embedding(f"p/{i}", self._vec(seed=i))
        results = storage.search_similar(vec, limit=3)
        assert len(results) <= 3

    def test_delete_removes_embedding(self, storage):
        vec = self._vec(seed=1)
        storage.save("p/a", {})
        storage.save_embedding("p/a", vec)
        storage.delete("p/a")
        results = storage.search_similar(vec, limit=5)
        assert all(k != "p/a" for k, _ in results)

    def test_embeddings_persisted_across_instances(self, tmp_path):
        vec = self._vec(seed=7)
        s1 = JSONStorage(path=tmp_path)
        s1.save_embedding("p/x", vec)

        s2 = JSONStorage(path=tmp_path)
        results = s2.search_similar(vec, limit=1)
        assert results[0][0] == "p/x"
        assert results[0][1] == pytest.approx(1.0, abs=1e-5)

    def test_zero_vector_query_returns_empty(self, storage):
        storage.save_embedding("p/a", [1.0, 0.0])
        results = storage.search_similar([0.0, 0.0], limit=5)
        assert results == []

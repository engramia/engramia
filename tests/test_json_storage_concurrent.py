# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Thread-safety tests for JSONStorage.

Proves that concurrent save/load/save_embedding operations on a shared
JSONStorage instance do not corrupt data or raise exceptions.
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from engramia.providers.json_storage import JSONStorage

pytestmark = pytest.mark.concurrent


class TestConcurrentWrites:
    """Concurrent save() calls must not corrupt each other's data."""

    def test_concurrent_saves_all_readable(self, tmp_path):
        storage = JSONStorage(path=tmp_path)
        n = 50

        def write(i: int) -> None:
            storage.save(f"patterns/item_{i:03d}", {"value": i, "tag": f"worker-{i}"})

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(write, i) for i in range(n)]
            for f in as_completed(futures):
                f.result()  # re-raise any exception

        for i in range(n):
            data = storage.load(f"patterns/item_{i:03d}")
            assert data is not None, f"item_{i:03d} was lost"
            assert data["value"] == i

    def test_concurrent_saves_correct_count(self, tmp_path):
        storage = JSONStorage(path=tmp_path)
        n = 40

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(storage.save, f"patterns/k_{i}", {"i": i}) for i in range(n)]
            for f in as_completed(futures):
                f.result()

        keys = storage.list_keys(prefix="patterns")
        assert len(keys) == n


class TestConcurrentEmbeddings:
    """Concurrent save_embedding() calls must not corrupt the index."""

    def test_concurrent_embedding_saves(self, tmp_path):
        storage = JSONStorage(path=tmp_path)
        dim = 8
        n = 30
        vec = [1.0 / dim] * dim  # unit-ish vector

        def write_emb(i: int) -> None:
            storage.save(f"patterns/e_{i:03d}", {"task": f"task_{i}"})
            storage.save_embedding(f"patterns/e_{i:03d}", vec)

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(write_emb, i) for i in range(n)]
            for f in as_completed(futures):
                f.result()

        # All embeddings must be retrievable via search
        results = storage.search_similar(vec, limit=n, prefix="patterns")
        assert len(results) == n

    def test_concurrent_reads_during_writes(self, tmp_path):
        """Readers must not see partial state while writers hold the lock."""
        storage = JSONStorage(path=tmp_path)
        vec = [0.5, 0.5, 0.5, 0.5]
        errors: list[Exception] = []

        def writer(i: int) -> None:
            try:
                key = f"patterns/rw_{i:03d}"
                storage.save(key, {"task": f"t{i}"})
                storage.save_embedding(key, vec)
            except Exception as exc:
                errors.append(exc)

        def reader() -> None:
            try:
                storage.search_similar(vec, limit=10, prefix="patterns")
            except Exception as exc:
                errors.append(exc)

        barrier = threading.Barrier(20)

        def worker(i: int) -> None:
            barrier.wait()
            if i % 2 == 0:
                writer(i // 2)
            else:
                reader()

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(worker, i) for i in range(20)]
            for f in as_completed(futures):
                f.result()

        assert errors == [], f"Concurrent read/write raised: {errors}"


class TestConcurrentListKeys:
    """list_keys() called concurrently with ongoing save() calls is consistent."""

    def test_list_keys_never_raises_during_concurrent_writes(self, tmp_path):
        storage = JSONStorage(path=tmp_path)
        errors: list[Exception] = []

        def writer(i: int) -> None:
            try:
                storage.save(f"patterns/lk_{i:04d}", {"v": i})
            except Exception as exc:
                errors.append(exc)

        def reader() -> None:
            try:
                keys = storage.list_keys(prefix="patterns")
                # Result must be a list (may be partial, but must be consistent)
                assert isinstance(keys, list)
            except Exception as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = (
                [pool.submit(writer, i) for i in range(50)]
                + [pool.submit(reader) for _ in range(20)]
            )
            for f in as_completed(futures):
                f.result()

        assert errors == [], f"Concurrent list_keys raised: {errors}"

    def test_list_keys_count_eventually_consistent(self, tmp_path):
        """After all writers finish, list_keys returns the exact count."""
        storage = JSONStorage(path=tmp_path)
        n = 60

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(storage.save, f"patterns/cnt_{i:04d}", {"i": i}) for i in range(n)]
            for f in as_completed(futures):
                f.result()

        keys = storage.list_keys(prefix="patterns")
        assert len(keys) == n


class TestConcurrentDeleteAndRead:
    """Delete while concurrent reads must not raise KeyError or similar."""

    def test_delete_during_reads(self, tmp_path):
        storage = JSONStorage(path=tmp_path)
        vec = [0.5, 0.5, 0.5, 0.5]
        n = 20

        for i in range(n):
            key = f"patterns/del_{i:03d}"
            storage.save(key, {"task": f"t{i}"})
            storage.save_embedding(key, vec)

        errors: list[Exception] = []

        def deleter(i: int) -> None:
            try:
                storage.delete(f"patterns/del_{i:03d}")
            except Exception as exc:
                errors.append(exc)

        def reader() -> None:
            try:
                storage.search_similar(vec, limit=5, prefix="patterns")
            except Exception as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(deleter, i) for i in range(n // 2)] + [pool.submit(reader) for _ in range(10)]
            for f in as_completed(futures):
                f.result()

        assert errors == [], f"Concurrent delete/read raised: {errors}"


class TestHighConcurrencyStress:
    """High-concurrency stress: many writers + readers, no corruption, no exceptions."""

    def test_stress_mixed_operations(self, tmp_path):
        storage = JSONStorage(path=tmp_path)
        vec = [0.25, 0.25, 0.25, 0.25]
        n_workers = 30  # concurrency level — matches the barrier party count
        n_write = 20
        n_read = 10
        errors: list[Exception] = []

        # Barrier ensures all threads start together to maximise contention
        barrier = threading.Barrier(n_workers)

        def writer(i: int) -> None:
            try:
                barrier.wait()
                key = f"patterns/stress_{i:04d}"
                storage.save(key, {"value": i, "name": f"item-{i}"})
                storage.save_embedding(key, vec)
            except Exception as exc:
                errors.append(exc)

        def reader() -> None:
            try:
                barrier.wait()
                storage.search_similar(vec, limit=10, prefix="patterns")
                storage.list_keys(prefix="patterns")
            except Exception as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = (
                [pool.submit(writer, i) for i in range(n_write)]
                + [pool.submit(reader) for _ in range(n_read)]
            )
            for f in as_completed(futures):
                f.result()

        assert errors == [], f"Stress test raised {len(errors)} errors: {errors[:3]}"

        # All writes must be retrievable after completion
        keys = storage.list_keys(prefix="patterns")
        assert len(keys) == n_write

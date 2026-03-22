"""JSON file-based storage backend.

Stores data as individual JSON files on disk.
Embedding index is loaded into memory on startup and persisted atomically.
Suitable for single-machine development and small deployments.

Thread-safe for concurrent reads and writes within a single process.
For multi-process deployments, use PostgresStorage instead.

No external dependencies beyond numpy (already a core dependency).
"""

import json
import logging
import os
import threading
from pathlib import Path

import numpy as np

from agent_brain.providers.base import StorageBackend

_log = logging.getLogger(__name__)
_EMBEDDINGS_FILE = "_embeddings.json"


class JSONStorage(StorageBackend):
    """Stores Brain data in a directory of JSON files.

    Each key maps to a file: ``{root}/{key}.json``.
    Embeddings are stored in a single index file ``{root}/_embeddings.json``
    and kept in memory for fast cosine similarity search.

    Writes are atomic: data is written to a ``.tmp`` file first, then
    renamed over the target to prevent corruption on crash.

    Thread-safe within a single process (threading.Lock on embedding index).
    For concurrent multi-process access, use PostgresStorage.

    Args:
        path: Directory to use as the storage root. Created if it does not exist.
    """

    def __init__(self, path: str | Path) -> None:
        self._root = Path(path)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._embeddings: dict[str, list[float]] = self._load_embeddings_index()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _key_to_path(self, key: str) -> Path:
        """Convert a storage key to a safe file path within the storage root.

        Rejects keys that would escape the root directory (path traversal).
        Segments consisting entirely of dots (``.``, ``..``, ``...``) are removed.
        """
        clean = key.replace("\\", "/")
        # Drop any segment that is only dots (prevents .., ..., etc.)
        parts = [p for p in clean.split("/") if p and not all(c == "." for c in p)]
        if not parts:
            raise ValueError(f"Invalid storage key: {key!r}")
        path = self._root.joinpath(*parts).with_suffix(".json")
        # Defense-in-depth: ensure the resolved path stays inside root
        try:
            path.resolve().relative_to(self._root.resolve())
        except ValueError:
            raise ValueError(f"Storage key escapes root directory: {key!r}")
        return path

    def _embeddings_path(self) -> Path:
        return self._root / _EMBEDDINGS_FILE

    def _load_embeddings_index(self) -> dict[str, list[float]]:
        p = self._embeddings_path()
        if not p.exists():
            return {}
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def _atomic_write(self, path: Path, data: dict) -> None:
        """Write *data* to *path* atomically using a tmp → bak → replace sequence."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        bak = path.with_suffix(".bak")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        if path.exists():
            os.replace(path, bak)
        os.replace(tmp, path)

    def _save_embeddings_index(self) -> None:
        # Caller must hold self._lock
        self._atomic_write(self._embeddings_path(), self._embeddings)

    # ------------------------------------------------------------------
    # StorageBackend: key-value store
    # ------------------------------------------------------------------

    def load(self, key: str) -> dict | None:
        path = self._key_to_path(key)
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def save(self, key: str, data: dict) -> None:
        self._atomic_write(self._key_to_path(key), data)

    def list_keys(self, prefix: str = "") -> list[str]:
        keys: list[str] = []
        for path in self._root.rglob("*.json"):
            if path.name.startswith("_"):
                continue
            relative = path.relative_to(self._root)
            key = str(relative.with_suffix("")).replace("\\", "/")
            if prefix and not key.startswith(prefix):
                continue
            keys.append(key)
        return sorted(keys)

    def delete(self, key: str) -> None:
        path = self._key_to_path(key)
        if path.exists():
            path.unlink()
        with self._lock:
            if key in self._embeddings:
                del self._embeddings[key]
                self._save_embeddings_index()

    # ------------------------------------------------------------------
    # StorageBackend: embedding index
    # ------------------------------------------------------------------

    def save_embedding(self, key: str, embedding: list[float]) -> None:
        with self._lock:
            # Dimension consistency check: all stored embeddings must share the same size
            if self._embeddings and embedding:
                stored_dim = len(next(iter(self._embeddings.values())))
                new_dim = len(embedding)
                if new_dim != stored_dim:
                    raise ValueError(
                        f"Embedding dimension mismatch: existing index uses {stored_dim}-dim vectors, "
                        f"got {new_dim}-dim. Ensure all embeddings use the same provider and model."
                    )
            self._embeddings[key] = embedding
            self._save_embeddings_index()

    def search_similar(
        self,
        embedding: list[float],
        limit: int = 10,
        prefix: str = "",
    ) -> list[tuple[str, float]]:
        """Brute-force cosine similarity over the in-memory embedding index.

        O(n) over number of stored embeddings. Sufficient for thousands of
        patterns; switch to PostgresStorage + pgvector for larger scales.
        """
        with self._lock:
            if self._embeddings and embedding:
                stored_dim = len(next(iter(self._embeddings.values())))
                if len(embedding) != stored_dim:
                    raise ValueError(
                        f"Query embedding dimension {len(embedding)} does not match "
                        f"stored dimension {stored_dim}."
                    )
            # Snapshot the index to avoid holding the lock during numpy ops
            index_snapshot = dict(self._embeddings)

        query = np.array(embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query)
        if query_norm == 0:
            return []

        results: list[tuple[str, float]] = []
        for key, vec in index_snapshot.items():
            if prefix and not key.startswith(prefix):
                continue
            v = np.array(vec, dtype=np.float32)
            v_norm = np.linalg.norm(v)
            if v_norm == 0:
                continue
            similarity = float(np.clip(np.dot(query, v) / (query_norm * v_norm), 0.0, 1.0))
            results.append((key, similarity))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

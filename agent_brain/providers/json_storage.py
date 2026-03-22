"""JSON file-based storage backend.

Stores data as individual JSON files on disk.
Embedding index is loaded into memory on startup and persisted atomically.
Suitable for single-machine development and small deployments.

No external dependencies beyond numpy (already a core dependency).
"""

import json
import os
from pathlib import Path

import numpy as np

from agent_brain.providers.base import StorageBackend

_EMBEDDINGS_FILE = "_embeddings.json"


class JSONStorage(StorageBackend):
    """Stores Brain data in a directory of JSON files.

    Each key maps to a file: ``{root}/{key}.json``.
    Embeddings are stored in a single index file ``{root}/_embeddings.json``
    and kept in memory for fast cosine similarity search.

    Writes are atomic: data is written to a ``.tmp`` file first, then
    renamed over the target to prevent corruption on crash.

    Args:
        path: Directory to use as the storage root. Created if it does not exist.
    """

    def __init__(self, path: str | Path) -> None:
        self._root = Path(path)
        self._root.mkdir(parents=True, exist_ok=True)
        self._embeddings: dict[str, list[float]] = self._load_embeddings_index()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _key_to_path(self, key: str) -> Path:
        """Convert a storage key to an absolute file path.

        Strips leading slashes and ``..`` segments to prevent path traversal.
        """
        clean = key.replace("..", "").strip("/").replace("\\", "/")
        return self._root / (clean + ".json")

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
        if key in self._embeddings:
            del self._embeddings[key]
            self._save_embeddings_index()

    # ------------------------------------------------------------------
    # StorageBackend: embedding index
    # ------------------------------------------------------------------

    def save_embedding(self, key: str, embedding: list[float]) -> None:
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
        query = np.array(embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query)
        if query_norm == 0:
            return []

        results: list[tuple[str, float]] = []
        for key, vec in self._embeddings.items():
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

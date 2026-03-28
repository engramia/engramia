# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""JSON file-based storage backend.

Stores data as individual JSON files on disk.
Embedding index is loaded into memory on startup and persisted atomically.
Suitable for single-machine development and small deployments.

Thread-safe for concurrent reads and writes within a single process.
For multi-process deployments, use PostgresStorage instead.

Multi-tenancy: each (tenant_id, project_id) scope uses a subdirectory.
The default scope (tenant_id='default', project_id='default') maps to the
root directory for full backward compatibility with existing data.

No external dependencies beyond numpy (already a core dependency).
"""

import json
import logging
import os
import threading
from pathlib import Path

import numpy as np

from engramia.providers.base import StorageBackend

_log = logging.getLogger(__name__)
_EMBEDDINGS_FILE = "_embeddings.json"


def _sanitize_segment(segment: str) -> str:
    """Remove characters unsafe for directory names from a path segment."""
    # Allow alphanumeric, hyphen, underscore. Replace everything else with _.
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in segment) or "default"


class JSONStorage(StorageBackend):
    """Stores Engramia data in a directory of JSON files.

    Each key maps to a file: ``{root}/{key}.json`` (default scope) or
    ``{root}/{tenant_id}/{project_id}/{key}.json`` (non-default scope).

    Embeddings are stored in a per-scope index file ``_embeddings.json``
    and kept in memory for fast cosine similarity search.

    Writes are atomic: data is written to a ``.tmp`` file first, then
    renamed over the target to prevent corruption on crash.

    Thread-safe within a single process (threading.Lock on embedding indexes).
    For concurrent multi-process access, use PostgresStorage.

    Args:
        path: Directory to use as the storage root. Created if it does not exist.
    """

    def __init__(self, path: str | Path) -> None:
        self._root = Path(path)
        self._root.mkdir(parents=True, exist_ok=True)
        # Resolve once at construction so that _key_to_path's relative_to()
        # comparison is always apples-to-apples even on Windows long paths.
        self._root_resolved = self._root.resolve()
        self._lock = threading.Lock()
        # Per-scope embedding indexes: {(tenant_id, project_id): {key: vector}}
        self._scope_embeddings: dict[tuple[str, str], dict[str, list[float]]] = {}
        # Eagerly load the default scope (backward compat with pre-5.1 data)
        self._scope_embeddings[("default", "default")] = self._load_embeddings_for_root(self._root)

    # ------------------------------------------------------------------
    # Scope helpers
    # ------------------------------------------------------------------

    def _effective_root(self) -> Path:
        """Return the storage root for the current scope.

        The default scope (tenant='default', project='default') maps to
        ``self._root`` for backward compatibility. All other scopes use
        a ``{root}/{tenant_id}/{project_id}/`` subdirectory.
        """
        from engramia._context import get_scope

        s = get_scope()
        if s.tenant_id == "default" and s.project_id == "default":
            return self._root
        t = _sanitize_segment(s.tenant_id)
        p = _sanitize_segment(s.project_id)
        return self._root / t / p

    def _scope_key(self) -> tuple[str, str]:
        from engramia._context import get_scope

        s = get_scope()
        return (s.tenant_id, s.project_id)

    def _get_embeddings(self) -> dict[str, list[float]]:
        """Return the in-memory embedding dict for the current scope (lazy load)."""
        k = self._scope_key()
        if k not in self._scope_embeddings:
            root = self._effective_root()
            self._scope_embeddings[k] = self._load_embeddings_for_root(root)
        return self._scope_embeddings[k]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _key_to_path(self, key: str) -> Path:
        """Convert a storage key to a safe file path within the effective root.

        Rejects keys that would escape the storage root (path traversal).
        Segments consisting entirely of dots (``.``, ``..``, ``...``) are removed.
        """
        clean = key.replace("\\", "/")
        parts = [p for p in clean.split("/") if p and not all(c == "." for c in p)]
        if not parts:
            raise ValueError(f"Invalid storage key: {key!r}")
        root = self._effective_root().resolve()
        path = root.joinpath(*parts).with_suffix(".json")
        # Defense-in-depth: ensure path stays inside the effective root.
        try:
            path.relative_to(self._root_resolved)
        except ValueError:
            raise ValueError(f"Storage key escapes root directory: {key!r}") from None
        return path

    def _embeddings_path(self) -> Path:
        return self._effective_root() / _EMBEDDINGS_FILE

    def _load_embeddings_for_root(self, root: Path) -> dict[str, list[float]]:
        p = root / _EMBEDDINGS_FILE
        if not p.exists():
            return {}
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def _atomic_write(self, path: Path, data: dict | list) -> None:  # type: ignore[type-arg]
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
        k = self._scope_key()
        self._atomic_write(self._embeddings_path(), self._scope_embeddings.get(k, {}))

    # ------------------------------------------------------------------
    # StorageBackend: key-value store
    # ------------------------------------------------------------------

    def load(self, key: str) -> dict | None:
        path = self._key_to_path(key)
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def save(self, key: str, data: dict | list) -> None:  # type: ignore[override]
        self._atomic_write(self._key_to_path(key), data)

    def list_keys(self, prefix: str = "") -> list[str]:
        root = self._effective_root()
        root.mkdir(parents=True, exist_ok=True)
        keys: list[str] = []
        for path in root.rglob("*.json"):
            if path.name.startswith("_"):
                continue
            relative = path.relative_to(root)
            key = str(relative.with_suffix("")).replace("\\", "/")
            if prefix and not key.startswith(prefix):
                continue
            keys.append(key)
        return sorted(keys)

    def delete(self, key: str) -> None:
        path = self._key_to_path(key)
        if path.exists():
            path.unlink()
        for suffix in (".bak", ".tmp"):
            artifact = path.with_suffix(suffix)
            if artifact.exists():
                artifact.unlink()
        with self._lock:
            embeddings = self._get_embeddings()
            if key in embeddings:
                del embeddings[key]
                self._save_embeddings_index()

    def count_patterns(self, prefix: str = "patterns/") -> int:
        return len(self.list_keys(prefix))

    # ------------------------------------------------------------------
    # StorageBackend: embedding index
    # ------------------------------------------------------------------

    def save_embedding(self, key: str, embedding: list[float]) -> None:
        with self._lock:
            embeddings = self._get_embeddings()
            # Dimension consistency check
            if embeddings and embedding:
                stored_dim = len(next(iter(embeddings.values())))
                new_dim = len(embedding)
                if new_dim != stored_dim:
                    raise ValueError(
                        f"Embedding dimension mismatch: existing index uses {stored_dim}-dim vectors, "
                        f"got {new_dim}-dim. Ensure all embeddings use the same provider and model."
                    )
            embeddings[key] = embedding
            self._save_embeddings_index()

    def search_similar(
        self,
        embedding: list[float],
        limit: int = 10,
        prefix: str = "",
    ) -> list[tuple[str, float]]:
        """Brute-force cosine similarity over the in-memory embedding index for the current scope.

        O(n) over number of stored embeddings in the scope. Sufficient for thousands of
        patterns; switch to PostgresStorage + pgvector for larger scales.
        """
        with self._lock:
            embeddings = self._get_embeddings()
            if embeddings and embedding:
                stored_dim = len(next(iter(embeddings.values())))
                if len(embedding) != stored_dim:
                    raise ValueError(
                        f"Query embedding dimension {len(embedding)} does not match stored dimension {stored_dim}."
                    )
            index_snapshot = dict(embeddings)

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

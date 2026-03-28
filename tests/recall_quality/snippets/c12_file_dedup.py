# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""C12 — File Deduplication snippets."""

GOOD: dict = {
    "eval_score": 9.0,
    "output": "Scanned 1024 files. Found 87 duplicates. Deleted 87 files, freed 234 MB.",
    "code": '''\
import hashlib
from pathlib import Path


def _file_md5(path: Path, chunk_size: int = 65536) -> str:
    """Stream-hash a file to avoid loading it entirely into memory."""
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def deduplicate_directory(
    root: str | Path,
    *,
    dry_run: bool = False,
    min_size: int = 1,
) -> list[Path]:
    """Remove duplicate files in *root* recursively, keeping the first seen.

    Args:
        root: Directory to scan.
        dry_run: If True, report duplicates without deleting.
        min_size: Skip files smaller than this (bytes). Default 1.

    Returns:
        List of paths that were deleted (or would be deleted in dry_run).
    """
    seen: dict[str, Path] = {}
    deleted: list[Path] = []

    for path in sorted(Path(root).rglob("*")):
        if not path.is_file():
            continue
        if path.stat().st_size < min_size:
            continue

        digest = _file_md5(path)
        if digest in seen:
            deleted.append(path)
            if not dry_run:
                path.unlink()
        else:
            seen[digest] = path

    return deleted
''',
}

MEDIUM: dict = {
    "eval_score": 6.0,
    "output": "Deleted 87 duplicates.",
    "code": '''\
import hashlib
import os

def dedup(directory):
    seen = {}
    deleted = []
    for dirpath, _, filenames in os.walk(directory):
        for name in filenames:
            full = os.path.join(dirpath, name)
            # BUG: loads entire file into memory — fails on large files
            digest = hashlib.md5(open(full, "rb").read()).hexdigest()
            if digest in seen:
                os.remove(full)
                deleted.append(full)
            else:
                seen[digest] = full
    return deleted
''',
}

BAD: dict = {
    "eval_score": 2.0,
    "output": "",
    "code": '''\
import os

def remove_duplicates(folder):
    # BAD: compares file contents byte-by-byte for every pair — O(n^2)
    # BAD: no hashing, reads files multiple times
    files = []
    for f in os.listdir(folder):
        files.append(os.path.join(folder, f))

    for i in range(len(files)):
        for j in range(i + 1, len(files)):
            if open(files[i], "rb").read() == open(files[j], "rb").read():
                os.remove(files[j])
                # BUG: modifies list while iterating (index shifts)
''',
}

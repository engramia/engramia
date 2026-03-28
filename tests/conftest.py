# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Shared test fixtures and helpers."""

import hashlib

import numpy as np
import pytest

from engramia.memory import Memory
from engramia.providers.base import EmbeddingProvider
from engramia.providers.json_storage import JSONStorage


class FakeEmbeddings(EmbeddingProvider):
    """Deterministic embeddings for tests — no API key required.

    Produces a stable 1536-dimensional unit vector derived from the MD5 hash
    of the input text. Identical texts produce identical vectors, so
    cosine similarity of a text with itself is always 1.0.
    """

    DIM = 1536

    def embed(self, text: str) -> list[float]:
        seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2**32)
        rng = np.random.RandomState(seed)
        vec = rng.randn(self.DIM).astype(np.float32)
        norm = np.linalg.norm(vec)
        return (vec / norm).tolist()


@pytest.fixture
def fake_embeddings() -> FakeEmbeddings:
    return FakeEmbeddings()


@pytest.fixture
def storage(tmp_path) -> JSONStorage:
    return JSONStorage(path=tmp_path)


@pytest.fixture
def mem(fake_embeddings, storage) -> Memory:
    return Memory(embeddings=fake_embeddings, storage=storage)

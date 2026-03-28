# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Pytest fixtures for the feature test suite.

Mirrors the recall_quality/conftest.py session fixtures but uses a separate
tmp storage directory so feature tests don't share state with quality tests.
"""
from __future__ import annotations

import os
import uuid

import pytest

from tests.recall_quality.conftest import TestClient


@pytest.fixture(scope="session")
def run_tag() -> str:
    """Unique tag for this test session — prefixed on all task strings."""
    return f"TF-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def client(tmp_path_factory, run_tag):  # noqa: F811
    """Session-scoped TestClient in local or remote mode."""
    mode = os.environ.get("ENGRAMIA_TEST_MODE", "local").lower()

    if mode == "remote":
        api_url = os.environ.get("ENGRAMIA_API_URL")
        if not api_url:
            pytest.skip("ENGRAMIA_API_URL not set — skipping remote tests")
        from engramia.sdk.webhook import EngramiaWebhook

        backend = EngramiaWebhook(
            url=api_url,
            api_key=os.environ.get("ENGRAMIA_API_KEY"),
        )
        return TestClient(backend, mode="remote")

    from engramia import Memory
    from engramia.providers import JSONStorage
    from engramia.providers.local_embeddings import LocalEmbeddings

    tmp = tmp_path_factory.mktemp("engramia_tf")
    backend = Memory(
        embeddings=LocalEmbeddings(),
        storage=JSONStorage(path=tmp),
    )
    return TestClient(backend, mode="local")

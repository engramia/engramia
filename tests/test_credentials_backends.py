# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Tests for the credential backend Protocol + local AES-GCM impl + factory.

The vault backend has its own file (``test_credentials_vault_backend.py``)
so this module focuses on:

- LocalAESGCMBackend round-trip + AAD enforcement (regression for the
  existing AESGCMCipher behaviour, now wrapped).
- Factory dispatch: env var picks local vs vault.
- Backend Protocol structural shape.
"""

import base64
import os

import pytest

from engramia.credentials.backend import CredentialBackend, EncryptedBlob
from engramia.credentials.backends import (
    LOCAL_BACKEND_ID,
    VAULT_BACKEND_ID,
    LocalAESGCMBackend,
    make_backend_from_env,
)
from engramia.exceptions import DecryptionError, MasterKeyError

_TEST_KEY_B64 = base64.b64encode(b"x" * 32).decode("ascii")


@pytest.fixture()
def local_backend(monkeypatch) -> LocalAESGCMBackend:
    monkeypatch.setenv("ENGRAMIA_CREDENTIALS_KEY", _TEST_KEY_B64)
    return LocalAESGCMBackend.from_env()


def test_local_backend_satisfies_protocol(local_backend):
    assert isinstance(local_backend, CredentialBackend)
    assert local_backend.backend_id == "local"


def test_local_round_trip(local_backend):
    blob = local_backend.encrypt(
        tenant_id="t1", provider="openai", purpose="llm", plaintext="sk-secret"
    )
    pt = local_backend.decrypt(
        tenant_id="t1", provider="openai", purpose="llm", blob=blob
    )
    assert pt == "sk-secret"


def test_local_blob_shape(local_backend):
    blob = local_backend.encrypt(
        tenant_id="t1", provider="openai", purpose="llm", plaintext="x"
    )
    assert isinstance(blob, EncryptedBlob)
    assert len(blob.nonce) == 12  # AES-GCM standard
    assert len(blob.auth_tag) == 16  # AES-GCM standard
    assert blob.key_version == 1


def test_local_aad_enforces_tenant(local_backend):
    blob = local_backend.encrypt(
        tenant_id="tenant-A", provider="openai", purpose="llm", plaintext="sk-x"
    )
    # Swapping the row to another tenant in the DB → decrypt fails.
    with pytest.raises(DecryptionError):
        local_backend.decrypt(
            tenant_id="tenant-B", provider="openai", purpose="llm", blob=blob
        )


def test_local_aad_enforces_provider(local_backend):
    blob = local_backend.encrypt(
        tenant_id="t1", provider="openai", purpose="llm", plaintext="sk-x"
    )
    with pytest.raises(DecryptionError):
        local_backend.decrypt(
            tenant_id="t1", provider="anthropic", purpose="llm", blob=blob
        )


def test_local_aad_enforces_purpose(local_backend):
    blob = local_backend.encrypt(
        tenant_id="t1", provider="openai", purpose="llm", plaintext="sk-x"
    )
    with pytest.raises(DecryptionError):
        local_backend.decrypt(
            tenant_id="t1", provider="openai", purpose="embedding", blob=blob
        )


def test_local_health_check_no_op(local_backend):
    # No-op: the cipher was validated at construction. Just ensures the
    # method exists and doesn't raise on a healthy backend.
    local_backend.health_check()


def test_factory_default_is_local(monkeypatch):
    monkeypatch.delenv("ENGRAMIA_CREDENTIALS_BACKEND", raising=False)
    monkeypatch.setenv("ENGRAMIA_CREDENTIALS_KEY", _TEST_KEY_B64)
    backend = make_backend_from_env()
    assert backend.backend_id == LOCAL_BACKEND_ID


def test_factory_explicit_local(monkeypatch):
    monkeypatch.setenv("ENGRAMIA_CREDENTIALS_BACKEND", "local")
    monkeypatch.setenv("ENGRAMIA_CREDENTIALS_KEY", _TEST_KEY_B64)
    backend = make_backend_from_env()
    assert backend.backend_id == LOCAL_BACKEND_ID


def test_factory_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("ENGRAMIA_CREDENTIALS_BACKEND", "memcached")
    with pytest.raises(ValueError, match="Unknown ENGRAMIA_CREDENTIALS_BACKEND"):
        make_backend_from_env()


def test_factory_local_missing_master_key_raises(monkeypatch):
    monkeypatch.setenv("ENGRAMIA_CREDENTIALS_BACKEND", "local")
    monkeypatch.delenv("ENGRAMIA_CREDENTIALS_KEY", raising=False)
    with pytest.raises(MasterKeyError):
        make_backend_from_env()


def test_factory_env_dict_override(monkeypatch):
    """Tests the ``env=`` argument so we can build a backend from a
    custom mapping without touching os.environ."""
    monkeypatch.delenv("ENGRAMIA_CREDENTIALS_BACKEND", raising=False)
    monkeypatch.setenv("ENGRAMIA_CREDENTIALS_KEY", _TEST_KEY_B64)
    custom = dict(os.environ)
    custom["ENGRAMIA_CREDENTIALS_BACKEND"] = "local"
    backend = make_backend_from_env(custom)
    assert backend.backend_id == "local"


def test_constants_match_backend_ids(local_backend):
    """Public constants on the package match each backend's instance ``backend_id``."""
    assert LOCAL_BACKEND_ID == "local"
    assert VAULT_BACKEND_ID == "vault"
    assert local_backend.backend_id == LOCAL_BACKEND_ID

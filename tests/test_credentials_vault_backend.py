# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Vault Transit backend tests with mocked Vault client.

We don't run an actual Vault server here — that's a release-marker
integration test. These unit tests verify:

- Encrypt → Decrypt round-trip via the backend Protocol shape.
- Context bytes are bound to (tenant_id, provider, purpose).
- ``EncryptedBlob`` shape: vault rows have empty nonce/auth_tag.
- Factory rejects missing required env vars.
- Backend errors (Vault unreachable / 5xx) propagate as ``VaultBackendError``.
"""

import base64
from typing import Any

import pytest

from engramia.credentials.backend import EncryptedBlob
from engramia.credentials.backends.vault import VaultTransitBackend, _context_for
from engramia.exceptions import VaultBackendError


class _MockVaultClient:
    """Stand-in for VaultClient that round-trips plaintext via base64
    of plaintext+context, mimicking Vault's derived-key behaviour just
    well enough for encrypt/decrypt symmetry tests."""

    def __init__(self) -> None:
        self.encrypt_calls: list[dict[str, Any]] = []
        self.decrypt_calls: list[dict[str, Any]] = []
        self.health_calls = 0

    def encrypt(self, *, plaintext: str, context: bytes) -> tuple[str, int]:
        self.encrypt_calls.append({"plaintext": plaintext, "context": context})
        # Simulate Vault: ciphertext is "vault:v1:<base64(context|plaintext)>"
        b = base64.b64encode(context + b"|" + plaintext.encode()).decode("ascii")
        return f"vault:v1:{b}", 1

    def decrypt(self, *, ciphertext: str, context: bytes) -> str:
        self.decrypt_calls.append({"ciphertext": ciphertext, "context": context})
        if not ciphertext.startswith("vault:v"):
            raise VaultBackendError("malformed ciphertext")
        payload_b64 = ciphertext.split(":", 2)[2]
        decoded = base64.b64decode(payload_b64)
        sep = decoded.index(b"|")
        original_ctx = decoded[:sep]
        if original_ctx != context:
            # Mimics Vault's behaviour with derived=true: wrong context
            # surfaces as a Vault-side error.
            raise VaultBackendError(
                f"context mismatch: stored={original_ctx!r}, presented={context!r}"
            )
        return decoded[sep + 1 :].decode()

    def health_check(self) -> None:
        self.health_calls += 1


def test_context_for_matches_local_aad_shape():
    """Vault context bytes have the same shape as the local backend's AAD,
    so a row swapped between backends would still be detected as tampered."""
    ctx = _context_for("tenant-A", "openai", "llm")
    assert ctx == b"tenant-A:openai:llm"


def test_encrypt_decrypt_round_trip():
    client = _MockVaultClient()
    backend = VaultTransitBackend(client)
    blob = backend.encrypt(
        tenant_id="t1", provider="openai", purpose="llm", plaintext="sk-abc"
    )
    assert blob.ciphertext.startswith(b"vault:v1:")
    assert blob.nonce == b""
    assert blob.auth_tag == b""
    assert blob.key_version == 1

    pt = backend.decrypt(
        tenant_id="t1", provider="openai", purpose="llm", blob=blob
    )
    assert pt == "sk-abc"


def test_decrypt_rejects_swap_to_wrong_tenant():
    """Row-substitution defence: a row swapped to another tenant has
    different context bytes than at encrypt time → Vault raises."""
    client = _MockVaultClient()
    backend = VaultTransitBackend(client)
    blob = backend.encrypt(
        tenant_id="tenant-A", provider="openai", purpose="llm", plaintext="sk-secret"
    )
    with pytest.raises(VaultBackendError, match="context mismatch"):
        backend.decrypt(
            tenant_id="tenant-B",  # different tenant — context differs
            provider="openai",
            purpose="llm",
            blob=blob,
        )


def test_decrypt_rejects_swap_to_wrong_provider():
    client = _MockVaultClient()
    backend = VaultTransitBackend(client)
    blob = backend.encrypt(
        tenant_id="t1", provider="openai", purpose="llm", plaintext="sk-secret"
    )
    with pytest.raises(VaultBackendError, match="context mismatch"):
        backend.decrypt(
            tenant_id="t1",
            provider="anthropic",  # mismatched provider
            purpose="llm",
            blob=blob,
        )


def test_decrypt_rejects_swap_to_wrong_purpose():
    client = _MockVaultClient()
    backend = VaultTransitBackend(client)
    blob = backend.encrypt(
        tenant_id="t1", provider="openai", purpose="llm", plaintext="sk-secret"
    )
    with pytest.raises(VaultBackendError, match="context mismatch"):
        backend.decrypt(
            tenant_id="t1",
            provider="openai",
            purpose="embedding",  # mismatched purpose
            blob=blob,
        )


def test_health_check_delegates_to_client():
    client = _MockVaultClient()
    backend = VaultTransitBackend(client)
    backend.health_check()
    assert client.health_calls == 1


def test_backend_id_is_vault():
    backend = VaultTransitBackend(_MockVaultClient())
    assert backend.backend_id == "vault"


def test_blob_ciphertext_is_bytes_of_vault_string():
    """Vault rows persist the ``vault:vN:...`` string as bytes — same DB
    column shape as local rows that hold AES ciphertext bytes."""
    client = _MockVaultClient()
    backend = VaultTransitBackend(client)
    blob = backend.encrypt(
        tenant_id="t1", provider="openai", purpose="llm", plaintext="sk-x"
    )
    assert isinstance(blob.ciphertext, bytes)
    # Sanity: ASCII-decodable (Vault uses only ASCII in the format)
    decoded = blob.ciphertext.decode("ascii")
    assert decoded.startswith("vault:v1:")


def test_factory_rejects_missing_env_vars():
    """Vault backend's ``from_env`` checks required vars before any
    network IO — so a misconfigured deployment fails startup loudly,
    not at the first decrypt."""
    with pytest.raises(ValueError, match="ENGRAMIA_VAULT_ADDR"):
        VaultTransitBackend.from_env({})

    with pytest.raises(ValueError, match="ENGRAMIA_VAULT_ROLE_ID"):
        VaultTransitBackend.from_env({
            "ENGRAMIA_VAULT_ADDR": "https://vault.example:8200",
            "ENGRAMIA_VAULT_SECRET_ID": "x",
        })


def test_blob_for_vault_row_serialises_to_db_shape():
    """Smoke check: the EncryptedBlob fields a vault row produces are
    the same shape that the store will read back via _row_to_stored —
    bytes ciphertext, empty nonce/auth_tag."""
    client = _MockVaultClient()
    backend = VaultTransitBackend(client)
    blob = backend.encrypt(
        tenant_id="t1", provider="openai", purpose="llm", plaintext="x"
    )
    assert isinstance(blob, EncryptedBlob)
    assert blob.nonce == b""
    assert blob.auth_tag == b""
    assert isinstance(blob.ciphertext, bytes)
    assert len(blob.ciphertext) > 0

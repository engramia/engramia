# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""CredentialBackend abstraction — local AES-GCM vs Vault Transit.

The backend Protocol is the single seam between the credential subsystem
(``store.py``, ``resolver.py``) and the underlying crypto primitive. Two
implementations live under ``engramia/credentials/backends/``:

- :class:`LocalAESGCMBackend` (default) — wraps :class:`AESGCMCipher` and
  produces self-contained ``(ciphertext, nonce, auth_tag)`` triples.
  Master key lives in the Engramia process. Suitable for self-host and
  any deployment without a separate KMS.
- :class:`VaultTransitBackend` (Phase 6.6 #6) — opaque ciphertext from
  Vault Transit. Master key never leaves Vault; every decrypt logs a row
  in Vault's audit backend. Required by Enterprise tenants with
  compliance constraints (SOC2 / HIPAA / regulated finance).

Per-row dispatch happens in :class:`CredentialResolver` based on the
``backend`` column on ``tenant_credentials`` — added in migration 028.
The resolver holds a ``dict[str, CredentialBackend]`` keyed by
``backend_id`` so a hybrid mid-migration deployment is correct.

See ``Ops/internal/vault-credential-backend-architecture.md`` for the
full design including ADRs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class EncryptedBlob:
    """Self-contained envelope for ciphertext as stored in
    ``tenant_credentials``.

    Field semantics differ per backend:

    - :class:`LocalAESGCMBackend`:
        - ``ciphertext`` — AES-256-GCM ciphertext (no tag appended).
        - ``nonce`` — 12 random bytes used at encrypt time.
        - ``auth_tag`` — 16-byte GCM authentication tag.
        - ``key_version`` — master-key generation marker (``1`` until rotation).

    - :class:`VaultTransitBackend`:
        - ``ciphertext`` — Vault's opaque ``vault:vN:...`` blob, encoded
          as bytes (UTF-8 of the Vault ciphertext string).
        - ``nonce`` — empty (``b""``); Vault embeds nonce internally.
        - ``auth_tag`` — empty (``b""``); Vault embeds tag internally.
        - ``key_version`` — Vault Transit key version (the ``N`` in
          ``vault:vN:...``). Useful for post-rotation auditing.

    The store persists all four fields regardless of backend; vault-backed
    rows simply have ``b""`` in the nonce / auth_tag columns. This keeps a
    single schema for both backends and survives the bulk
    local→vault migration without column drops.
    """

    ciphertext: bytes
    nonce: bytes
    auth_tag: bytes
    key_version: int


@runtime_checkable
class CredentialBackend(Protocol):
    """Symmetric encrypt/decrypt of tenant credentials.

    Both implementations bind ciphertext to a ``(tenant_id, provider,
    purpose)`` triple so a row swap inside the database is detected at
    decryption time:

    - Local backend uses AES-GCM AAD bytes.
    - Vault backend uses Transit ``context`` (requires ``derived: true``
      on the Transit key — see ADR-005).

    Implementations MUST be thread-safe: they are called concurrently
    from the FastAPI request thread pool and from the credential
    resolver's cache fill path.
    """

    #: Stable string identifier persisted in the ``backend`` column on
    #: ``tenant_credentials``. Lower-case, no spaces. New backends that
    #: come later (AWS KMS, GCP KMS, Azure KV) get their own value here.
    backend_id: str

    def encrypt(
        self,
        *,
        tenant_id: str,
        provider: str,
        purpose: str,
        plaintext: str,
    ) -> EncryptedBlob:
        """Encrypt *plaintext*. Implementations bind the ciphertext to
        the ``(tenant_id, provider, purpose)`` triple.

        Raises whatever the underlying primitive raises (``MasterKeyError``
        for local, :class:`engramia.exceptions.VaultBackendError` for vault).
        """
        ...

    def decrypt(
        self,
        *,
        tenant_id: str,
        provider: str,
        purpose: str,
        blob: EncryptedBlob,
    ) -> str:
        """Decrypt *blob*. Raises
        :class:`engramia.exceptions.DecryptionError` on auth failure
        (tampering, wrong context, wrong key).
        """
        ...

    def health_check(self) -> None:
        """Probe the backend's availability. Called from
        ``/v1/health/deep``. MUST raise on failure rather than return
        a status — the caller wraps the exception into a structured
        health response.
        """
        ...

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Local AES-GCM credential backend.

Wraps :class:`engramia.credentials.crypto.AESGCMCipher` to satisfy the
:class:`engramia.credentials.backend.CredentialBackend` Protocol.

Identity-preserving with the pre-Phase-6.6-#6 implementation: ciphertext
output bytes are the same; AAD is identical (``f"{tenant}:{provider}:{purpose}"``);
existing rows in ``tenant_credentials`` decrypt unchanged. The Backend
abstraction is a pure refactor on this side — the change is visible only
in the call signature (Backend takes kwargs, AESGCMCipher takes positional
``aad`` bytes).

This backend remains the **default** for self-hosted deployments under
BSL: requiring Vault to run from source would be hostile. Operators who
need master-key separation flip to :class:`VaultTransitBackend` via
``ENGRAMIA_CREDENTIALS_BACKEND=vault``.
"""

from __future__ import annotations

from typing import Final

from engramia.credentials.backend import CredentialBackend, EncryptedBlob
from engramia.credentials.crypto import AESGCMCipher

#: Stable string identifier for ``backend`` column rows. Mirrored in
#: :mod:`engramia.credentials.backends` so callers don't import the
#: backend modules just for the constant.
BACKEND_ID: Final[str] = "local"


class LocalAESGCMBackend(CredentialBackend):
    """AES-256-GCM backed by an in-process master key.

    Holds a single :class:`AESGCMCipher` instance. Thread-safe: the
    underlying ``cryptography`` ``AESGCM`` object is re-entrant and the
    backend has no mutable state besides the cipher.

    Args:
        cipher: An initialised :class:`AESGCMCipher`. Tests pass synthetic
            keys here directly. Production callers should use
            :meth:`from_env`.
    """

    backend_id = BACKEND_ID

    def __init__(self, cipher: AESGCMCipher) -> None:
        self._cipher = cipher

    @classmethod
    def from_env(cls) -> LocalAESGCMBackend:
        """Build a backend from ``ENGRAMIA_CREDENTIALS_KEY`` env var.

        Raises:
            MasterKeyError: env var unset, malformed base64, or wrong length.
        """
        return cls(AESGCMCipher.from_env())

    @property
    def key_version(self) -> int:
        """Master-key generation marker, mirrored into every
        :class:`EncryptedBlob` we produce. Bumped by the master-key
        rotation tooling (out of scope for #6).
        """
        return self._cipher.key_version

    def encrypt(
        self,
        *,
        tenant_id: str,
        provider: str,
        purpose: str,
        plaintext: str,
    ) -> EncryptedBlob:
        aad = _aad_for(tenant_id, provider, purpose)
        ciphertext, nonce, auth_tag = self._cipher.encrypt(plaintext, aad)
        return EncryptedBlob(
            ciphertext=ciphertext,
            nonce=nonce,
            auth_tag=auth_tag,
            key_version=self._cipher.key_version,
        )

    def decrypt(
        self,
        *,
        tenant_id: str,
        provider: str,
        purpose: str,
        blob: EncryptedBlob,
    ) -> str:
        aad = _aad_for(tenant_id, provider, purpose)
        return self._cipher.decrypt(blob.ciphertext, blob.nonce, blob.auth_tag, aad)

    def health_check(self) -> None:
        """Local backend is healthy iff the cipher is loaded.

        We do not perform a probe encrypt+decrypt here because the cipher
        is already validated at construction (``from_env`` raises on
        malformed keys). A late-arriving failure would mean memory
        corruption and is out of scope.
        """
        # Implicit: the cipher exists or __init__ would have raised.


def _aad_for(tenant_id: str, provider: str, purpose: str) -> bytes:
    """Build the AAD bytes the AES-GCM tag covers.

    Same shape as the pre-refactor resolver used (``f"{tenant_id}:{provider}:{purpose}"``)
    so existing rows decrypt unchanged. The AAD is the row-substitution
    defence — swapping a row to another tenant in the DB makes the
    decrypt fail because the resolver passes the *new* row's tenant_id
    here, which won't match the encrypted-time AAD.
    """
    return f"{tenant_id}:{provider}:{purpose}".encode()

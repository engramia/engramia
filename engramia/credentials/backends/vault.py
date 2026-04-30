# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Vault Transit credential backend.

Implements :class:`engramia.credentials.backend.CredentialBackend` against
HashiCorp Vault's Transit secrets engine. Master key never leaves Vault;
every encrypt/decrypt is logged in Vault's audit backend.

Key invariants:

- Vault Transit key MUST be created with ``derived: true`` so the
  ``context`` parameter participates in the per-row key derivation.
  Operator runs ``vault write transit/keys/engramia derived=true type=aes256-gcm96``
  during setup. See ``Ops/runbooks/vault-credentials-setup.md``.

- ``context`` mirrors the local backend's AAD shape:
  ``f"{tenant_id}:{provider}:{purpose}".encode()``. Same row-substitution
  defence; row swap inside our DB → Vault decrypt fails because the
  reconstructed context won't match the encrypt-time context.

- :class:`engramia.credentials.backend.EncryptedBlob` encodes Vault
  ciphertext as **bytes-of-the-string**: the UTF-8 of the ``vault:vN:...``
  format. This keeps the DB column shape identical for both backends.
  ``nonce`` and ``auth_tag`` fields stay empty (``b""``) for vault rows.
"""

from __future__ import annotations

import logging
from typing import Final

from engramia.credentials.backend import CredentialBackend, EncryptedBlob
from engramia.credentials.backends.vault_client import VaultClient

#: Stable string identifier persisted in the ``backend`` column.
BACKEND_ID: Final[str] = "vault"

_log = logging.getLogger(__name__)


class VaultTransitBackend(CredentialBackend):
    """HashiCorp Vault Transit-backed credential cipher.

    Args:
        client: A configured :class:`VaultClient` (already logged in).
            Tests inject a mock client here; production builds via
            :meth:`from_env`.
    """

    backend_id = BACKEND_ID

    def __init__(self, client: VaultClient) -> None:
        self._client = client

    @classmethod
    def from_env(cls, env: dict[str, str]) -> VaultTransitBackend:
        """Construct from ``ENGRAMIA_VAULT_*`` env vars.

        Required:
            ENGRAMIA_VAULT_ADDR
            ENGRAMIA_VAULT_ROLE_ID
            ENGRAMIA_VAULT_SECRET_ID

        Optional:
            ENGRAMIA_VAULT_NAMESPACE
            ENGRAMIA_VAULT_TRANSIT_PATH    (default: 'transit')
            ENGRAMIA_VAULT_TRANSIT_KEY     (default: 'engramia')
            ENGRAMIA_VAULT_TLS_VERIFY      (default: 'true')
            ENGRAMIA_VAULT_CA_CERT         (path to CA bundle)
            ENGRAMIA_VAULT_REQUEST_TIMEOUT (default: 5.0)

        Raises:
            VaultBackendError: AppRole login fails.
            ValueError: a required env var is missing.
        """
        required = ("ENGRAMIA_VAULT_ADDR", "ENGRAMIA_VAULT_ROLE_ID", "ENGRAMIA_VAULT_SECRET_ID")
        missing = [k for k in required if not env.get(k, "").strip()]
        if missing:
            raise ValueError(f"Missing required env vars for vault backend: {', '.join(missing)}")

        verify_env = env.get("ENGRAMIA_VAULT_TLS_VERIFY", "true").strip().lower()
        ca_cert = env.get("ENGRAMIA_VAULT_CA_CERT", "").strip()
        if ca_cert:
            verify: bool | str = ca_cert
        elif verify_env in ("false", "0", "no"):
            verify = False
            _log.warning(
                "SECURITY: ENGRAMIA_VAULT_TLS_VERIFY=false — Vault TLS "
                "certificate validation is disabled. Use only in dev."
            )
        else:
            verify = True

        client = VaultClient(
            addr=env["ENGRAMIA_VAULT_ADDR"].strip(),
            role_id=env["ENGRAMIA_VAULT_ROLE_ID"].strip(),
            secret_id=env["ENGRAMIA_VAULT_SECRET_ID"].strip(),
            transit_path=env.get("ENGRAMIA_VAULT_TRANSIT_PATH", "transit").strip(),
            transit_key=env.get("ENGRAMIA_VAULT_TRANSIT_KEY", "engramia").strip(),
            namespace=env.get("ENGRAMIA_VAULT_NAMESPACE", "").strip() or None,
            verify=verify,
            request_timeout=float(env.get("ENGRAMIA_VAULT_REQUEST_TIMEOUT", "5.0")),
        )
        return cls(client)

    def encrypt(
        self,
        *,
        tenant_id: str,
        provider: str,
        purpose: str,
        plaintext: str,
    ) -> EncryptedBlob:
        ctx = _context_for(tenant_id, provider, purpose)
        ciphertext_str, key_version = self._client.encrypt(plaintext=plaintext, context=ctx)
        return EncryptedBlob(
            ciphertext=ciphertext_str.encode("ascii"),
            nonce=b"",
            auth_tag=b"",
            key_version=key_version,
        )

    def decrypt(
        self,
        *,
        tenant_id: str,
        provider: str,
        purpose: str,
        blob: EncryptedBlob,
    ) -> str:
        ctx = _context_for(tenant_id, provider, purpose)
        ciphertext_str = blob.ciphertext.decode("ascii")
        return self._client.decrypt(ciphertext=ciphertext_str, context=ctx)

    def health_check(self) -> None:
        self._client.health_check()


def _context_for(tenant_id: str, provider: str, purpose: str) -> bytes:
    """Build the Vault Transit ``context`` bytes.

    Same shape as the local backend's AAD. Vault's derived-key feature
    derives a per-context encryption key from the master key + this
    context — so a row swap in our DB triggers a decrypt failure on
    Vault's side, mirroring the AES-GCM AAD check.
    """
    return f"{tenant_id}:{provider}:{purpose}".encode()

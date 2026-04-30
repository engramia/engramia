# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Credential backend factory + concrete implementations.

Choose at startup via ``ENGRAMIA_CREDENTIALS_BACKEND``:

- ``local`` (default) — :class:`LocalAESGCMBackend`. Master key in env.
- ``vault`` — :class:`VaultTransitBackend`. Requires ``engramia[vault]``
  extra (hvac SDK) plus ``ENGRAMIA_VAULT_*`` env vars.

The factory returns a :class:`engramia.credentials.backend.CredentialBackend`.
The resolver does not need to know which subclass — dispatch happens by
``backend_id`` on every row, so a hybrid mid-migration deployment works.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from engramia.credentials.backends.local import LocalAESGCMBackend

if TYPE_CHECKING:
    from engramia.credentials.backend import CredentialBackend

_log = logging.getLogger(__name__)

#: Stable IDs persisted in the ``backend`` column on ``tenant_credentials``.
LOCAL_BACKEND_ID = "local"
VAULT_BACKEND_ID = "vault"


def make_backend_from_env(env: dict[str, str] | None = None) -> CredentialBackend:
    """Construct the configured backend.

    Reads (with sensible defaults so dev/test rarely needs explicit config):

    Local backend:
        ENGRAMIA_CREDENTIALS_BACKEND=local           (default)
        ENGRAMIA_CREDENTIALS_KEY=<base64 32B>        (required)

    Vault backend:
        ENGRAMIA_CREDENTIALS_BACKEND=vault
        ENGRAMIA_VAULT_ADDR=https://vault.internal:8200
        ENGRAMIA_VAULT_NAMESPACE=                    (Vault Enterprise; optional)
        ENGRAMIA_VAULT_ROLE_ID=<UUID>                (AppRole)
        ENGRAMIA_VAULT_SECRET_ID=<UUID>              (AppRole)
        ENGRAMIA_VAULT_TRANSIT_PATH=transit          (default)
        ENGRAMIA_VAULT_TRANSIT_KEY=engramia          (default)
        ENGRAMIA_VAULT_TLS_VERIFY=true               (default)
        ENGRAMIA_VAULT_CA_CERT=/path/to/ca.pem       (optional)
        ENGRAMIA_VAULT_REQUEST_TIMEOUT=5.0           (default, seconds)

    Args:
        env: Override ``os.environ`` (test seam). ``None`` means real env.

    Returns:
        A backend instance ready for use. The local backend logs in
        immediately to verify the master key parses; the Vault backend
        performs an AppRole login at construction so a misconfigured
        Vault fails startup loudly rather than silently at the first
        decrypt call.

    Raises:
        MasterKeyError: local backend selected but master key missing/invalid.
        VaultBackendError: vault backend selected but startup login failed.
        ImportError: vault backend selected but ``engramia[vault]`` not installed.
        ValueError: unknown backend id.
    """
    e = env if env is not None else dict(os.environ)
    backend = e.get("ENGRAMIA_CREDENTIALS_BACKEND", LOCAL_BACKEND_ID).lower()

    if backend == LOCAL_BACKEND_ID:
        _log.info("Credential backend: local (AES-256-GCM, master key from env).")
        return LocalAESGCMBackend.from_env()

    if backend == VAULT_BACKEND_ID:
        try:
            from engramia.credentials.backends.vault import VaultTransitBackend
        except ImportError as exc:  # pragma: no cover  — depends on optional dep
            raise ImportError(
                "ENGRAMIA_CREDENTIALS_BACKEND=vault requires the [vault] extra. "
                "Install with: pip install 'engramia[vault]'"
            ) from exc
        _log.info(
            "Credential backend: vault (Transit at %s, key=%s).",
            e.get("ENGRAMIA_VAULT_ADDR", "<unset>"),
            e.get("ENGRAMIA_VAULT_TRANSIT_KEY", "engramia"),
        )
        return VaultTransitBackend.from_env(e)

    raise ValueError(
        f"Unknown ENGRAMIA_CREDENTIALS_BACKEND={backend!r}. Expected one of: {LOCAL_BACKEND_ID}, {VAULT_BACKEND_ID}."
    )


__all__ = [
    "LOCAL_BACKEND_ID",
    "VAULT_BACKEND_ID",
    "LocalAESGCMBackend",
    "make_backend_from_env",
]

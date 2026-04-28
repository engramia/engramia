# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""AES-256-GCM cipher for credential storage at rest.

Backs the local-mode credential store (``ENGRAMIA_CREDENTIALS_BACKEND=local``).
Uses authenticated encryption (AES-GCM) with per-record random nonces and
caller-supplied AAD (additional authenticated data) so that:

- Ciphertext alone is opaque without the master key.
- Tampering with ``encrypted_key``, ``nonce``, ``auth_tag``, or AAD raises
  :class:`engramia.exceptions.DecryptionError`.
- Swapping a row between tenants fails the AAD check (the resolver binds AAD
  to ``f"{tenant_id}:{provider}:{purpose}"`` so a swapped row decrypts under
  the wrong AAD).

Master key lifecycle:
    Operator generates a 32-byte key once via :func:`generate_master_key` (or
    ``openssl rand -base64 32``), stores it in SOPS-encrypted .env, and
    exposes it as ``ENGRAMIA_CREDENTIALS_KEY``. Loss of this key means
    permanent loss of all tenant credentials — operators MUST back it up
    separately from the database (e.g. 1Password, paper in safe).

For Vault Transit / KMS backends, swap this module via dependency injection
(see ``ENGRAMIA_CREDENTIALS_BACKEND`` env var, future).
"""

from __future__ import annotations

import base64
import os
import secrets
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from engramia.exceptions import DecryptionError, MasterKeyError

_MASTER_KEY_ENV: Final[str] = "ENGRAMIA_CREDENTIALS_KEY"
_MASTER_KEY_BYTES: Final[int] = 32  # AES-256
_NONCE_BYTES: Final[int] = 12  # GCM standard
_AUTH_TAG_BYTES: Final[int] = 16  # GCM standard

# AESGCM appends the 16-byte authentication tag to the ciphertext on encrypt
# and expects it appended on decrypt. We split/recombine to match the DB
# schema which stores ``encrypted_key`` and ``auth_tag`` in separate columns
# (operationally clearer for audit and re-encryption tooling).
_GCM_TAG_LEN: Final[int] = 16


class AESGCMCipher:
    """AES-256-GCM symmetric cipher bound to a master key.

    Thread-safe: the underlying ``cryptography`` ``AESGCM`` object is
    re-entrant. One instance per process is sufficient.

    Args:
        master_key: 32-byte AES-256 key. In production, load via
            :meth:`from_env`. Tests may pass synthetic keys directly.
        key_version: Generation marker for master-key rotation. Stored
            alongside ciphertext in the DB; older versions are decryptable
            until the rotation migration sweeps them. Default ``1``.

    Raises:
        MasterKeyError: ``master_key`` is not exactly ``_MASTER_KEY_BYTES`` bytes.
    """

    __slots__ = ("_aesgcm", "key_version")

    def __init__(self, master_key: bytes, *, key_version: int = 1) -> None:
        if not isinstance(master_key, (bytes, bytearray)):
            raise MasterKeyError(f"master_key must be bytes, got {type(master_key).__name__}")
        if len(master_key) != _MASTER_KEY_BYTES:
            raise MasterKeyError(
                f"master_key must be {_MASTER_KEY_BYTES} bytes (256 bits), got {len(master_key)} bytes"
            )
        if key_version < 1:
            raise MasterKeyError(f"key_version must be >= 1, got {key_version}")
        self._aesgcm = AESGCM(bytes(master_key))
        self.key_version = key_version

    @classmethod
    def from_env(cls, *, key_version: int = 1) -> AESGCMCipher:
        """Construct a cipher from ``ENGRAMIA_CREDENTIALS_KEY``.

        The env var must contain a base64-encoded 32-byte key (44 characters
        with padding, 43 without). Whitespace is stripped.

        Raises:
            MasterKeyError: env var is unset, malformed base64, or wrong length.
        """
        raw = os.environ.get(_MASTER_KEY_ENV, "").strip()
        if not raw:
            raise MasterKeyError(
                f"{_MASTER_KEY_ENV} is not set. Generate one with "
                f"`python -c 'from engramia.credentials import generate_master_key; "
                f"print(generate_master_key())'` and store it in your SOPS-encrypted "
                f".env file."
            )
        try:
            key_bytes = base64.b64decode(raw, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise MasterKeyError(f"{_MASTER_KEY_ENV} is not valid base64: {exc}") from exc
        return cls(key_bytes, key_version=key_version)

    def encrypt(self, plaintext: str, aad: bytes) -> tuple[bytes, bytes, bytes]:
        """Encrypt a UTF-8 string with a fresh random nonce.

        Args:
            plaintext: The credential value (LLM API key) to encrypt.
                Must be non-empty; the encoder rejects empty strings to catch
                accidental clearing of credentials at the call site.
            aad: Additional authenticated data — bound to the ciphertext via
                the GCM tag. The resolver MUST pass the same AAD on decrypt
                or the operation fails. Convention:
                ``f"{tenant_id}:{provider}:{purpose}".encode()``.

        Returns:
            Tuple of ``(ciphertext, nonce, auth_tag)`` where:
                - ``ciphertext``: encrypted bytes (same length as plaintext)
                - ``nonce``: 12 random bytes (must be stored alongside)
                - ``auth_tag``: 16-byte GCM tag (must be stored alongside)

        Raises:
            ValueError: ``plaintext`` is empty or AAD is empty.
        """
        if not plaintext:
            raise ValueError("plaintext must be non-empty")
        if not aad:
            raise ValueError("aad must be non-empty (use tenant_id:provider:purpose)")
        nonce = secrets.token_bytes(_NONCE_BYTES)
        ct_with_tag = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), aad)
        # cryptography returns ciphertext || tag concatenated; split for DB columns
        ciphertext = ct_with_tag[:-_GCM_TAG_LEN]
        auth_tag = ct_with_tag[-_GCM_TAG_LEN:]
        return ciphertext, nonce, auth_tag

    def decrypt(
        self,
        ciphertext: bytes,
        nonce: bytes,
        auth_tag: bytes,
        aad: bytes,
    ) -> str:
        """Decrypt a ciphertext to its original UTF-8 string.

        Args:
            ciphertext: Encrypted bytes from a previous :meth:`encrypt` call.
            nonce: 12-byte nonce stored alongside the ciphertext.
            auth_tag: 16-byte GCM tag stored alongside the ciphertext.
            aad: Same AAD bytes used at encryption. AAD mismatch = decryption
                failure; this is the row-substitution defence (an attacker
                swapping ``encrypted_key`` between tenants would supply the
                wrong AAD when the resolver tries to decrypt).

        Returns:
            Original plaintext string.

        Raises:
            DecryptionError: AAD mismatch, tampered ciphertext/nonce/tag,
                wrong master key, or other AES-GCM authentication failure.
                The exception message intentionally avoids leaking which
                specific check failed (timing-safe behaviour from the
                underlying library).
            ValueError: Malformed input lengths (caught early before the
                cipher call to give better operator diagnostics).
        """
        if len(nonce) != _NONCE_BYTES:
            raise ValueError(f"nonce must be {_NONCE_BYTES} bytes, got {len(nonce)}")
        if len(auth_tag) != _AUTH_TAG_BYTES:
            raise ValueError(f"auth_tag must be {_AUTH_TAG_BYTES} bytes, got {len(auth_tag)}")
        if not aad:
            raise ValueError("aad must be non-empty")
        ct_with_tag = bytes(ciphertext) + bytes(auth_tag)
        try:
            plaintext_bytes = self._aesgcm.decrypt(bytes(nonce), ct_with_tag, bytes(aad))
        except InvalidTag as exc:
            # Do NOT include row identifiers, key fingerprints, or AAD content
            # in the error message — DecryptionError surfaces to logs and we
            # don't want to leak which (tenant, provider) tuple was being
            # decrypted on a tampering attempt.
            raise DecryptionError(
                "AES-GCM authentication failed: ciphertext, nonce, auth_tag, "
                "or AAD does not match — possible tampering, wrong master key, "
                "or AAD mismatch."
            ) from exc
        return plaintext_bytes.decode("utf-8")


def generate_master_key() -> str:
    """Generate a fresh 32-byte AES-256 master key as a base64 string.

    Use once during operator setup; persist the output in SOPS-encrypted
    .env as ``ENGRAMIA_CREDENTIALS_KEY``.

    Returns:
        URL-safe base64 string (44 characters, with padding).

    Example::

        $ python -c 'from engramia.credentials import generate_master_key; print(generate_master_key())'
        x9TtL4mE2pK...=
    """
    return base64.b64encode(secrets.token_bytes(_MASTER_KEY_BYTES)).decode("ascii")

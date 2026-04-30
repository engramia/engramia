# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Custom exception hierarchy for Engramia.

Public API callers should catch these instead of RuntimeError/ValueError
for more precise error handling.

Hierarchy::

    EngramiaError (base)
    ├── ProviderError       — LLM or embedding provider missing or failed
    ├── StorageError        — Storage backend read/write failures
    ├── ValidationError     — Input data failed validation
    ├── QuotaExceededError  — Quota reached
    ├── AuthorizationError  — Operation not permitted for role
    └── CredentialsError    — Credential storage / encryption failures
        ├── MasterKeyError       — Master encryption key missing or invalid
        ├── DecryptionError      — Ciphertext decryption failed (tampered or wrong key)
        └── VaultBackendError    — Vault Transit backend unreachable / auth failed
"""


class EngramiaError(Exception):
    """Base class for all Engramia exceptions."""


class ProviderError(EngramiaError):
    """Raised when an LLM or embedding provider is missing or fails.

    Example::

        try:
            result = memory.evaluate(task, code)
        except ProviderError:
            print("No LLM configured — skipping evaluation")
    """


class StorageError(EngramiaError):
    """Raised for storage backend errors (connection failures, corrupt data)."""


class ValidationError(EngramiaError):
    """Raised when input data fails validation (too long, empty, out of range)."""


class QuotaExceededError(EngramiaError):
    """Raised when a project's pattern quota has been reached.

    Example::

        try:
            result = memory.learn(task, code, score)
        except QuotaExceededError:
            print("Pattern quota reached — delete old patterns or upgrade plan.")
    """


class AuthorizationError(EngramiaError):
    """Raised when an operation is not permitted for the current role."""


class CredentialsError(EngramiaError):
    """Base class for credential storage and encryption errors."""


class MasterKeyError(CredentialsError):
    """Raised when the credential master key is missing, malformed, or wrong size.

    The credential subsystem requires a 32-byte AES-256 master key supplied via
    the ``ENGRAMIA_CREDENTIALS_KEY`` environment variable as a base64 string.
    Operators with BYOK enabled (``ENGRAMIA_BYOK_ENABLED=true``) must configure
    this before startup; the API refuses to serve credential operations
    otherwise.
    """


class DecryptionError(CredentialsError):
    """Raised when AES-GCM decryption fails — wrong key, tampered ciphertext,
    AAD mismatch, or nonce reuse.

    Logged at WARNING level by ``CredentialResolver`` so security alerts can
    fire on suspected tampering. The plaintext is *not* recoverable by retry —
    the row is marked invalid and the tenant must re-enter the credential.
    """


class VaultBackendError(CredentialsError):
    """Raised when the Vault Transit backend cannot complete a request.

    Specifically used by ``VaultTransitBackend`` for transport errors,
    authentication failures, and 5xx responses from the Vault server.
    Distinct from :class:`DecryptionError` because the failure mode is
    *infrastructure* (Vault unreachable, token expired, network) rather
    than *integrity* (wrong key, tampered blob). The resolver maps both
    to ``None`` for the caller, but the audit log distinguishes them so
    operators can tell "row is corrupt" from "Vault is down".
    """

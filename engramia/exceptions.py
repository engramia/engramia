# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Custom exception hierarchy for Engramia.

Public API callers should catch these instead of RuntimeError/ValueError
for more precise error handling.

Hierarchy::

    EngramiaError (base)
    ├── ProviderError   — LLM or embedding provider missing or failed
    ├── StorageError    — Storage backend read/write failures
    └── ValidationError — Input data failed validation
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

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
            result = brain.evaluate(task, code)
        except ProviderError:
            print("No LLM configured — skipping evaluation")
    """


class StorageError(EngramiaError):
    """Raised for storage backend errors (connection failures, corrupt data)."""


class ValidationError(EngramiaError):
    """Raised when input data fails validation (too long, empty, out of range)."""

"""Custom exception hierarchy for Agent Brain.

Public API callers should catch these instead of RuntimeError/ValueError
for more precise error handling.

Hierarchy::

    BrainError (base)
    ├── ProviderError   — LLM or embedding provider missing or failed
    ├── StorageError    — Storage backend read/write failures
    └── ValidationError — Input data failed validation
"""


class BrainError(Exception):
    """Base class for all Agent Brain exceptions."""


class ProviderError(BrainError):
    """Raised when an LLM or embedding provider is missing or fails.

    Example::

        try:
            result = brain.evaluate(task, code)
        except ProviderError:
            print("No LLM configured — skipping evaluation")
    """


class StorageError(BrainError):
    """Raised for storage backend errors (connection failures, corrupt data)."""


class ValidationError(BrainError):
    """Raised when input data fails validation (too long, empty, out of range)."""

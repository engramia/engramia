"""Tests for the custom exception hierarchy."""

import pytest

from agent_brain.exceptions import (
    BrainError,
    ProviderError,
    StorageError,
    ValidationError,
)


class TestExceptionHierarchy:
    def test_all_inherit_from_brain_error(self):
        assert issubclass(ProviderError, BrainError)
        assert issubclass(StorageError, BrainError)
        assert issubclass(ValidationError, BrainError)

    def test_all_inherit_from_exception(self):
        assert issubclass(BrainError, Exception)

    def test_provider_error_catchable_as_brain_error(self):
        with pytest.raises(BrainError):
            raise ProviderError("no LLM")

    def test_validation_error_catchable_as_brain_error(self):
        with pytest.raises(BrainError):
            raise ValidationError("bad input")

    def test_storage_error_catchable_as_brain_error(self):
        with pytest.raises(BrainError):
            raise StorageError("disk full")

    def test_provider_error_message(self):
        exc = ProviderError("missing key")
        assert "missing key" in str(exc)

    def test_exceptions_exported_from_package(self):
        import agent_brain

        assert hasattr(agent_brain, "BrainError")
        assert hasattr(agent_brain, "ProviderError")
        assert hasattr(agent_brain, "ValidationError")
        assert hasattr(agent_brain, "StorageError")

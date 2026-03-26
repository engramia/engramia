"""Tests for the custom exception hierarchy."""

import pytest

from remanence.exceptions import (
    RemanenceError,
    ProviderError,
    StorageError,
    ValidationError,
)


class TestExceptionHierarchy:
    def test_all_inherit_from_brain_error(self):
        assert issubclass(ProviderError, RemanenceError)
        assert issubclass(StorageError, RemanenceError)
        assert issubclass(ValidationError, RemanenceError)

    def test_all_inherit_from_exception(self):
        assert issubclass(RemanenceError, Exception)

    def test_provider_error_catchable_as_brain_error(self):
        with pytest.raises(RemanenceError):
            raise ProviderError("no LLM")

    def test_validation_error_catchable_as_brain_error(self):
        with pytest.raises(RemanenceError):
            raise ValidationError("bad input")

    def test_storage_error_catchable_as_brain_error(self):
        with pytest.raises(RemanenceError):
            raise StorageError("disk full")

    def test_provider_error_message(self):
        exc = ProviderError("missing key")
        assert "missing key" in str(exc)

    def test_exceptions_exported_from_package(self):
        import remanence

        assert hasattr(remanence, "RemanenceError")
        assert hasattr(remanence, "ProviderError")
        assert hasattr(remanence, "ValidationError")
        assert hasattr(remanence, "StorageError")

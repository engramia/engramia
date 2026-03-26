"""Tests for the custom exception hierarchy."""

import pytest

from engramia.exceptions import (
    EngramiaError,
    ProviderError,
    StorageError,
    ValidationError,
)


class TestExceptionHierarchy:
    def test_all_inherit_from_brain_error(self):
        assert issubclass(ProviderError, EngramiaError)
        assert issubclass(StorageError, EngramiaError)
        assert issubclass(ValidationError, EngramiaError)

    def test_all_inherit_from_exception(self):
        assert issubclass(EngramiaError, Exception)

    def test_provider_error_catchable_as_brain_error(self):
        with pytest.raises(EngramiaError):
            raise ProviderError("no LLM")

    def test_validation_error_catchable_as_brain_error(self):
        with pytest.raises(EngramiaError):
            raise ValidationError("bad input")

    def test_storage_error_catchable_as_brain_error(self):
        with pytest.raises(EngramiaError):
            raise StorageError("disk full")

    def test_provider_error_message(self):
        exc = ProviderError("missing key")
        assert "missing key" in str(exc)

    def test_exceptions_exported_from_package(self):
        import engramia

        assert hasattr(engramia, "EngramiaError")
        assert hasattr(engramia, "ProviderError")
        assert hasattr(engramia, "ValidationError")
        assert hasattr(engramia, "StorageError")

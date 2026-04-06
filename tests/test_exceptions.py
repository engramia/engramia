# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for the custom exception hierarchy."""

import pytest

from engramia.exceptions import (
    AuthorizationError,
    EngramiaError,
    ProviderError,
    QuotaExceededError,
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

    def test_quota_exceeded_inherits_from_engramia_error(self):
        assert issubclass(QuotaExceededError, EngramiaError)

    def test_authorization_inherits_from_engramia_error(self):
        assert issubclass(AuthorizationError, EngramiaError)

    def test_quota_exceeded_catchable_as_engramia_error(self):
        with pytest.raises(EngramiaError):
            raise QuotaExceededError("over limit")

    def test_authorization_error_catchable_as_engramia_error(self):
        with pytest.raises(EngramiaError):
            raise AuthorizationError("forbidden")

    def test_exceptions_exported_from_package(self):
        import engramia

        assert hasattr(engramia, "EngramiaError")
        assert hasattr(engramia, "ProviderError")
        assert hasattr(engramia, "ValidationError")
        assert hasattr(engramia, "StorageError")
        assert hasattr(engramia, "QuotaExceededError")
        assert hasattr(engramia, "AuthorizationError")

    def test_new_exceptions_in_all(self):
        import engramia

        assert "QuotaExceededError" in engramia.__all__
        assert "AuthorizationError" in engramia.__all__

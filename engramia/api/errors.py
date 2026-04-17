# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Structured error codes for API responses (F-05).

All API error responses include an ``error_code`` field taken from this
module so that clients can branch on machine-readable codes rather than
HTTP status numbers or free-form message strings.
"""

from __future__ import annotations


class ErrorCode(str):
    """String-based error code constants.

    Inheriting from ``str`` means values serialise directly in JSON without
    extra ``.value`` access (unlike ``enum.Enum``).
    """

    # Generic fallback
    ERROR = "ERROR"

    # 4xx client errors
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    RATE_LIMITED = "RATE_LIMITED"

    # 5xx server errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
    STORAGE_ERROR = "STORAGE_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


# Maps HTTP status codes to a default ErrorCode when the exception detail
# does not supply an explicit ``error_code``.
STATUS_TO_ERROR_CODE: dict[int, str] = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.QUOTA_EXCEEDED,
    500: ErrorCode.INTERNAL_ERROR,
    501: ErrorCode.PROVIDER_NOT_CONFIGURED,
    503: ErrorCode.STORAGE_ERROR,
}

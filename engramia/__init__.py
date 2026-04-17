# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
from importlib.metadata import PackageNotFoundError, version

from engramia.exceptions import (
    AuthorizationError,
    EngramiaError,
    ProviderError,
    QuotaExceededError,
    StorageError,
    ValidationError,
)
from engramia.memory import Memory
from engramia.sdk.webhook import EngramiaWebhookError

try:
    __version__ = version("engramia")
except PackageNotFoundError:
    __version__ = "0.0.0+dev"

__license__ = "BUSL-1.1"

__all__ = [
    "AuthorizationError",
    "EngramiaError",
    "EngramiaWebhookError",
    "Memory",
    "ProviderError",
    "QuotaExceededError",
    "StorageError",
    "ValidationError",
    "__license__",
    "__version__",
]

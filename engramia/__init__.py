# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
from importlib.metadata import PackageNotFoundError, version

from engramia.exceptions import EngramiaError, ProviderError, StorageError, ValidationError
from engramia.memory import Memory

try:
    __version__ = version("engramia")
except PackageNotFoundError:
    __version__ = "0.0.0+dev"

__license__ = "BUSL-1.1"

__all__ = [
    "EngramiaError",
    "Memory",
    "ProviderError",
    "StorageError",
    "ValidationError",
    "__license__",
    "__version__",
]

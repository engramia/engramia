# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Runtime version metadata for Engramia.

Single source of truth for all version-related constants exposed at runtime.
GIT_COMMIT and BUILD_TIME are injected at Docker build time via environment
variables (set in Dockerfile ARGs → ENV). In local dev without Docker they
fall back to safe placeholder values.
"""

import os
from importlib.metadata import PackageNotFoundError, version

try:
    APP_VERSION: str = version("engramia")
except PackageNotFoundError:
    APP_VERSION = "0.0.0+dev"

API_VERSION: str = "v1"
GIT_COMMIT: str = os.environ.get("GIT_COMMIT", "unknown")
BUILD_TIME: str = os.environ.get("BUILD_TIME", "unknown")

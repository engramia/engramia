# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""C04 — YAML Config Merging snippets."""

GOOD: dict = {
    "eval_score": 9.0,
    "output": "Merged config: {'db_host': 'prod-db', 'port': '5432', 'debug': 'false'}",
    "code": '''\
import os
from pathlib import Path
from typing import Any

import yaml


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base* (override wins on conflict)."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_merged_config(
    base_path: str | Path,
    override_path: str | Path | None = None,
    *,
    env_prefix: str = "",
) -> dict[str, Any]:
    """Merge YAML configs with optional environment variable overrides.

    Priority (highest wins): env vars > override.yaml > base.yaml.

    Args:
        base_path: Base configuration file.
        override_path: Optional override file layered on top of base.
        env_prefix: Only env vars with this prefix are applied (stripped).

    Returns:
        Merged configuration dict.
    """
    with Path(base_path).open() as fh:
        config: dict = yaml.safe_load(fh) or {}

    if override_path and Path(override_path).exists():
        with Path(override_path).open() as fh:
            overrides: dict = yaml.safe_load(fh) or {}
        config = _deep_merge(config, overrides)

    for key, value in os.environ.items():
        if env_prefix and not key.startswith(env_prefix):
            continue
        config_key = key[len(env_prefix):].lower() if env_prefix else key.lower()
        config[config_key] = value

    return config
''',
}

MEDIUM: dict = {
    "eval_score": 5.5,
    "output": "Merged config loaded.",
    "code": '''\
import os
import yaml

def merge_configs(base_path, override_path=None):
    with open(base_path) as f:
        config = yaml.safe_load(f) or {}
    if override_path:
        with open(override_path) as f:
            overrides = yaml.safe_load(f) or {}
        # BUG: dict.update is shallow — nested dicts are replaced, not merged
        config.update(overrides)
    # Apply env vars
    for k, v in os.environ.items():
        config[k.lower()] = v
    return config
''',
}

BAD: dict = {
    "eval_score": 2.0,
    "output": "",
    "code": '''\
import yaml
import os

def load_config(base, override=None):
    # BAD: yaml.load without Loader is unsafe (arbitrary code execution)
    config = yaml.load(open(base))
    if override:
        extra = yaml.load(open(override))
        config = extra  # BUG: replaces base entirely instead of merging
    # BUG: ignores env vars entirely
    return config
''',
}

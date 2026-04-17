# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""C03 — TOML Config Validation snippets."""

GOOD: dict = {
    "eval_score": 9.0,
    "output": "Config valid. Keys present: database, api_key, timeout.",
    "code": '''\
import tomllib
from pathlib import Path


def load_and_validate_toml(
    path: str | Path,
    required_keys: list[str],
) -> dict:
    """Load a TOML config file and assert all required keys are present.

    Args:
        path: Path to the .toml file.
        required_keys: Keys that must exist at the top level.

    Returns:
        Parsed config dict.

    Raises:
        FileNotFoundError: If the file does not exist.
        KeyError: If any required key is missing.
        tomllib.TOMLDecodeError: If the file is malformed TOML.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Config not found: {file_path}")

    with file_path.open("rb") as fh:
        config = tomllib.load(fh)

    missing = [k for k in required_keys if k not in config]
    if missing:
        raise KeyError(f"Missing required config keys: {missing}")

    return config
''',
}

MEDIUM: dict = {
    "eval_score": 6.0,
    "output": "Config loaded.",
    "code": """\
import tomllib

def validate_config(path, required_keys):
    with open(path, "rb") as f:
        config = tomllib.load(f)
    for key in required_keys:
        if key not in config:
            raise KeyError(f"Missing key: {key}")
    return config
""",
}

BAD: dict = {
    "eval_score": 2.5,
    "output": "",
    "code": """\
import re

def check_toml(path, keys):
    # BAD: parsing TOML with regex instead of tomllib
    content = open(path).read()
    result = {}
    for key in keys:
        match = re.search(rf"{key}\\s*=\\s*(.+)", content)
        if not match:
            raise Exception(f"key {key} not found")
        result[key] = match.group(1).strip()
    return result
""",
}

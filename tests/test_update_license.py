# SPDX-License-Identifier: BUSL-1.1
"""Tests for scripts/update_license.py — the BUSL per-version Change Date helper."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from update_license import (  # noqa: E402
    default_change_date,
    update_license_text,
)


SAMPLE_LICENSE = """License text copyright (c) 2020 MariaDB Corporation Ab, All Rights Reserved.

Parameters

Licensor: Marek Čermák

Licensed Work: Engramia, version 0.6.5. Licensed work is (c) 2026 Marek Čermák

Additional Use Grant: You may make production use of the Licensed Work...

Change Date: 2030-04-20

Change License: Apache 2.0

## Terms

The Licensor hereby grants you the right to copy, modify, create derivative
works...
"""


def test_bumps_version_and_date():
    out = update_license_text(
        SAMPLE_LICENSE, version="1.0.0", year=2028, change_date="2032-06-01"
    )
    assert "Licensed Work: Engramia, version 1.0.0." in out
    assert "(c) 2028 Marek Čermák" in out
    assert "Change Date: 2032-06-01" in out
    assert "0.6.5" not in out
    assert "2030-04-20" not in out


def test_idempotent_on_same_values():
    out = update_license_text(
        SAMPLE_LICENSE, version="0.6.5", year=2026, change_date="2030-04-20"
    )
    assert out == SAMPLE_LICENSE


def test_preserves_rest_of_license():
    out = update_license_text(
        SAMPLE_LICENSE, version="1.0.0", year=2028, change_date="2032-06-01"
    )
    assert "Licensor: Marek Čermák" in out
    assert "Additional Use Grant:" in out
    assert "Change License: Apache 2.0" in out
    assert "## Terms" in out


def test_custom_licensor():
    out = update_license_text(
        SAMPLE_LICENSE,
        version="1.0.0",
        year=2028,
        change_date="2032-06-01",
        licensor="Engramia s.r.o.",
    )
    assert "(c) 2028 Engramia s.r.o." in out


def test_raises_when_licensed_work_missing():
    broken = SAMPLE_LICENSE.replace("Licensed Work:", "Work Licensed:")
    with pytest.raises(ValueError, match="Licensed Work"):
        update_license_text(broken, version="1.0.0", year=2028, change_date="2032-06-01")


def test_raises_when_change_date_missing():
    broken = SAMPLE_LICENSE.replace("Change Date:", "Changed Date:")
    with pytest.raises(ValueError, match="Change Date"):
        update_license_text(broken, version="1.0.0", year=2028, change_date="2032-06-01")


def test_default_change_date_is_four_years_out():
    today = dt.date(2026, 4, 20)
    assert default_change_date(today) == "2030-04-20"

    # Feb 29 leap-year edge case: 2028-02-29 + 4y = 2032-02-29 (also leap)
    leap = dt.date(2028, 2, 29)
    assert default_change_date(leap) == "2032-02-29"

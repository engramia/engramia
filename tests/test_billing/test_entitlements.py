# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for ``billing.entitlements`` — feature tier gating."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from engramia.billing.entitlements import (
    FEATURE_MIN_TIER,
    TIER_ORDER,
    has_feature,
    require_feature,
    tier_at_least,
)
from engramia.billing.models import BillingSubscription


def _sub(plan_tier: str) -> BillingSubscription:
    """Build a minimal subscription for a tier without DB."""
    return BillingSubscription(tenant_id="t1", plan_tier=plan_tier)


class TestTierAtLeast:
    @pytest.mark.parametrize(
        ("current", "required", "expected"),
        [
            ("developer", "developer", True),
            ("developer", "pro", False),
            ("pro", "developer", True),
            ("business", "team", True),
            ("team", "business", False),
            ("enterprise", "business", True),
            # sandbox alias maps to developer
            ("sandbox", "developer", True),
            ("sandbox", "pro", False),
            # unknown -> never grants
            ("garbage", "developer", False),
            ("garbage", "enterprise", False),
        ],
    )
    def test_ordering(self, current: str, required: str, expected: bool) -> None:
        assert tier_at_least(current, required) is expected


class TestRequireFeature:
    def test_allows_when_tier_matches(self) -> None:
        # No exception
        require_feature(_sub("business"), "byok.role_models")

    def test_allows_when_tier_higher(self) -> None:
        require_feature(_sub("enterprise"), "byok.role_models")

    def test_blocks_when_tier_lower(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            require_feature(_sub("pro"), "byok.role_models")
        assert exc_info.value.status_code == 402
        body = exc_info.value.detail
        assert body["error_code"] == "ENTITLEMENT_REQUIRED"
        assert body["feature"] == "byok.role_models"
        assert body["current_tier"] == "pro"
        assert body["required_tier"] == "business"
        assert "upgrade_url" in body

    def test_blocks_developer(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            require_feature(_sub("developer"), "byok.failover_chain")
        assert exc_info.value.status_code == 402

    def test_unknown_tier_blocks_all_paid_features(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            require_feature(_sub("garbage"), "byok.role_models")
        assert exc_info.value.status_code == 402

    def test_unknown_feature_raises_keyerror(self) -> None:
        # Programmer error — not a runtime user error.
        with pytest.raises(KeyError):
            require_feature(_sub("business"), "byok.does_not_exist")


class TestHasFeature:
    def test_returns_true_for_eligible(self) -> None:
        assert has_feature(_sub("business"), "byok.role_models") is True

    def test_returns_false_for_ineligible(self) -> None:
        assert has_feature(_sub("pro"), "byok.role_models") is False

    def test_does_not_raise_on_low_tier(self) -> None:
        # Counterpart to require_feature — has_feature is the UI banner path
        # and must NOT raise.
        assert has_feature(_sub("developer"), "byok.role_models") is False


class TestTierOrderInsertionSafety:
    """Guard against regressions when a future tier is inserted."""

    def test_tier_order_is_strictly_increasing(self) -> None:
        # If someone reorders TIER_ORDER incorrectly (e.g. puts business
        # before pro) every entitlement check inverts. The list shape itself
        # is the invariant.
        assert TIER_ORDER == ["developer", "pro", "team", "business", "enterprise"]

    def test_every_feature_min_tier_is_known(self) -> None:
        for feature, min_tier in FEATURE_MIN_TIER.items():
            assert min_tier in TIER_ORDER, f"feature {feature!r} -> unknown tier {min_tier!r}"

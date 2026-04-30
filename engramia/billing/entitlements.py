# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Feature entitlement gating — qualitative tier checks.

Distinct from :mod:`engramia.billing.enforcement`: enforcement checks
*quantitative* limits (counter >= limit -> HTTP 429); entitlements check
*qualitative* feature access (tier < required -> HTTP 402). Mixing the two
in one module risks a refactor accidentally turning a paywall (402) into a
quota error (429), which presents to the user as the wrong upgrade path.

Tiers are ordered by an explicit list — ``TIER_ORDER.index(tier)`` rather
than a magic-number rank — so inserting a new tier (e.g. a future
``"starter"`` between developer and pro) is a one-line change.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from engramia.billing.models import BillingSubscription

# Ordered tier list — increasing capability. Insertion-safe (add a new tier
# in the right slot, no other module needs to change).
TIER_ORDER: list[str] = ["developer", "pro", "team", "business", "enterprise"]

# Legacy alias for the pre-6.6 free tier name. Anything that still resolves
# to ``"sandbox"`` is treated as developer-equivalent for entitlement
# purposes (matches PLAN_LIMITS sandbox alias in models.py).
_TIER_ALIASES: dict[str, str] = {"sandbox": "developer"}


# Feature -> minimum tier mapping. Keep one canonical name per feature so
# the Dashboard's UI gating mirror (``Dashboard/src/lib/entitlements.ts``)
# can hardcode the same strings without the risk of typos drifting apart.
FEATURE_MIN_TIER: dict[str, str] = {
    "byok.role_models": "business",
    "byok.failover_chain": "business",
    "byok.role_cost_ceiling": "business",  # follow-up #2b
}


def _normalised_tier(tier: str) -> str:
    return _TIER_ALIASES.get(tier, tier)


def tier_at_least(current: str, required: str) -> bool:
    """True when ``current`` is the same or higher tier than ``required``.

    Unknown tier names are treated as the lowest tier (developer) so a
    misconfigured DB row never silently grants paid features.
    """
    cur = _normalised_tier(current)
    req = _normalised_tier(required)
    try:
        return TIER_ORDER.index(cur) >= TIER_ORDER.index(req)
    except ValueError:
        return False


def require_feature(subscription: BillingSubscription, feature: str) -> None:
    """Raise HTTP 402 ENTITLEMENT_REQUIRED when the tier is below the gate.

    Call this from request handlers (or, preferably, as a route-level
    dependency) before performing the gated action. The error body carries
    the current and required tier so the dashboard can render the right
    upgrade CTA without parsing the human message.

    Args:
        subscription: The active tenant's BillingSubscription.
        feature: Feature key, e.g. ``"byok.role_models"``. Must be in
            :data:`FEATURE_MIN_TIER` — KeyError is a programmer error
            (never reach runtime in tested code paths).

    Raises:
        HTTPException: 402 with structured error body.
        KeyError: if ``feature`` is not registered.
    """
    min_tier = FEATURE_MIN_TIER[feature]
    if not tier_at_least(subscription.plan_tier, min_tier):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error_code": "ENTITLEMENT_REQUIRED",
                "feature": feature,
                "current_tier": subscription.plan_tier,
                "required_tier": min_tier,
                "upgrade_url": "https://engramia.dev/pricing",
                "detail": (
                    f"Feature {feature!r} requires the {min_tier!r} tier or higher. "
                    f"Current tier: {subscription.plan_tier!r}."
                ),
            },
        )


def has_feature(subscription: BillingSubscription, feature: str) -> bool:
    """Non-raising variant — useful for UI banner logic on the server side."""
    return tier_at_least(subscription.plan_tier, FEATURE_MIN_TIER[feature])

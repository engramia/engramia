# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Stripe SDK private-API safety net.

BillingService.handle_webhook_event() and StripeClient back-fetch both rely
on StripeObject._to_dict_recursive() (see service.py:498-504, 614-619). It
is private API but has been stable across the 15.x line.

If a future Stripe SDK release renames or drops the helper, this test fails
fast and pins the breakage to the SDK upgrade — instead of surfacing as a
silent webhook handler regression where event payloads are passed straight
through (the `else` branch in handle_webhook_event) and downstream `.get()`
calls explode on the StripeObject's missing dict API.

Pair this test with the version pin in pyproject.toml ([project.optional-dependencies].billing).
"""

import pytest

stripe = pytest.importorskip("stripe", reason="billing extra not installed")

# Stripe 15.x exposes StripeObject at the private module path _stripe_object.
# Earlier 14.x shipped it as `stripe.stripe_object.StripeObject` and `stripe.StripeObject`.
# Try both so this test survives a covered minor bump within 15.x while still
# failing fast if the symbol disappears entirely.
try:
    from stripe._stripe_object import StripeObject  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover — fallback path for older 15.x
    from stripe.stripe_object import StripeObject  # type: ignore[no-redef]


def test_stripe_object_exposes_to_dict_recursive():
    """StripeObject must keep _to_dict_recursive() callable on every SDK release."""
    obj = StripeObject()
    assert hasattr(obj, "_to_dict_recursive"), (
        "StripeObject._to_dict_recursive disappeared — Stripe SDK upgrade broke "
        "BillingService.handle_webhook_event payload normalisation. Pin the SDK "
        "to the previous major or refactor service.py to use a stable alternative."
    )
    assert callable(obj._to_dict_recursive)


def test_to_dict_recursive_returns_plain_dict():
    """Returned value must be a plain dict that supports .get() on nested fields."""
    nested = StripeObject()
    nested["currency"] = "usd"
    parent = StripeObject()
    parent["nested"] = nested
    parent["customer"] = "cus_123"

    result = parent._to_dict_recursive()

    assert isinstance(result, dict)
    assert result["customer"] == "cus_123"
    assert isinstance(result["nested"], dict)
    assert result["nested"].get("currency") == "usd"


def test_stripe_sdk_major_version_within_pinned_range():
    """Pyproject.toml pins billing extra to stripe>=15.0.1,<16. Detect drift early."""
    major = int(stripe.VERSION.split(".", 1)[0])
    assert major == 15, (
        f"Stripe SDK major version {major} is outside the pinned 15.x range. "
        "Verify _to_dict_recursive still exists and update pyproject.toml billing extra."
    )

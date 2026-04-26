# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Thin wrapper around the Stripe Python SDK.

``stripe`` is an optional dependency (``pip install engramia[billing]``).
All methods raise ``RuntimeError`` when the SDK is not installed or
``STRIPE_SECRET_KEY`` is not configured.
"""

import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

# Explicitly pin the Stripe API version so upgrading the stripe-python SDK
# (e.g. v15 -> v16) does not silently change request/response shapes.
# Bump this deliberately after testing webhook event compatibility.
_STRIPE_API_VERSION = "2025-04-30.basil"


class StripeClient:
    """Minimal Stripe API surface needed for Engramia billing.

    Args:
        secret_key: Stripe secret key. Defaults to ``STRIPE_SECRET_KEY`` env var.
        webhook_secret: Stripe webhook signing secret. Defaults to
            ``STRIPE_WEBHOOK_SECRET`` env var.
    """

    def __init__(
        self,
        secret_key: str | None = None,
        webhook_secret: str | None = None,
    ) -> None:
        self._secret_key = secret_key or os.environ.get("STRIPE_SECRET_KEY", "")
        self._webhook_secret = webhook_secret or os.environ.get("STRIPE_WEBHOOK_SECRET", "")
        self._stripe: Any = None

    def _sdk(self) -> Any:
        """Lazy-load the stripe SDK and configure the API key."""
        if self._stripe is not None:
            return self._stripe
        try:
            import stripe as _stripe_lib
        except ImportError as exc:
            raise RuntimeError("stripe SDK not installed. Run: pip install 'engramia[billing]'") from exc
        if not self._secret_key:
            raise RuntimeError(
                "STRIPE_SECRET_KEY is not set. Configure it via env var or StripeClient(secret_key=...)."
            )
        _stripe_lib.api_key = self._secret_key
        # Pin the Stripe API version explicitly so behaviour (request/response
        # shapes) does not shift when the stripe-python SDK default changes
        # with a future major bump.
        _stripe_lib.api_version = _STRIPE_API_VERSION
        self._stripe = _stripe_lib
        return self._stripe

    # ------------------------------------------------------------------
    # Checkout + portal
    # ------------------------------------------------------------------

    def create_checkout_session(
        self,
        customer_id: str | None,
        price_id: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str] | None = None,
        customer_email: str | None = None,
        client_reference_id: str | None = None,
    ) -> str:
        """Create a Stripe Checkout Session and return the session URL.

        ``automatic_tax`` is enabled so Stripe Tax calculates the correct VAT /
        sales tax for each jurisdiction automatically.  Requires Stripe Tax to
        be activated in the Stripe Dashboard (Settings → Tax).

        ``tax_id_collection`` lets B2B customers enter their VAT ID; Stripe
        then applies the EU reverse-charge rule and prints the ID on invoices.

        ``client_reference_id`` is what the webhook handler reads from
        ``checkout.session.completed`` to link the Stripe customer to the
        tenant — set it explicitly here when migrating away from Payment
        Links (which encoded it via URL query parameter).

        ``customer_email`` pre-fills the email field on the hosted checkout
        page when no Stripe customer exists yet.
        """
        stripe = self._sdk()
        params: dict[str, Any] = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": metadata or {},
            "automatic_tax": {"enabled": True},
            "tax_id_collection": {"enabled": True},
        }
        # Mirror the top-level metadata onto the subscription so the
        # customer.subscription.created webhook can resolve tenant_id even
        # if checkout.session.completed is delayed or replayed alone.
        if metadata:
            params["subscription_data"] = {"metadata": metadata}
        if customer_id:
            # When we already know the Stripe customer, do not also pass
            # customer_email — Stripe rejects sending both.
            params["customer"] = customer_id
        elif customer_email:
            params["customer_email"] = customer_email
        if client_reference_id:
            params["client_reference_id"] = client_reference_id
        session = stripe.checkout.Session.create(**params)
        return session.url

    def create_customer(self, tenant_id: str, email: str | None = None) -> str:
        """Create a Stripe Customer and return the customer ID.

        Called during tenant provisioning so the stripe_customer_id → tenant_id
        mapping exists in DB before the first Checkout session.
        """
        stripe = self._sdk()
        params: dict[str, Any] = {"metadata": {"tenant_id": tenant_id}}
        if email:
            params["email"] = email
        customer = stripe.Customer.create(**params)
        _log.info("Created Stripe customer %s for tenant=%s", customer.id, tenant_id)
        return customer.id

    def create_customer_portal_session(self, customer_id: str, return_url: str) -> str:
        """Create a Stripe Customer Portal session and return the URL."""
        stripe = self._sdk()
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        return session.url

    # ------------------------------------------------------------------
    # Subscription / customer retrieval
    # ------------------------------------------------------------------

    def retrieve_subscription(self, subscription_id: str) -> Any:
        """Fetch a Subscription from Stripe by ID.

        Used by the webhook handler to back-fetch subscription details when
        the checkout.session.completed event arrives before
        customer.subscription.created (Stripe does not guarantee delivery
        order). Returns the raw Stripe Subscription object — caller is
        expected to call ``_to_dict_recursive`` (or equivalent) to normalise
        nested StripeObjects into plain dicts.
        """
        stripe = self._sdk()
        return stripe.Subscription.retrieve(subscription_id)

    # ------------------------------------------------------------------
    # Webhook verification
    # ------------------------------------------------------------------

    def construct_webhook_event(self, payload: bytes, sig_header: str) -> Any:
        """Verify Stripe webhook signature and return the parsed event.

        Raises ``ValueError`` on signature mismatch (invalid or replayed).
        """
        stripe = self._sdk()
        if not self._webhook_secret:
            raise RuntimeError("STRIPE_WEBHOOK_SECRET is not set. Configure it via env var.")
        try:
            return stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=self._webhook_secret,
            )
        except stripe.error.SignatureVerificationError as exc:
            raise ValueError(f"Invalid Stripe webhook signature: {exc}") from exc

    # ------------------------------------------------------------------
    # Overage invoicing
    # ------------------------------------------------------------------

    def create_invoice_item(
        self,
        customer_id: str,
        amount_cents: int,
        description: str,
        subscription_id: str | None = None,
    ) -> None:
        """Create an invoice item (to be picked up by the next invoice)."""
        stripe = self._sdk()
        params: dict[str, Any] = {
            "customer": customer_id,
            "amount": amount_cents,
            "currency": "usd",
            "description": description,
        }
        if subscription_id:
            params["subscription"] = subscription_id
        stripe.InvoiceItem.create(**params)
        _log.info(
            "Created Stripe invoice item: customer=%s amount=$%.2f",
            customer_id,
            amount_cents / 100,
        )

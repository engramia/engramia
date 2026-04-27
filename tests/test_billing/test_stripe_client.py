# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Unit tests for StripeClient (engramia/billing/stripe_client.py).

All stripe SDK calls are mocked — no real network or Stripe account needed.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from engramia.billing.stripe_client import StripeClient

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# StripeClient._sdk() — lazy load + validation
# ---------------------------------------------------------------------------


class TestSdk:
    def test_import_error_raises_runtime_error(self):
        client = StripeClient(secret_key="sk-test", webhook_secret="whsec")

        def _block_import(name, *args, **kwargs):
            if name == "stripe":
                raise ImportError("No module named 'stripe'")
            import builtins

            return builtins.__import__(name, *args, **kwargs)

        client._stripe = None  # force re-init
        with patch("builtins.__import__", side_effect=_block_import), pytest.raises(RuntimeError, match="stripe SDK not installed"):
            client._sdk()

    def test_missing_secret_key_raises_runtime_error(self):
        client = StripeClient(secret_key="", webhook_secret="whsec")
        stripe_mock = MagicMock()
        with patch.dict("sys.modules", {"stripe": stripe_mock}), pytest.raises(RuntimeError, match="STRIPE_SECRET_KEY"):
            client._sdk()

    def test_sdk_sets_api_key(self):
        stripe_mock = MagicMock()
        client = StripeClient(secret_key="sk-test-key", webhook_secret="whsec")
        with patch.dict("sys.modules", {"stripe": stripe_mock}):
            client._stripe = None
            client._sdk()
        assert stripe_mock.api_key == "sk-test-key"

    def test_sdk_cached_after_first_call(self):
        client = StripeClient(secret_key="sk-test", webhook_secret="whsec")
        fake_stripe = MagicMock()
        client._stripe = fake_stripe
        result = client._sdk()
        assert result is fake_stripe

    def test_reads_secret_from_env(self):
        with patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk-env-key", "STRIPE_WEBHOOK_SECRET": "whsec-env"}):
            client = StripeClient()
            assert client._secret_key == "sk-env-key"
            assert client._webhook_secret == "whsec-env"


# ---------------------------------------------------------------------------
# create_checkout_session()
# ---------------------------------------------------------------------------


class TestCreateCheckoutSession:
    def _client(self):
        client = StripeClient(secret_key="sk-test", webhook_secret="whsec")
        stripe_mock = MagicMock()
        stripe_mock.checkout.Session.create.return_value.url = "https://checkout.stripe.com/pay/cs_test"
        client._stripe = stripe_mock
        return client, stripe_mock

    def test_returns_session_url(self):
        client, _ = self._client()
        url = client.create_checkout_session(
            customer_id="cus_abc",
            price_id="price_pro",
            success_url="https://ok",
            cancel_url="https://cancel",
        )
        assert url == "https://checkout.stripe.com/pay/cs_test"

    def test_passes_customer_id_when_provided(self):
        client, stripe_mock = self._client()
        client.create_checkout_session("cus_abc", "price_x", "https://ok", "https://cancel")
        params = stripe_mock.checkout.Session.create.call_args[1]
        assert params["customer"] == "cus_abc"
        # tax_id_collection on an existing customer needs explicit
        # customer_update permissions or Stripe rejects the session.
        assert params["customer_update"] == {
            "name": "auto",
            "address": "auto",
            "shipping": "auto",
        }

    def test_no_customer_id_omits_customer_param(self):
        client, stripe_mock = self._client()
        client.create_checkout_session(None, "price_x", "https://ok", "https://cancel")
        params = stripe_mock.checkout.Session.create.call_args[1]
        assert "customer" not in params
        # customer_update is only valid when customer is also set.
        assert "customer_update" not in params

    def test_metadata_passed(self):
        client, stripe_mock = self._client()
        meta = {"tenant_id": "t1"}
        client.create_checkout_session("cus_x", "price_x", "https://ok", "https://cancel", metadata=meta)
        params = stripe_mock.checkout.Session.create.call_args[1]
        assert params["metadata"] == meta

    def test_mode_is_subscription(self):
        client, stripe_mock = self._client()
        client.create_checkout_session("cus_x", "price_x", "https://ok", "https://cancel")
        params = stripe_mock.checkout.Session.create.call_args[1]
        assert params["mode"] == "subscription"

    def test_client_reference_id_forwarded(self):
        client, stripe_mock = self._client()
        client.create_checkout_session(
            None,
            "price_x",
            "https://ok",
            "https://cancel",
            client_reference_id="tenant-abc",
        )
        params = stripe_mock.checkout.Session.create.call_args[1]
        assert params["client_reference_id"] == "tenant-abc"

    def test_customer_email_forwarded_when_no_customer_id(self):
        client, stripe_mock = self._client()
        client.create_checkout_session(
            None,
            "price_x",
            "https://ok",
            "https://cancel",
            customer_email="user@example.com",
        )
        params = stripe_mock.checkout.Session.create.call_args[1]
        assert params["customer_email"] == "user@example.com"
        assert "customer" not in params

    def test_customer_email_ignored_when_customer_id_present(self):
        """Stripe rejects passing both — customer_id wins."""
        client, stripe_mock = self._client()
        client.create_checkout_session(
            "cus_abc",
            "price_x",
            "https://ok",
            "https://cancel",
            customer_email="user@example.com",
        )
        params = stripe_mock.checkout.Session.create.call_args[1]
        assert params["customer"] == "cus_abc"
        assert "customer_email" not in params

    def test_metadata_mirrored_to_subscription_data(self):
        client, stripe_mock = self._client()
        client.create_checkout_session(
            "cus_x",
            "price_x",
            "https://ok",
            "https://cancel",
            metadata={"tenant_id": "t1", "plan_tier": "pro"},
        )
        params = stripe_mock.checkout.Session.create.call_args[1]
        assert params["subscription_data"] == {
            "metadata": {"tenant_id": "t1", "plan_tier": "pro"}
        }


# ---------------------------------------------------------------------------
# create_customer_portal_session()
# ---------------------------------------------------------------------------


class TestCreateCustomerPortalSession:
    def test_returns_portal_url(self):
        client = StripeClient(secret_key="sk-test", webhook_secret="whsec")
        stripe_mock = MagicMock()
        stripe_mock.billing_portal.Session.create.return_value.url = "https://billing.stripe.com/xyz"
        client._stripe = stripe_mock

        url = client.create_customer_portal_session("cus_abc", "https://return")
        assert url == "https://billing.stripe.com/xyz"

    def test_passes_customer_id(self):
        client = StripeClient(secret_key="sk-test", webhook_secret="whsec")
        stripe_mock = MagicMock()
        stripe_mock.billing_portal.Session.create.return_value.url = "https://portal"
        client._stripe = stripe_mock

        client.create_customer_portal_session("cus_xyz", "https://return")
        call_kwargs = stripe_mock.billing_portal.Session.create.call_args[1]
        assert call_kwargs["customer"] == "cus_xyz"
        assert call_kwargs["return_url"] == "https://return"


# ---------------------------------------------------------------------------
# construct_webhook_event()
# ---------------------------------------------------------------------------


class TestConstructWebhookEvent:
    def test_no_webhook_secret_raises_runtime_error(self):
        client = StripeClient(secret_key="sk-test", webhook_secret="")
        stripe_mock = MagicMock()
        client._stripe = stripe_mock
        with pytest.raises(RuntimeError, match="STRIPE_WEBHOOK_SECRET"):
            client.construct_webhook_event(b"{}", "sig")

    def test_valid_event_returned(self):
        client = StripeClient(secret_key="sk-test", webhook_secret="whsec")
        stripe_mock = MagicMock()
        fake_event = {"type": "invoice.paid", "data": {"object": {}}}
        stripe_mock.Webhook.construct_event.return_value = fake_event
        client._stripe = stripe_mock

        result = client.construct_webhook_event(b'{"type":"invoice.paid"}', "t=1,v1=sig")
        assert result["type"] == "invoice.paid"

    def test_invalid_signature_raises_value_error(self):
        client = StripeClient(secret_key="sk-test", webhook_secret="whsec")
        stripe_mock = MagicMock()

        class FakeSignatureError(Exception):
            pass

        stripe_mock.error = MagicMock()
        stripe_mock.error.SignatureVerificationError = FakeSignatureError
        stripe_mock.Webhook.construct_event.side_effect = FakeSignatureError("bad sig")
        client._stripe = stripe_mock

        with pytest.raises(ValueError, match="Invalid Stripe webhook signature"):
            client.construct_webhook_event(b"{}", "bad-sig")

    def test_payload_and_sig_forwarded_verbatim(self):
        client = StripeClient(secret_key="sk-test", webhook_secret="whsec-123")
        stripe_mock = MagicMock()
        stripe_mock.Webhook.construct_event.return_value = {"type": "test", "data": {"object": {}}}
        client._stripe = stripe_mock

        payload = b'{"type":"test"}'
        sig = "t=999,v1=abc"
        client.construct_webhook_event(payload, sig)
        call_kwargs = stripe_mock.Webhook.construct_event.call_args[1]
        assert call_kwargs["payload"] == payload
        assert call_kwargs["sig_header"] == sig
        assert call_kwargs["secret"] == "whsec-123"


# ---------------------------------------------------------------------------
# create_invoice_item()
# ---------------------------------------------------------------------------


class TestCreateInvoiceItem:
    def test_creates_invoice_item(self):
        client = StripeClient(secret_key="sk-test", webhook_secret="whsec")
        stripe_mock = MagicMock()
        client._stripe = stripe_mock

        client.create_invoice_item(
            customer_id="cus_abc",
            amount_cents=1500,
            description="Overage: 15 runs",
        )
        stripe_mock.InvoiceItem.create.assert_called_once()
        params = stripe_mock.InvoiceItem.create.call_args[1]
        assert params["customer"] == "cus_abc"
        assert params["amount"] == 1500
        assert params["currency"] == "usd"

    def test_subscription_id_passed_when_provided(self):
        client = StripeClient(secret_key="sk-test", webhook_secret="whsec")
        stripe_mock = MagicMock()
        client._stripe = stripe_mock

        client.create_invoice_item(
            customer_id="cus_x",
            amount_cents=200,
            description="test",
            subscription_id="sub_123",
        )
        params = stripe_mock.InvoiceItem.create.call_args[1]
        assert params["subscription"] == "sub_123"

    def test_subscription_id_omitted_when_none(self):
        client = StripeClient(secret_key="sk-test", webhook_secret="whsec")
        stripe_mock = MagicMock()
        client._stripe = stripe_mock

        client.create_invoice_item(
            customer_id="cus_x",
            amount_cents=200,
            description="test",
            subscription_id=None,
        )
        params = stripe_mock.InvoiceItem.create.call_args[1]
        assert "subscription" not in params


# ---------------------------------------------------------------------------
# Network and Stripe error paths
# ---------------------------------------------------------------------------


class TestNetworkErrors:
    """Verify that network/Stripe errors propagate correctly from each client method."""

    def _client(self):
        client = StripeClient(secret_key="sk-test", webhook_secret="whsec")
        stripe_mock = MagicMock()
        client._stripe = stripe_mock
        return client, stripe_mock

    def test_connection_error_during_checkout_propagates(self):
        client, stripe_mock = self._client()
        stripe_mock.checkout.Session.create.side_effect = ConnectionError("Network unreachable")
        with pytest.raises(ConnectionError):
            client.create_checkout_session("cus_x", "price_x", "https://ok", "https://cancel")

    def test_timeout_error_during_checkout_propagates(self):
        client, stripe_mock = self._client()
        stripe_mock.checkout.Session.create.side_effect = TimeoutError("Request timed out")
        with pytest.raises(TimeoutError):
            client.create_checkout_session("cus_x", "price_x", "https://ok", "https://cancel")

    def test_connection_error_during_create_customer_propagates(self):
        client, stripe_mock = self._client()
        stripe_mock.Customer.create.side_effect = ConnectionError("Network unreachable")
        with pytest.raises(ConnectionError):
            client.create_customer(tenant_id="t1")

    def test_stripe_rate_limit_error_during_invoice_item_propagates(self):
        """429 rate-limit errors must propagate so the caller can retry."""
        client, stripe_mock = self._client()

        class FakeRateLimitError(Exception):
            http_status = 429

        stripe_mock.error = MagicMock()
        stripe_mock.error.RateLimitError = FakeRateLimitError
        stripe_mock.InvoiceItem.create.side_effect = FakeRateLimitError("Too many requests")
        with pytest.raises(FakeRateLimitError):
            client.create_invoice_item("cus_x", 500, "Overage")

    def test_card_decline_during_portal_session_propagates(self):
        """Stripe CardError must propagate so the API layer can surface it."""
        client, stripe_mock = self._client()

        class FakeCardError(Exception):
            pass

        stripe_mock.error = MagicMock()
        stripe_mock.error.CardError = FakeCardError
        stripe_mock.billing_portal.Session.create.side_effect = FakeCardError("Card declined")
        with pytest.raises(FakeCardError):
            client.create_customer_portal_session("cus_x", "https://return")

    def test_create_customer_returns_customer_id(self):
        """Happy path: create_customer returns the new customer's ID."""
        client, stripe_mock = self._client()
        fake_customer = MagicMock()
        fake_customer.id = "cus_brand_new"
        stripe_mock.Customer.create.return_value = fake_customer

        result = client.create_customer(tenant_id="tenant-new", email="new@example.com")
        assert result == "cus_brand_new"
        params = stripe_mock.Customer.create.call_args[1]
        assert params["metadata"]["tenant_id"] == "tenant-new"
        assert params["email"] == "new@example.com"

    def test_create_customer_no_email_omits_email_param(self):
        """create_customer without email must not pass email to Stripe."""
        client, stripe_mock = self._client()
        fake_customer = MagicMock()
        fake_customer.id = "cus_no_email"
        stripe_mock.Customer.create.return_value = fake_customer

        client.create_customer(tenant_id="t1", email=None)
        params = stripe_mock.Customer.create.call_args[1]
        assert "email" not in params

    def test_stripe_error_during_checkout_propagates(self):
        """Generic StripeError during checkout must not be silently swallowed."""
        client, stripe_mock = self._client()

        class FakeStripeError(Exception):
            pass

        stripe_mock.checkout.Session.create.side_effect = FakeStripeError("Stripe error")
        with pytest.raises(FakeStripeError):
            client.create_checkout_session("cus_x", "price_x", "https://ok", "https://cancel")

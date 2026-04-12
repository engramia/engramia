# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""A06 — API Integration snippets (good / medium / bad).

Domain: Third-party API integration — Stripe, Twilio, Slack — with retry, auth, webhooks.
"""

GOOD: dict = {
    "eval_score": 9.0,
    "output": "Stripe integration with idempotency, webhook signature verification, and exponential backoff retry.",
    "code": '''\
import hashlib
import hmac
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 0.5


class StripeIntegration:
    """Stripe payment processing with production-grade reliability.

    Features:
        - Idempotency keys on all mutating requests
        - Webhook signature verification (Stripe-Signature header)
        - Exponential backoff retry on transient errors (429, 5xx)
        - Structured logging for audit trail
    """

    def __init__(self, api_key: str, webhook_secret: str) -> None:
        self._api_key = api_key
        self._webhook_secret = webhook_secret
        self._client = httpx.AsyncClient(
            base_url="https://api.stripe.com/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    async def create_payment_intent(
        self,
        amount_cents: int,
        currency: str,
        customer_id: str,
        idempotency_key: str,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "amount": amount_cents,
            "currency": currency.lower(),
            "customer": customer_id,
        }
        if metadata:
            for k, v in metadata.items():
                payload[f"metadata[{k}]"] = v

        for attempt in range(1, MAX_RETRIES + 1):
            response = await self._client.post(
                "/payment_intents",
                data=payload,
                headers={"Idempotency-Key": idempotency_key},
            )
            if response.status_code in (429, 500, 502, 503):
                wait = BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "Stripe %d on attempt %d, retrying in %.1fs",
                    response.status_code, attempt, wait,
                )
                time.sleep(wait)
                continue
            response.raise_for_status()
            result = response.json()
            logger.info("PaymentIntent created: %s", result["id"])
            return result

        raise RuntimeError(f"Stripe request failed after {MAX_RETRIES} retries")

    def verify_webhook_signature(
        self, payload: bytes, signature_header: str
    ) -> bool:
        parts = dict(
            item.split("=", 1)
            for item in signature_header.split(",")
        )
        timestamp = parts.get("t", "")
        expected_sig = parts.get("v1", "")

        signed_payload = f"{timestamp}.{payload.decode()}"
        computed = hmac.new(
            self._webhook_secret.encode(),
            signed_payload.encode(),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(computed, expected_sig)
''',
}

MEDIUM: dict = {
    "eval_score": 5.8,
    "output": "Stripe charge working.",
    "code": """\
import httpx

class StripeClient:
    def __init__(self, api_key):
        self.api_key = api_key

    async def charge(self, amount, currency, customer_id):
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.stripe.com/v1/charges",
                data={"amount": amount, "currency": currency, "customer": customer_id},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            return resp.json()
""",
}

BAD: dict = {
    "eval_score": 2.5,
    "output": "stripe call",
    "code": """\
import requests

def charge_stripe(amount, token):
    r = requests.post("https://api.stripe.com/v1/charges",
                       data={"amount": amount, "source": token},
                       auth=("sk_live_xxx", ""))
    return r.json()
""",
}

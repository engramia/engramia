# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""A02 — Bug Diagnosis & Fix snippets (good / medium / bad).

Domain: Tracing request flows, identifying root causes, applying targeted fixes.
"""

GOOD: dict = {
    "eval_score": 9.0,
    "output": "Root cause: webhook payload missing 'currency' field after Stripe API v2023-12 upgrade. Fixed validation schema and added fallback.",
    "code": '''\
import logging
from typing import Any

logger = logging.getLogger(__name__)


def validate_webhook_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize incoming payment webhook payload.

    The Stripe API v2023-12 upgrade changed the payload structure:
    - 'currency' moved from top-level to 'payment_intent.currency'
    - 'amount' is now in smallest currency unit (cents)

    Args:
        payload: Raw webhook JSON body.

    Returns:
        Normalized payload dict with guaranteed 'currency' and 'amount_cents'.

    Raises:
        ValueError: If required fields are missing after normalization.
    """
    # Handle both old and new Stripe payload formats
    currency = (
        payload.get("currency")
        or payload.get("payment_intent", {}).get("currency")
    )
    if not currency:
        raise ValueError(
            f"Missing 'currency' in webhook payload. "
            f"Keys present: {sorted(payload.keys())}"
        )

    amount = payload.get("amount") or payload.get("payment_intent", {}).get("amount")
    if amount is None:
        raise ValueError("Missing 'amount' in webhook payload")

    normalized = {
        **payload,
        "currency": currency.upper(),
        "amount_cents": int(amount),
    }
    logger.debug("Webhook payload normalized: currency=%s amount=%d", currency, amount)
    return normalized


def fix_payment_webhook_handler(app):
    """Patch the /webhooks/payment endpoint to handle new Stripe format.

    Before: assumed payload.currency existed (422 on missing field).
    After:  checks both legacy and new paths, raises clear error.
    """
    original_handler = app.webhook_handlers.get("payment")

    async def patched_handler(request):
        body = await request.json()
        try:
            normalized = validate_webhook_payload(body)
        except ValueError as exc:
            logger.warning("Webhook validation failed: %s", exc)
            return {"status": "error", "detail": str(exc)}, 422
        return await original_handler(request, payload=normalized)

    app.webhook_handlers["payment"] = patched_handler
''',
}

MEDIUM: dict = {
    "eval_score": 6.0,
    "output": "Fixed the 422 by adding a check for missing currency.",
    "code": """\
def fix_webhook(payload):
    if "currency" not in payload:
        payload["currency"] = payload.get("payment_intent", {}).get("currency", "USD")
    if "amount" not in payload:
        payload["amount"] = payload.get("payment_intent", {}).get("amount", 0)
    return payload
""",
}

BAD: dict = {
    "eval_score": 2.8,
    "output": "added try except",
    "code": """\
def handle_webhook(data):
    try:
        process_payment(data["currency"], data["amount"])
    except:
        pass  # ignore errors for now
""",
}

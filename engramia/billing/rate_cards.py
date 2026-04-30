# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Static LLM pricing table for the per-role cost ceiling (Phase 6.6 #2b).

Public providers (OpenAI, Anthropic, Gemini) publish per-1M-token prices
that change ~quarterly. This module is the single source of truth for
those numbers inside Engramia. It is **deliberately static** — pulling
prices from a provider API at runtime would couple every LLM call to a
flaky external dependency, and providers do not expose stable price
endpoints anyway.

Maintenance contract: review every quarter (next: 2026-07-30) against
the provider pricing pages linked below. When a number changes, bump the
constant and add a CHANGELOG entry. Old prices stay relevant for billing
audits — past spend is computed against the rate card that was current
at the time, but Engramia does **not** retroactively re-cost; the ceiling
gate uses *current* card.

Providers without a public rate card (Ollama, openai_compat with custom
endpoints) return ``None`` from :func:`cost_for`. Cost ceilings on those
providers are **not enforced** — the gate logs a warning and lets the
call through. Tenants are responsible for their own observability when
they BYOK a non-canonical provider.

References (last reviewed 2026-04-30):
- OpenAI:    https://openai.com/api/pricing/
- Anthropic: https://www.anthropic.com/pricing#anthropic-api
- Gemini:    https://ai.google.dev/gemini-api/docs/pricing
"""

from __future__ import annotations

import logging
from typing import Final, TypedDict

_log = logging.getLogger(__name__)


class _Rate(TypedDict):
    """Per-1M-token price in cents.

    Stored as ``int`` cents (not float dollars) so cumulative spend
    counters use integer arithmetic. 100 cents = $1.
    """

    input_per_1m_cents: int
    output_per_1m_cents: int


# (provider, model) -> rate. Models are the canonical ids accepted by
# each SDK. Unknown models on a known provider return ``None`` — the
# gate then treats them as "no rate card", same as Ollama.
_RATE_CARD: Final[dict[tuple[str, str], _Rate]] = {
    # ----- OpenAI ------------------------------------------------------
    ("openai", "gpt-5"): {"input_per_1m_cents": 250, "output_per_1m_cents": 1000},
    ("openai", "gpt-4.1"): {"input_per_1m_cents": 200, "output_per_1m_cents": 800},
    ("openai", "gpt-4.1-mini"): {"input_per_1m_cents": 40, "output_per_1m_cents": 160},
    ("openai", "gpt-4o"): {"input_per_1m_cents": 250, "output_per_1m_cents": 1000},
    ("openai", "gpt-4o-mini"): {"input_per_1m_cents": 15, "output_per_1m_cents": 60},
    # Embedding rates are tracked too — used by the future embedding
    # ceiling. Cheap relative to chat models but non-zero.
    ("openai", "text-embedding-3-small"): {"input_per_1m_cents": 2, "output_per_1m_cents": 0},
    ("openai", "text-embedding-3-large"): {"input_per_1m_cents": 13, "output_per_1m_cents": 0},
    # ----- Anthropic ---------------------------------------------------
    ("anthropic", "claude-opus-4-7"): {"input_per_1m_cents": 1500, "output_per_1m_cents": 7500},
    ("anthropic", "claude-sonnet-4-6"): {"input_per_1m_cents": 300, "output_per_1m_cents": 1500},
    ("anthropic", "claude-haiku-4-5"): {"input_per_1m_cents": 80, "output_per_1m_cents": 400},
    # ----- Gemini ------------------------------------------------------
    ("gemini", "gemini-2.5-pro"): {"input_per_1m_cents": 125, "output_per_1m_cents": 1000},
    ("gemini", "gemini-2.5-flash"): {"input_per_1m_cents": 30, "output_per_1m_cents": 250},
    ("gemini", "gemini-embedding-001"): {"input_per_1m_cents": 2, "output_per_1m_cents": 0},
}

# Last manual review date — surfaced in /v1/version so an operator can
# see at a glance how stale the card is. Update on every PR that touches
# pricing.
RATE_CARD_REVIEWED: Final[str] = "2026-04-30"


def cost_for(
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
) -> int | None:
    """Compute the cost in cents for a completed LLM call.

    Args:
        provider: Provider id matching ``ProviderType`` (``openai`` etc.).
        model: Model identifier as resolved by ``model_for_role``.
        tokens_in: Prompt tokens reported by the SDK ``usage`` field.
        tokens_out: Completion tokens reported by the SDK.

    Returns:
        Integer cents. ``None`` when no rate card entry exists for the
        ``(provider, model)`` pair (Ollama, openai_compat, unknown
        canonical model). Callers must handle the None branch — the
        ceiling gate logs a warning and skips enforcement.
    """
    rate = _RATE_CARD.get((provider, model))
    if rate is None:
        return None
    # Integer arithmetic — token counts are integers, prices are
    # cents-per-million, so the division by 1_000_000 is exact at the
    # cent level only when token volume is large enough. For small calls
    # we accept rounding loss (under-report by < 1 cent / call), which is
    # immaterial against the cents-level monthly limits the ceiling
    # operates on.
    cost_in = (rate["input_per_1m_cents"] * tokens_in) // 1_000_000
    cost_out = (rate["output_per_1m_cents"] * tokens_out) // 1_000_000
    return cost_in + cost_out


def has_rate_card(provider: str, model: str) -> bool:
    """True when an entry exists. Cheap probe used by the gate to decide
    whether to log a "skipping ceiling" warning."""
    return (provider, model) in _RATE_CARD


def known_models_for_provider(provider: str) -> list[str]:
    """Return the list of canonical model ids on the rate card.

    Used by the dashboard to populate the cost-card autocomplete and by
    the docs generator. Order is alphabetical for stable output.
    """
    return sorted(model for (p, model) in _RATE_CARD if p == provider)

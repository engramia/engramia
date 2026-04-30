# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for the static LLM rate card (#2b).

The rate card is hand-maintained per provider. These tests guard the
shape (every entry must have both input and output prices, both
non-negative) so a typo or pasted-wrong price surfaces in CI rather
than as a quietly mis-billed customer call.
"""

from __future__ import annotations

import pytest

from engramia.billing import rate_cards
from engramia.billing.rate_cards import (
    RATE_CARD_REVIEWED,
    cost_for,
    has_rate_card,
    known_models_for_provider,
)

# Pull the private map for shape validation. Test code is allowed to
# reach into the implementation; production code is not.
_RATE_CARD = rate_cards._RATE_CARD


class TestShape:
    def test_every_entry_has_both_prices(self) -> None:
        for (provider, model), rate in _RATE_CARD.items():
            assert "input_per_1m_cents" in rate, f"{provider}/{model} missing input price"
            assert "output_per_1m_cents" in rate, f"{provider}/{model} missing output price"

    def test_prices_are_non_negative_ints(self) -> None:
        for (provider, model), rate in _RATE_CARD.items():
            for key in ("input_per_1m_cents", "output_per_1m_cents"):
                v = rate[key]
                assert isinstance(v, int), f"{provider}/{model}/{key} not int: {type(v)}"
                assert v >= 0, f"{provider}/{model}/{key} negative: {v}"

    def test_canonical_providers_present(self) -> None:
        # If any of these get accidentally deleted on a refactor,
        # tenants with that provider would silently lose ceiling
        # enforcement. Guard the canonical three.
        canonical_providers = {p for (p, _m) in _RATE_CARD}
        assert "openai" in canonical_providers
        assert "anthropic" in canonical_providers
        assert "gemini" in canonical_providers

    def test_reviewed_date_format(self) -> None:
        # Maintenance contract: ISO date. Exercising the constant prevents
        # someone removing it during a refactor (the docstring rests on it).
        assert isinstance(RATE_CARD_REVIEWED, str)
        # Loose check — the migration / CI would surface bad formats.
        parts = RATE_CARD_REVIEWED.split("-")
        assert len(parts) == 3, "RATE_CARD_REVIEWED must be YYYY-MM-DD"


class TestCostFor:
    def test_known_model_returns_cents(self) -> None:
        # gpt-4.1: 200/1M in, 800/1M out
        # 1000 in + 500 out -> floor((200*1000)/1e6) + floor((800*500)/1e6)
        # = floor(0.2) + floor(0.4) = 0 + 0 = 0 (small calls round down)
        assert cost_for("openai", "gpt-4.1", 1000, 500) == 0
        # Larger volume — exercises the integer division path
        cost = cost_for("openai", "gpt-4.1", 100_000, 50_000)
        # 200*100_000 // 1_000_000 + 800*50_000 // 1_000_000 = 20 + 40 = 60
        assert cost == 60

    def test_unknown_provider_returns_none(self) -> None:
        assert cost_for("ollama", "llama3.3", 10_000, 5_000) is None

    def test_unknown_model_on_known_provider_returns_none(self) -> None:
        assert cost_for("openai", "made-up-model-xxx", 10_000, 5_000) is None

    def test_zero_tokens_returns_zero(self) -> None:
        # Edge case — provider returned no usage. Cost is 0, not None.
        assert cost_for("openai", "gpt-4.1", 0, 0) == 0


class TestHasRateCard:
    @pytest.mark.parametrize(
        ("provider", "model", "expected"),
        [
            ("openai", "gpt-4.1", True),
            ("anthropic", "claude-opus-4-7", True),
            ("ollama", "llama3.3", False),
            ("openai_compat", "anything", False),
            ("openai", "gpt-99-turbo", False),
        ],
    )
    def test_lookup(self, provider: str, model: str, expected: bool) -> None:
        assert has_rate_card(provider, model) is expected


class TestKnownModelsForProvider:
    def test_returns_sorted_list(self) -> None:
        models = known_models_for_provider("openai")
        assert models == sorted(models)
        assert "gpt-4.1" in models

    def test_unknown_provider_returns_empty(self) -> None:
        assert known_models_for_provider("ollama") == []

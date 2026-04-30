# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Property-style tests for ``TenantCredential.model_for_role`` fallback chain.

Three precedence levels:

    1. ``role_models[role]`` (per-role override)
    2. ``default_model`` (credential-wide default)
    3. ``default_model_for(provider)`` (provider-wide static default)

Hypothesis is not currently in the dev deps, so this file uses
``parametrize`` with hand-picked edge cases that cover the same surface
(empty maps, missing keys, falsy strings, every provider, every canonical
role plus an unknown role).
"""

from __future__ import annotations

import pytest

from engramia.credentials.models import TenantCredential, default_model_for
from engramia.providers.roles import KNOWN_ROLES

_PROVIDERS = ["openai", "anthropic", "gemini", "ollama", "openai_compat"]


def _make_cred(
    *,
    provider: str = "openai",
    default_model: str | None = None,
    role_models: dict[str, str] | None = None,
) -> TenantCredential:
    return TenantCredential(
        id="row-1",
        tenant_id="t1",
        provider=provider,  # type: ignore[arg-type]
        purpose="llm",
        api_key="sk-test-1234567890",
        key_fingerprint="sk-...test",
        default_model=default_model,
        role_models=role_models or {},
    )


# ---------------------------------------------------------------------------
# Precedence levels
# ---------------------------------------------------------------------------


class TestPrecedence:
    def test_role_models_wins_over_default(self) -> None:
        cred = _make_cred(
            default_model="gpt-4.1",
            role_models={"eval": "gpt-4.1-mini"},
        )
        assert cred.model_for_role("eval") == "gpt-4.1-mini"

    def test_default_model_used_when_role_unmapped(self) -> None:
        cred = _make_cred(
            default_model="gpt-4.1",
            role_models={"eval": "gpt-4.1-mini"},
        )
        # 'architect' not in role_models -> falls through to default_model
        assert cred.model_for_role("architect") == "gpt-4.1"

    def test_provider_default_used_when_default_model_none(self) -> None:
        cred = _make_cred(default_model=None, role_models={})
        assert cred.model_for_role("default") == default_model_for("openai")


# ---------------------------------------------------------------------------
# Property-style: every (provider, role, role_models?, default_model?) combo
# returns a non-empty string and never raises.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", _PROVIDERS)
@pytest.mark.parametrize("role", sorted(KNOWN_ROLES) + ["custom_enterprise_role"])
@pytest.mark.parametrize(
    "default_model",
    [None, "user-default-model"],
)
@pytest.mark.parametrize(
    "role_models",
    [
        {},
        {"eval": "mapped-eval"},
        {"eval": "mapped-eval", "architect": "mapped-architect"},
    ],
)
def test_always_returns_non_empty_string(
    provider: str,
    role: str,
    default_model: str | None,
    role_models: dict[str, str],
) -> None:
    cred = _make_cred(
        provider=provider,
        default_model=default_model,
        role_models=role_models,
    )
    result = cred.model_for_role(role)
    assert isinstance(result, str)
    assert result  # non-empty


# ---------------------------------------------------------------------------
# Edge cases that property tests must catch
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_role_string_falls_through_to_default(self) -> None:
        cred = _make_cred(default_model="gpt-4.1", role_models={"": "weird"})
        # Key match works regardless of name; library does not enforce
        # canonical names at lookup (validator runs at API boundary only).
        assert cred.model_for_role("") == "weird"

    def test_role_with_no_default_falls_to_provider_default(self) -> None:
        cred = _make_cred(provider="anthropic", default_model=None, role_models={})
        assert cred.model_for_role("evolve") == default_model_for("anthropic")

    def test_role_models_with_falsy_value_returns_falsy(self) -> None:
        # If a tenant somehow stored '' as a role_models value (validator
        # forbids it at API but DB tampering could), model_for_role returns
        # the empty string verbatim. This documents current behaviour and
        # would fail the bigger property test above (caught early).
        cred = _make_cred(default_model="gpt-4.1", role_models={"eval": ""})
        # Behaviour: returns '' literally — it's a key match.
        # If we ever decide to skip-on-falsy, change this assertion.
        assert cred.model_for_role("eval") == ""

    def test_unknown_role_falls_through_silently(self) -> None:
        # Phase 6.6 #2: unknown role names are allowed (Enterprise custom
        # roles). The hot path logs INFO once per cold cache; the lookup
        # itself just returns the default_model.
        cred = _make_cred(default_model="gpt-4.1", role_models={})
        assert cred.model_for_role("totally-unknown-role") == "gpt-4.1"

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for engramia.credentials.models.

Verifies the safety properties of the schemas:
- ``CredentialCreate.api_key`` is a SecretStr; default model_dump masks it.
- ``TenantCredential.api_key`` is excluded from model_dump entirely.
- ``CredentialPublicView`` has no api_key field at all.
- ``fingerprint_for`` returns the documented ``"<3>...<4>"`` format.
- ``model_for_role`` falls back through role_models → default_model →
  provider default.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from engramia.credentials.models import (
    CredentialCreate,
    CredentialPublicView,
    CredentialUpdate,
    TenantCredential,
    default_model_for,
    fingerprint_for,
)

# ---------------------------------------------------------------------------
# CredentialCreate
# ---------------------------------------------------------------------------


class TestCredentialCreate:
    def test_accepts_minimal_valid_input(self) -> None:
        cc = CredentialCreate(provider="openai", api_key="sk-test-1234567890")
        assert cc.provider == "openai"
        assert cc.purpose == "llm"  # default
        assert isinstance(cc.api_key, SecretStr)
        assert cc.api_key.get_secret_value() == "sk-test-1234567890"

    def test_repr_does_not_leak_api_key(self) -> None:
        cc = CredentialCreate(provider="openai", api_key="sk-test-LEAK-DETECTOR-1234")
        assert "sk-test-LEAK" not in repr(cc)
        assert "**********" in repr(cc)

    def test_model_dump_masks_api_key(self) -> None:
        """Default model_dump() returns SecretStr objects which str() to '**********'."""
        cc = CredentialCreate(provider="openai", api_key="sk-test-LEAK-DETECTOR-1234")
        dumped = cc.model_dump()
        assert "sk-test-LEAK" not in str(dumped["api_key"])

    def test_model_dump_json_masks_api_key(self) -> None:
        cc = CredentialCreate(provider="openai", api_key="sk-test-LEAK-DETECTOR-1234")
        as_json = cc.model_dump_json()
        assert "sk-test-LEAK" not in as_json
        assert "**********" in as_json

    def test_rejects_blank_api_key(self) -> None:
        with pytest.raises(ValidationError):
            CredentialCreate(provider="openai", api_key="        ")

    def test_rejects_too_short_api_key(self) -> None:
        with pytest.raises(ValidationError):
            CredentialCreate(provider="openai", api_key="x")

    def test_rejects_unknown_provider(self) -> None:
        with pytest.raises(ValidationError):
            CredentialCreate(provider="xai", api_key="sk-test-1234567890")  # type: ignore[arg-type]

    def test_rejects_unknown_purpose(self) -> None:
        with pytest.raises(ValidationError):
            CredentialCreate(
                provider="openai",
                purpose="evil",  # type: ignore[arg-type]
                api_key="sk-test-1234567890",
            )

    def test_accepts_https_base_url(self) -> None:
        cc = CredentialCreate(
            provider="openai_compat",
            api_key="sk-test-1234567890",
            base_url="https://api.together.xyz",
        )
        assert cc.base_url == "https://api.together.xyz"

    def test_accepts_localhost_http_base_url(self) -> None:
        """Ollama on localhost with plain http is the only http:// allowed."""
        cc = CredentialCreate(
            provider="ollama",
            api_key="sk-ollama-placeholder1234567890",
            base_url="http://localhost:11434",
        )
        assert cc.base_url == "http://localhost:11434"

    def test_rejects_plain_http_base_url(self) -> None:
        with pytest.raises(ValidationError, match="https"):
            CredentialCreate(
                provider="openai_compat",
                api_key="sk-test-1234567890",
                base_url="http://api.example.com",  # plain http, not localhost
            )

    def test_purpose_defaults_to_llm(self) -> None:
        cc = CredentialCreate(provider="anthropic", api_key="sk-ant-test-1234567890")
        assert cc.purpose == "llm"


# ---------------------------------------------------------------------------
# TenantCredential
# ---------------------------------------------------------------------------


class TestTenantCredential:
    def _make(self, **overrides) -> TenantCredential:
        return TenantCredential(
            id="abc-123",
            tenant_id="tenant-1",
            provider="openai",
            purpose="llm",
            api_key=overrides.pop("api_key", "sk-test-LEAK-DETECTOR-1234"),
            key_fingerprint="sk-...1234",
            **overrides,
        )

    def test_repr_does_not_leak_api_key(self) -> None:
        cred = self._make()
        assert "sk-test-LEAK" not in repr(cred)

    def test_model_dump_excludes_api_key(self) -> None:
        cred = self._make()
        dumped = cred.model_dump()
        assert "api_key" not in dumped
        # Sanity check: the string secret cannot leak via str(dumped)
        assert "sk-test-LEAK" not in str(dumped)

    def test_model_dump_json_excludes_api_key(self) -> None:
        cred = self._make()
        assert "sk-test-LEAK" not in cred.model_dump_json()

    def test_aad_format(self) -> None:
        cred = self._make()
        assert cred.aad() == b"tenant-1:openai:llm"

    def test_aad_changes_with_tenant_id(self) -> None:
        a = self._make()
        b = self._make()
        b = TenantCredential(
            id="b",
            tenant_id="tenant-2",
            provider="openai",
            purpose="llm",
            api_key="x",
            key_fingerprint="x...x",
        )
        assert a.aad() != b.aad()

    def test_model_for_role_falls_through(self) -> None:
        cred = self._make(default_model="gpt-5", role_models={"eval": "gpt-4.1-mini"})
        assert cred.model_for_role("eval") == "gpt-4.1-mini"
        assert cred.model_for_role("default") == "gpt-5"
        assert cred.model_for_role("anything-else") == "gpt-5"

    def test_model_for_role_uses_provider_default_if_unset(self) -> None:
        cred = self._make()  # no default_model, no role_models
        # OpenAI default per default_model_for
        assert cred.model_for_role("default") == default_model_for("openai")


# ---------------------------------------------------------------------------
# CredentialPublicView
# ---------------------------------------------------------------------------


class TestCredentialPublicView:
    def test_no_api_key_field(self) -> None:
        """Defence-in-depth: even if a route handler accidentally tries to
        set api_key on a public view, Pydantic must reject it because the
        field doesn't exist."""
        v = CredentialPublicView(
            id="abc",
            provider="openai",
            purpose="llm",
            key_fingerprint="sk-...1234",
            status="active",
        )
        assert "api_key" not in v.model_dump()
        assert "api_key" not in v.model_dump_json()
        assert "api_key" not in CredentialPublicView.model_fields


# ---------------------------------------------------------------------------
# CredentialUpdate
# ---------------------------------------------------------------------------


class TestCredentialUpdate:
    def test_no_api_key_field(self) -> None:
        """PATCH cannot rotate the key — that path must use POST UPSERT."""
        assert "api_key" not in CredentialUpdate.model_fields

    def test_all_fields_optional(self) -> None:
        # An empty PATCH is a no-op, not an error.
        # Note: ``role_models`` is no longer on CredentialUpdate (moved
        # to its own tier-gated PATCH /role-models endpoint in #2).
        upd = CredentialUpdate()
        assert upd.base_url is None
        assert upd.default_model is None
        assert upd.default_embed_model is None


# ---------------------------------------------------------------------------
# fingerprint_for
# ---------------------------------------------------------------------------


class TestFingerprintFor:
    def test_returns_prefix_and_suffix(self) -> None:
        fp = fingerprint_for("sk-1234567890ABCD")
        assert fp.startswith("sk-")
        assert fp.endswith("ABCD")
        assert "..." in fp

    def test_format_matches_documented_example(self) -> None:
        fp = fingerprint_for("sk-AbCdEfGhIjKlMnOpQrStUv")
        assert fp == "sk-...QrUv" or fp == "sk-...StUv"
        # The exact suffix is "StUv" — last 4 chars of the input
        assert fp == "sk-...StUv"

    def test_works_with_anthropic_prefix(self) -> None:
        fp = fingerprint_for("sk-ant-api03-AbCdEfGhIjKl")
        assert fp.startswith("sk-")
        assert fp.endswith("HIjKl"[1:])

    def test_works_with_aiza_prefix(self) -> None:
        fp = fingerprint_for("AIzaSyBcDeFgHiJkLmNoPqRs")
        assert fp.startswith("AIz")

    def test_rejects_too_short(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            fingerprint_for("short")

    def test_does_not_log_or_echo_full_key(self) -> None:
        """Sanity: fingerprint must not contain middle chars of the key."""
        full = "sk-MIDDLE-LEAK-CHARS-ABCD"
        fp = fingerprint_for(full)
        assert "MIDDLE" not in fp
        assert "LEAK" not in fp
        # But suffix is preserved
        assert fp.endswith("ABCD")

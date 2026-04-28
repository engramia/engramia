# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for engramia.providers.tenant_scoped wrappers (BYOK Phase 6.6)."""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pytest

from engramia._context import reset_scope, set_scope
from engramia.credentials import (
    AESGCMCipher,
    CredentialResolver,
    CredentialStore,
    StoredCredential,
)
from engramia.providers.demo import DemoProvider
from engramia.providers.tenant_scoped import (
    TenantScopedEmbeddingProvider,
    TenantScopedLLMProvider,
)
from engramia.types import Scope

_TEST_KEY = bytes(range(32))


# ---------------------------------------------------------------------------
# Fakes — tiny ad-hoc CredentialStore so the resolver doesn't need a DB
# ---------------------------------------------------------------------------


class _FakeStore(CredentialStore):
    def __init__(self) -> None:  # type: ignore[override]
        self._rows: dict[tuple[str, str], StoredCredential] = {}

    def upsert_row(self, row: StoredCredential) -> None:
        self._rows[(row.tenant_id, row.purpose)] = row

    def get_active_for_purpose(self, tenant_id, purpose):  # type: ignore[override]
        return self._rows.get((tenant_id, purpose))

    def touch_last_used(self, credential_id: str) -> None:  # type: ignore[override]
        pass

    def mark_invalid(self, credential_id: str, error: str) -> None:  # type: ignore[override]
        pass


def _make_row(
    *,
    tenant_id: str,
    provider: str = "openai",
    purpose: str = "llm",
    plaintext: str = "sk-test-1234567890",
    cipher: AESGCMCipher | None = None,
    default_model: str | None = None,
) -> StoredCredential:
    cipher = cipher or AESGCMCipher(_TEST_KEY)
    aad = f"{tenant_id}:{provider}:{purpose}".encode()
    ct, nonce, tag = cipher.encrypt(plaintext, aad)
    return StoredCredential(
        id=f"row-{tenant_id}-{provider}",
        tenant_id=tenant_id,
        provider=provider,  # type: ignore[arg-type]
        purpose=purpose,  # type: ignore[arg-type]
        encrypted_key=ct,
        nonce=nonce,
        auth_tag=tag,
        key_version=1,
        key_fingerprint="sk-...test",
        base_url=None,
        default_model=default_model,
        default_embed_model=None,
        role_models={},
        status="active",
        last_used_at=None,
        last_validated_at=None,
        last_validation_error=None,
        created_at=datetime.datetime.now(datetime.UTC),
        created_by="test",
    )


@pytest.fixture
def cipher() -> AESGCMCipher:
    return AESGCMCipher(_TEST_KEY)


@pytest.fixture
def store() -> _FakeStore:
    return _FakeStore()


@pytest.fixture
def resolver(store: _FakeStore, cipher: AESGCMCipher) -> CredentialResolver:
    return CredentialResolver(store=store, cipher=cipher)  # type: ignore[arg-type]


@pytest.fixture
def with_tenant_scope():
    def _scope(tenant_id: str) -> None:
        token = set_scope(Scope(tenant_id=tenant_id, project_id="default"))
        return token

    yield _scope


# ---------------------------------------------------------------------------
# TenantScopedLLMProvider
# ---------------------------------------------------------------------------


class TestTenantScopedLLM:
    def test_falls_back_to_demo_when_no_credential(self, resolver) -> None:
        provider = TenantScopedLLMProvider(resolver=resolver)
        token = set_scope(Scope(tenant_id="tenant-no-key", project_id="p"))
        try:
            result = provider.call("hi", role="default")
        finally:
            reset_scope(token)
        # DemoProvider returns the demo string for default role
        assert "DEMO" in result

    def test_dispatches_to_concrete_provider(self, store, resolver, cipher) -> None:
        # Register a credential for tenant-A
        store.upsert_row(_make_row(tenant_id="tenant-A", plaintext="sk-real-key", cipher=cipher))

        # Patch _build_llm so we don't construct a real OpenAI client
        mock_llm = MagicMock()
        mock_llm.call.return_value = "real response"

        with patch("engramia.providers.tenant_scoped._build_llm", return_value=mock_llm) as mock_build:
            provider = TenantScopedLLMProvider(resolver=resolver)
            token = set_scope(Scope(tenant_id="tenant-A", project_id="p"))
            try:
                result = provider.call("prompt", role="default")
            finally:
                reset_scope(token)

        assert result == "real response"
        # _build_llm called with the resolved credential
        cred_arg = mock_build.call_args.args[0]
        assert cred_arg.api_key == "sk-real-key"

    def test_provider_cache_reuses_instance(self, store, resolver, cipher) -> None:
        """Second call to the same (tenant, provider, role) must reuse the
        constructed concrete provider — not rebuild the SDK client."""
        store.upsert_row(_make_row(tenant_id="tenant-A", cipher=cipher))

        with patch("engramia.providers.tenant_scoped._build_llm", return_value=MagicMock()) as mock_build:
            provider = TenantScopedLLMProvider(resolver=resolver)
            token = set_scope(Scope(tenant_id="tenant-A", project_id="p"))
            try:
                provider.call("prompt 1")
                provider.call("prompt 2")
            finally:
                reset_scope(token)

        # _build_llm called only once across the two calls
        assert mock_build.call_count == 1

    def test_invalidate_clears_tenant_cache(self, store, resolver, cipher) -> None:
        store.upsert_row(_make_row(tenant_id="tenant-A", cipher=cipher))

        with patch("engramia.providers.tenant_scoped._build_llm", return_value=MagicMock()) as mock_build:
            provider = TenantScopedLLMProvider(resolver=resolver)
            token = set_scope(Scope(tenant_id="tenant-A", project_id="p"))
            try:
                provider.call("first")
                provider.invalidate("tenant-A")
                # Resolver also caches — clear that too
                resolver.invalidate("tenant-A")
                provider.call("second")
            finally:
                reset_scope(token)

        assert mock_build.call_count == 2

    def test_different_tenants_get_separate_providers(self, store, resolver, cipher) -> None:
        store.upsert_row(_make_row(tenant_id="tenant-A", plaintext="sk-A", cipher=cipher))
        store.upsert_row(_make_row(tenant_id="tenant-B", plaintext="sk-B", cipher=cipher))

        seen_keys: list[str] = []

        def _capture(cred, role):
            seen_keys.append(cred.api_key)
            return MagicMock()

        with patch("engramia.providers.tenant_scoped._build_llm", side_effect=_capture):
            provider = TenantScopedLLMProvider(resolver=resolver)
            token_a = set_scope(Scope(tenant_id="tenant-A", project_id="p"))
            try:
                provider.call("x")
            finally:
                reset_scope(token_a)
            token_b = set_scope(Scope(tenant_id="tenant-B", project_id="p"))
            try:
                provider.call("y")
            finally:
                reset_scope(token_b)

        # Each tenant got its own credential's key
        assert "sk-A" in seen_keys
        assert "sk-B" in seen_keys


# ---------------------------------------------------------------------------
# TenantScopedEmbeddingProvider
# ---------------------------------------------------------------------------


class TestTenantScopedEmbeddings:
    def test_uses_explicit_fallback_when_no_credential(self, resolver) -> None:
        fallback = MagicMock()
        fallback.embed.return_value = [0.5] * 384
        provider = TenantScopedEmbeddingProvider(resolver=resolver, fallback=fallback)
        token = set_scope(Scope(tenant_id="tenant-none", project_id="p"))
        try:
            result = provider.embed("hello")
        finally:
            reset_scope(token)
        assert result == [0.5] * 384
        fallback.embed.assert_called_once_with("hello")

    def test_anthropic_credential_falls_back_to_fallback(self, store, resolver, cipher) -> None:
        """Anthropic doesn't offer embeddings — the resolver may return an
        Anthropic LLM credential, but we MUST NOT try to call embed on it."""
        store.upsert_row(
            _make_row(
                tenant_id="tenant-A",
                provider="anthropic",
                purpose="llm",
                cipher=cipher,
            )
        )

        fallback = MagicMock()
        fallback.embed.return_value = [0.1] * 384
        provider = TenantScopedEmbeddingProvider(resolver=resolver, fallback=fallback)
        token = set_scope(Scope(tenant_id="tenant-A", project_id="p"))
        try:
            result = provider.embed("hi")
        finally:
            reset_scope(token)
        assert result == [0.1] * 384

    def test_uses_concrete_provider_for_openai(self, store, resolver, cipher) -> None:
        store.upsert_row(_make_row(tenant_id="tenant-A", provider="openai", cipher=cipher))

        mock_emb = MagicMock()
        mock_emb.embed.return_value = [0.9] * 1536

        with patch(
            "engramia.providers.tenant_scoped._build_embeddings",
            return_value=mock_emb,
        ):
            provider = TenantScopedEmbeddingProvider(resolver=resolver)
            token = set_scope(Scope(tenant_id="tenant-A", project_id="p"))
            try:
                result = provider.embed("hi")
            finally:
                reset_scope(token)
        assert result == [0.9] * 1536

    def test_embed_batch_dispatches_to_provider(self, store, resolver, cipher) -> None:
        store.upsert_row(_make_row(tenant_id="tenant-A", provider="openai", cipher=cipher))

        mock_emb = MagicMock()
        mock_emb.embed_batch.return_value = [[0.1], [0.2]]

        with patch(
            "engramia.providers.tenant_scoped._build_embeddings",
            return_value=mock_emb,
        ):
            provider = TenantScopedEmbeddingProvider(resolver=resolver)
            token = set_scope(Scope(tenant_id="tenant-A", project_id="p"))
            try:
                result = provider.embed_batch(["a", "b"])
            finally:
                reset_scope(token)
        assert result == [[0.1], [0.2]]


# ---------------------------------------------------------------------------
# DemoProvider integration smoke test
# ---------------------------------------------------------------------------


class TestDemoFallbackIntegration:
    def test_demo_response_is_eval_parseable(self, resolver) -> None:
        """When no credential exists and role='eval', the demo provider
        must return JSON that MultiEvaluator can parse — otherwise the
        evaluate endpoint would fail on demo-mode tenants."""
        provider = TenantScopedLLMProvider(resolver=resolver, fallback=DemoProvider())
        token = set_scope(Scope(tenant_id="tenant-demo", project_id="p"))
        try:
            result = provider.call("evaluate me", role="eval")
        finally:
            reset_scope(token)

        import json

        parsed = json.loads(result)
        assert "overall" in parsed
        assert "feedback" in parsed

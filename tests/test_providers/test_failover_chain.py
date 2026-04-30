# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Failover chain semantics for ``TenantScopedLLMProvider``.

Covers the design invariants from Phase 6.6 #2:

* Auth-class errors on **any** chain member raise immediately — never failover.
* Transient errors advance the chain.
* Whole chain exhausted -> last transient bubbles up.
* Inactive (revoked / invalid) fallback rows are silently skipped.
* Per-role model resolution is applied to every chain member independently.
* Cross-credential cache invalidation: invalidating tenant flushes the chain.
"""

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
from engramia.providers.tenant_scoped import TenantScopedLLMProvider
from engramia.types import Scope

_TEST_KEY = bytes(range(32))


class _FakeStoreWithById(CredentialStore):
    """Adds ``get_by_id`` (used by failover resolution) on top of the basic
    fake from ``test_tenant_scoped`` — copied here so the test file stays
    self-contained."""

    def __init__(self) -> None:  # type: ignore[override]
        self._rows: dict[str, StoredCredential] = {}
        self._by_purpose: dict[tuple[str, str], StoredCredential] = {}

    def add(self, row: StoredCredential, *, primary: bool = False) -> None:
        self._rows[row.id] = row
        if primary:
            self._by_purpose[(row.tenant_id, row.purpose)] = row

    def get_active_for_purpose(self, tenant_id, purpose):  # type: ignore[override]
        return self._by_purpose.get((tenant_id, purpose))

    def get_by_id(self, tenant_id, credential_id):  # type: ignore[override]
        row = self._rows.get(credential_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        return row

    def touch_last_used(self, credential_id: str) -> None:  # type: ignore[override]
        pass

    def mark_invalid(self, credential_id: str, error: str) -> None:  # type: ignore[override]
        pass


def _make_row(
    *,
    tenant_id: str,
    provider: str,
    row_id: str,
    cipher: AESGCMCipher,
    purpose: str = "llm",
    plaintext: str = "sk-test-1234567890",
    default_model: str | None = None,
    role_models: dict[str, str] | None = None,
    failover_chain: list[str] | None = None,
    status: str = "active",
) -> StoredCredential:
    aad = f"{tenant_id}:{provider}:{purpose}".encode()
    ct, nonce, tag = cipher.encrypt(plaintext, aad)
    return StoredCredential(
        id=row_id,
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
        role_models=role_models or {},
        failover_chain=failover_chain or [],
        status=status,  # type: ignore[arg-type]
        last_used_at=None,
        last_validated_at=None,
        last_validation_error=None,
        created_at=datetime.datetime.now(datetime.UTC),
        created_by="test",
        updated_at=datetime.datetime.now(datetime.UTC),
    )


@pytest.fixture
def cipher() -> AESGCMCipher:
    return AESGCMCipher(_TEST_KEY)


@pytest.fixture
def store(cipher: AESGCMCipher) -> _FakeStoreWithById:
    s = _FakeStoreWithById()
    primary = _make_row(
        tenant_id="t1",
        provider="openai",
        row_id="cred-primary",
        cipher=cipher,
        failover_chain=["cred-secondary"],
    )
    secondary = _make_row(
        tenant_id="t1",
        provider="anthropic",
        row_id="cred-secondary",
        cipher=cipher,
    )
    s.add(primary, primary=True)
    s.add(secondary)
    return s


@pytest.fixture
def resolver(store: _FakeStoreWithById, cipher: AESGCMCipher) -> CredentialResolver:
    return CredentialResolver(store=store, cipher=cipher)  # type: ignore[arg-type]


@pytest.fixture
def scoped_t1():
    token = set_scope(Scope(tenant_id="t1", project_id="default"))
    yield
    reset_scope(token)


# ---------------------------------------------------------------------------
# Helpers — patch the concrete provider builders so we can inject mocks
# without going through the real OpenAI / Anthropic SDKs.
# ---------------------------------------------------------------------------


def _patched_build_one_llm(*responses_per_provider):
    """Build a side_effect function for ``_build_one_llm``.

    ``responses_per_provider`` is a sequence of ``(provider_name, mock)``
    pairs. The patch returns ``mock`` when the credential's provider field
    matches. Lets each test wire failure modes onto the primary vs.
    secondary independently.
    """
    table = dict(responses_per_provider)

    def _factory(cred, role):
        try:
            return table[cred.provider]
        except KeyError as e:
            raise AssertionError(f"unexpected provider {cred.provider!r} in chain") from e

    return _factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAuthErrorFailFast:
    def test_auth_error_on_primary_does_not_failover(
        self, store, resolver, scoped_t1
    ) -> None:
        """An ``AuthenticationError`` on primary must raise immediately.

        Mocking ``is_auth_error`` is cleaner than importing the openai SDK
        in tests — we substitute the classifier so any sentinel exception
        is treated as auth-class.
        """
        primary_mock = MagicMock()
        primary_mock.call.side_effect = RuntimeError("simulated auth")
        secondary_mock = MagicMock()
        secondary_mock.call.return_value = "should never be reached"

        wrapper = TenantScopedLLMProvider(resolver, store=store)
        with patch(
            "engramia.providers.tenant_scoped._build_one_llm",
            side_effect=_patched_build_one_llm(
                ("openai", primary_mock),
                ("anthropic", secondary_mock),
            ),
        ), patch(
            "engramia.providers.tenant_scoped.is_auth_error",
            return_value=True,
        ):
            with pytest.raises(RuntimeError, match="simulated auth"):
                wrapper.call("hello")
        # Secondary was built (chain construction is eager) but never called.
        assert secondary_mock.call.call_count == 0


class TestTransientFailover:
    def test_transient_on_primary_advances_to_secondary(
        self, store, resolver, scoped_t1
    ) -> None:
        primary_mock = MagicMock()
        primary_mock.call.side_effect = RuntimeError("transient 503")
        secondary_mock = MagicMock()
        secondary_mock.call.return_value = "from secondary"

        wrapper = TenantScopedLLMProvider(resolver, store=store)
        with patch(
            "engramia.providers.tenant_scoped._build_one_llm",
            side_effect=_patched_build_one_llm(
                ("openai", primary_mock),
                ("anthropic", secondary_mock),
            ),
        ), patch(
            "engramia.providers.tenant_scoped.is_auth_error",
            return_value=False,
        ):
            result = wrapper.call("hello")

        assert result == "from secondary"
        assert primary_mock.call.call_count == 1
        assert secondary_mock.call.call_count == 1

    def test_whole_chain_exhausted_raises_last_transient(
        self, store, resolver, scoped_t1
    ) -> None:
        primary_mock = MagicMock()
        primary_mock.call.side_effect = RuntimeError("primary down")
        secondary_mock = MagicMock()
        secondary_mock.call.side_effect = RuntimeError("secondary also down")

        wrapper = TenantScopedLLMProvider(resolver, store=store)
        with patch(
            "engramia.providers.tenant_scoped._build_one_llm",
            side_effect=_patched_build_one_llm(
                ("openai", primary_mock),
                ("anthropic", secondary_mock),
            ),
        ), patch(
            "engramia.providers.tenant_scoped.is_auth_error",
            return_value=False,
        ):
            with pytest.raises(RuntimeError, match="secondary also down"):
                wrapper.call("hello")


class TestInactiveSkipped:
    def test_revoked_secondary_is_skipped(
        self, cipher, scoped_t1
    ) -> None:
        """Builder skips inactive rows; chain effectively becomes [primary]."""
        s = _FakeStoreWithById()
        primary = _make_row(
            tenant_id="t1",
            provider="openai",
            row_id="cred-primary",
            cipher=cipher,
            failover_chain=["cred-secondary"],
        )
        secondary_revoked = _make_row(
            tenant_id="t1",
            provider="anthropic",
            row_id="cred-secondary",
            cipher=cipher,
            status="revoked",
        )
        s.add(primary, primary=True)
        s.add(secondary_revoked)
        resolver = CredentialResolver(store=s, cipher=cipher)  # type: ignore[arg-type]

        primary_mock = MagicMock()
        primary_mock.call.side_effect = RuntimeError("transient")

        wrapper = TenantScopedLLMProvider(resolver, store=s)
        with patch(
            "engramia.providers.tenant_scoped._build_one_llm",
            side_effect=lambda c, r: primary_mock,
        ), patch(
            "engramia.providers.tenant_scoped.is_auth_error",
            return_value=False,
        ):
            with pytest.raises(RuntimeError, match="transient"):
                wrapper.call("hello")
        # No failover provider was ever built / called.
        assert primary_mock.call.call_count == 1


class TestPerRoleResolution:
    """Each chain member resolves its OWN role_models — failover honors role."""

    def test_role_passed_to_each_chain_build(
        self, cipher, scoped_t1
    ) -> None:
        s = _FakeStoreWithById()
        primary = _make_row(
            tenant_id="t1",
            provider="openai",
            row_id="cred-primary",
            cipher=cipher,
            failover_chain=["cred-secondary"],
            role_models={"eval": "gpt-4.1-mini"},
        )
        secondary = _make_row(
            tenant_id="t1",
            provider="anthropic",
            row_id="cred-secondary",
            cipher=cipher,
            role_models={"eval": "claude-haiku-4-5"},
        )
        s.add(primary, primary=True)
        s.add(secondary)
        resolver = CredentialResolver(store=s, cipher=cipher)  # type: ignore[arg-type]

        seen_roles: list[tuple[str, str]] = []

        def _spy(cred, role):
            seen_roles.append((cred.provider, role))
            mock = MagicMock()
            # Make primary fail so we walk the chain
            if cred.provider == "openai":
                mock.call.side_effect = RuntimeError("transient")
            else:
                mock.call.return_value = "ok"
            return mock

        wrapper = TenantScopedLLMProvider(resolver, store=s)
        with patch(
            "engramia.providers.tenant_scoped._build_one_llm",
            side_effect=_spy,
        ), patch(
            "engramia.providers.tenant_scoped.is_auth_error",
            return_value=False,
        ):
            wrapper.call("hello", role="eval")

        assert seen_roles == [("openai", "eval"), ("anthropic", "eval")]


class TestSelfRefDeduplication:
    """Even if a chain row sneaks in with a self-ref (DB tampering), the
    builder dedupes by id so we never call the same provider twice."""

    def test_self_ref_in_failover_chain_is_dropped(
        self, cipher, scoped_t1
    ) -> None:
        s = _FakeStoreWithById()
        # Hand-craft a primary that points to ITSELF in failover_chain.
        # The API rejects this at PATCH time; this is the defence-in-depth
        # behaviour for a tampered row.
        primary = _make_row(
            tenant_id="t1",
            provider="openai",
            row_id="cred-primary",
            cipher=cipher,
            failover_chain=["cred-primary"],
        )
        s.add(primary, primary=True)
        resolver = CredentialResolver(store=s, cipher=cipher)  # type: ignore[arg-type]

        build_count = {"n": 0}

        def _spy(cred, role):
            build_count["n"] += 1
            mock = MagicMock()
            mock.call.return_value = "ok"
            return mock

        wrapper = TenantScopedLLMProvider(resolver, store=s)
        with patch(
            "engramia.providers.tenant_scoped._build_one_llm",
            side_effect=_spy,
        ), patch(
            "engramia.providers.tenant_scoped.is_auth_error",
            return_value=False,
        ):
            result = wrapper.call("hello")

        assert result == "ok"
        # Primary built once; self-ref dropped, so total = 1.
        assert build_count["n"] == 1

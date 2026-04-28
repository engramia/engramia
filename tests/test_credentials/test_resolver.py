# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for engramia.credentials.resolver.CredentialResolver.

Uses the real :class:`AESGCMCipher` (cheap, in-memory) but a fake
:class:`CredentialStore` so tests don't require Postgres. The fake store
simulates the public method surface and tracks calls so assertions can
verify decryption AAD, cache invalidation, and last-used touch behaviour.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from engramia.credentials.crypto import AESGCMCipher
from engramia.credentials.resolver import CredentialResolver
from engramia.credentials.store import StoredCredential

if TYPE_CHECKING:
    from engramia.credentials.models import ProviderType, PurposeType

# ---------------------------------------------------------------------------
# Test fixtures + fakes
# ---------------------------------------------------------------------------

_TEST_KEY = bytes(range(32))


def _stored(
    *,
    plaintext: str,
    cipher: AESGCMCipher,
    tenant_id: str = "tenant-1",
    provider: ProviderType = "openai",
    purpose: PurposeType = "llm",
    row_id: str = "row-1",
    role_models: dict[str, str] | None = None,
) -> StoredCredential:
    """Encrypt ``plaintext`` and assemble a StoredCredential row."""
    aad = f"{tenant_id}:{provider}:{purpose}".encode()
    ct, nonce, tag = cipher.encrypt(plaintext, aad)
    return StoredCredential(
        id=row_id,
        tenant_id=tenant_id,
        provider=provider,
        purpose=purpose,
        encrypted_key=ct,
        nonce=nonce,
        auth_tag=tag,
        key_version=1,
        key_fingerprint="sk-...abcd",
        base_url=None,
        default_model=None,
        default_embed_model=None,
        role_models=role_models or {},
        status="active",
        last_used_at=None,
        last_validated_at=None,
        last_validation_error=None,
        created_at=datetime.datetime.now(datetime.UTC),
        created_by="test",
    )


@dataclass
class FakeStore:
    """Minimal CredentialStore stand-in, no DB engine required.

    Maps ``(tenant_id, purpose)`` to a single :class:`StoredCredential`.
    Captures method-call history so tests can assert side effects.
    """

    rows: dict[tuple[str, str], StoredCredential] = field(default_factory=dict)
    touched_ids: list[str] = field(default_factory=list)
    invalid_marks: list[tuple[str, str]] = field(default_factory=list)

    def get_active_for_purpose(self, tenant_id: str, purpose: PurposeType) -> StoredCredential | None:
        return self.rows.get((tenant_id, purpose))

    def get(self, *args: Any, **kwargs: Any) -> StoredCredential | None:
        return None  # not used by resolver after the refactor

    def touch_last_used(self, credential_id: str) -> None:
        self.touched_ids.append(credential_id)

    def mark_invalid(self, credential_id: str, error: str) -> None:
        self.invalid_marks.append((credential_id, error))


@pytest.fixture
def cipher() -> AESGCMCipher:
    return AESGCMCipher(_TEST_KEY)


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def resolver(store: FakeStore, cipher: AESGCMCipher) -> CredentialResolver:
    return CredentialResolver(store=store, cipher=cipher)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Resolution happy path
# ---------------------------------------------------------------------------


class TestResolveHappy:
    def test_returns_decrypted_credential(
        self,
        resolver: CredentialResolver,
        store: FakeStore,
        cipher: AESGCMCipher,
    ) -> None:
        store.rows[("tenant-1", "llm")] = _stored(
            plaintext="sk-real-key-1234",
            cipher=cipher,
        )
        result = resolver.resolve("tenant-1", "llm")
        assert result is not None
        assert result.api_key == "sk-real-key-1234"
        assert result.tenant_id == "tenant-1"
        assert result.provider == "openai"

    def test_returns_none_when_no_row(self, resolver: CredentialResolver) -> None:
        assert resolver.resolve("tenant-nonexistent", "llm") is None

    def test_touches_last_used_on_resolve(
        self,
        resolver: CredentialResolver,
        store: FakeStore,
        cipher: AESGCMCipher,
    ) -> None:
        store.rows[("tenant-1", "llm")] = _stored(plaintext="sk-key", cipher=cipher, row_id="row-42")
        resolver.resolve("tenant-1", "llm")
        assert "row-42" in store.touched_ids

    def test_no_cipher_returns_none(self, store: FakeStore) -> None:
        """When BYOK is disabled (``cipher=None``), every resolution returns
        None so callers fall back to demo mode."""
        resolver = CredentialResolver(store=store, cipher=None)  # type: ignore[arg-type]
        store.rows[("tenant-1", "llm")] = _stored(plaintext="sk", cipher=AESGCMCipher(_TEST_KEY))
        assert resolver.resolve("tenant-1", "llm") is None


# ---------------------------------------------------------------------------
# Tampering / decryption-error path
# ---------------------------------------------------------------------------


class TestDecryptionFailure:
    def test_aad_mismatch_returns_none_and_marks_invalid(
        self,
        resolver: CredentialResolver,
        store: FakeStore,
        cipher: AESGCMCipher,
    ) -> None:
        """Simulate an attacker swapping a row to a different tenant_id —
        the AAD computed at decrypt time differs from the AAD used at
        encrypt time, so the cipher rejects."""
        # Encrypt with tenant-1 AAD
        original = _stored(plaintext="sk-key", cipher=cipher, tenant_id="tenant-1")
        # Re-tag the row as tenant-2 — same ciphertext, swapped tenant
        tampered = StoredCredential(
            id=original.id,
            tenant_id="tenant-2",  # SWAPPED
            provider=original.provider,
            purpose=original.purpose,
            encrypted_key=original.encrypted_key,
            nonce=original.nonce,
            auth_tag=original.auth_tag,
            key_version=original.key_version,
            key_fingerprint=original.key_fingerprint,
            base_url=None,
            default_model=None,
            default_embed_model=None,
            role_models={},
            status="active",
            last_used_at=None,
            last_validated_at=None,
            last_validation_error=None,
            created_at=original.created_at,
            created_by="test",
        )
        store.rows[("tenant-2", "llm")] = tampered
        result = resolver.resolve("tenant-2", "llm")
        assert result is None
        assert len(store.invalid_marks) == 1
        assert store.invalid_marks[0][0] == original.id


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------


class TestCache:
    def test_second_resolve_hits_cache(
        self,
        resolver: CredentialResolver,
        store: FakeStore,
        cipher: AESGCMCipher,
    ) -> None:
        store.rows[("tenant-1", "llm")] = _stored(plaintext="sk-key", cipher=cipher, row_id="row-1")
        resolver.resolve("tenant-1", "llm")
        # Second call: store should not be consulted again
        store.rows.pop(("tenant-1", "llm"))  # remove from store
        result = resolver.resolve("tenant-1", "llm")
        assert result is not None  # served from cache

    def test_cache_size_increments_on_miss(
        self,
        resolver: CredentialResolver,
        store: FakeStore,
        cipher: AESGCMCipher,
    ) -> None:
        assert resolver.cache_size == 0
        store.rows[("tenant-1", "llm")] = _stored(plaintext="x", cipher=cipher)
        resolver.resolve("tenant-1", "llm")
        assert resolver.cache_size == 1

    def test_invalidate_drops_tenant_entries(
        self,
        resolver: CredentialResolver,
        store: FakeStore,
        cipher: AESGCMCipher,
    ) -> None:
        store.rows[("tenant-1", "llm")] = _stored(plaintext="sk", cipher=cipher, tenant_id="tenant-1")
        store.rows[("tenant-2", "llm")] = _stored(plaintext="sk", cipher=cipher, tenant_id="tenant-2")
        resolver.resolve("tenant-1", "llm")
        resolver.resolve("tenant-2", "llm")
        assert resolver.cache_size == 2
        resolver.invalidate("tenant-1")
        assert resolver.cache_size == 1
        # tenant-2 still cached
        store.rows.pop(("tenant-2", "llm"))
        assert resolver.resolve("tenant-2", "llm") is not None  # cache hit

    def test_invalidate_all_clears_cache(
        self,
        resolver: CredentialResolver,
        store: FakeStore,
        cipher: AESGCMCipher,
    ) -> None:
        store.rows[("tenant-1", "llm")] = _stored(plaintext="sk", cipher=cipher)
        resolver.resolve("tenant-1", "llm")
        assert resolver.cache_size == 1
        resolver.invalidate_all()
        assert resolver.cache_size == 0

    def test_ttl_expiry_forces_re_decrypt(
        self,
        resolver: CredentialResolver,
        store: FakeStore,
        cipher: AESGCMCipher,
    ) -> None:
        """Decision A2 — 1-hour hard TTL. After expiry, the cache entry
        is dropped and a fresh DB lookup happens."""
        store.rows[("tenant-1", "llm")] = _stored(plaintext="sk-key", cipher=cipher)
        with patch("engramia.credentials.resolver.time.time", return_value=1000.0):
            resolver.resolve("tenant-1", "llm")
            assert resolver.cache_size == 1
        # 2 hours later
        with patch("engramia.credentials.resolver.time.time", return_value=1000.0 + 7200):
            store.rows.pop(("tenant-1", "llm"))
            result = resolver.resolve("tenant-1", "llm")
            assert result is None  # store empty after expiry
            assert resolver.cache_size == 0


# ---------------------------------------------------------------------------
# Capacity / LRU eviction
# ---------------------------------------------------------------------------


class TestCapacityLRU:
    def test_lru_eviction_when_full(
        self,
        store: FakeStore,
        cipher: AESGCMCipher,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When more than _CACHE_MAX_ENTRIES entries are inserted, the
        oldest is evicted. Uses a small max via monkeypatch to keep the
        test fast."""
        from engramia.credentials import resolver as resolver_module

        monkeypatch.setattr(resolver_module, "_CACHE_MAX_ENTRIES", 2)
        r = CredentialResolver(store=store, cipher=cipher)  # type: ignore[arg-type]

        for i in range(3):
            tid = f"tenant-{i}"
            store.rows[(tid, "llm")] = _stored(plaintext=f"sk-{i}", cipher=cipher, tenant_id=tid)
            r.resolve(tid, "llm")

        assert r.cache_size == 2
        # tenant-0 should be evicted (oldest)
        store.rows.pop(("tenant-0", "llm"))
        assert r.resolve("tenant-0", "llm") is None

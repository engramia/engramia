# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Per-tenant credential resolver with bounded TTL cache.

The resolver is the single decryption point for the BYOK subsystem. It sits
between :class:`engramia.credentials.store.CredentialStore` (raw rows) and
:class:`engramia._factory.make_llm` (provider instances). The lifecycle is:

1. ``make_llm()`` reads the active tenant from ``_context.get_scope()``.
2. ``CredentialResolver.resolve(tenant_id, "llm")`` returns a
   :class:`engramia.credentials.models.TenantCredential` with the plaintext
   key, or ``None`` if no row exists.
3. The factory either constructs the provider with the plaintext key or
   falls back to :class:`DemoProvider` (added in PR5).

Caching policy (decision A2): hybrid event-driven invalidation + 1-hour
hard TTL. The TTL bounds the time plaintext keys live in process memory
even when the tenant is constantly active; the event-driven invalidation
makes credential rotation reflect immediately. Capacity 512 entries —
roughly 100 active tenants x 5 roles, well within process RSS budget.

Thread-safety: the cache uses an :class:`OrderedDict` plus a
:class:`threading.Lock`, mirroring the auth-key cache pattern in
``engramia/api/auth.py``. No async — credentials resolution must work in
the sync route handler thread pool.
"""

from __future__ import annotations

import collections
import logging
import threading
import time
from typing import TYPE_CHECKING, Final

from engramia.credentials.backend import EncryptedBlob
from engramia.credentials.models import TenantCredential
from engramia.exceptions import DecryptionError, VaultBackendError

if TYPE_CHECKING:
    from engramia.credentials.backend import CredentialBackend
    from engramia.credentials.store import CredentialStore, StoredCredential

_log = logging.getLogger(__name__)

_CACHE_TTL_SECONDS: Final[float] = 3600.0  # decision A2: 1-hour hard TTL
_CACHE_MAX_ENTRIES: Final[int] = 512


class CredentialResolver:
    """Resolve tenant credentials from the store, decrypting on the way.

    Backend dispatch is per-row: every :class:`StoredCredential` carries
    a ``backend`` marker (``"local"`` or ``"vault"``), and the resolver
    looks up the matching :class:`CredentialBackend` in its
    :attr:`_backends` map. This keeps a hybrid mid-migration deployment
    correct while the bulk migration script flips rows from local to
    vault.

    Args:
        store: :class:`CredentialStore` for DB lookups.
        backends: Mapping of ``backend_id`` → backend instance. Pass an
            empty dict (or ``None``) to disable resolution entirely —
            used in dev / ``ENGRAMIA_BYOK_ENABLED=false`` mode where the
            caller wants every ``resolve()`` to return ``None``. The
            production wiring in :func:`engramia.api.app._setup_byok`
            puts the configured backend (one or the other) in here under
            its own ``backend_id`` key; the bulk migration script
            registers both at once.

    Thread-safety: all public methods are thread-safe. The cache lock is
    held only across the dict mutation, not across the DB call or the
    decryption — those are pure functions of their inputs and contention
    on the lock is negligible.
    """

    def __init__(
        self,
        store: CredentialStore,
        backends: dict[str, CredentialBackend] | None = None,
        # Back-compat: some tests still pass cipher= positionally / as kwarg.
        # Wrap it into a {local: LocalAESGCMBackend} dict on the fly.
        cipher: object | None = None,
    ) -> None:
        self._store = store
        if backends is None:
            backends = {}
            if cipher is not None:
                # Lazy import to avoid the cipher → backend → resolver
                # import cycle at module load time.
                from engramia.credentials.backends.local import LocalAESGCMBackend

                # Treat cipher as either an AESGCMCipher (old API) or
                # an already-built LocalAESGCMBackend (new code paths
                # where someone passes a backend explicitly).
                if hasattr(cipher, "backend_id"):
                    backends[cipher.backend_id] = cipher  # type: ignore[index,assignment]
                else:
                    backends["local"] = LocalAESGCMBackend(cipher)  # type: ignore[arg-type]
        self._backends: dict[str, CredentialBackend] = backends
        self._cache: collections.OrderedDict[tuple[str, str], tuple[float, TenantCredential]] = (
            collections.OrderedDict()
        )
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        tenant_id: str,
        purpose: str = "llm",
    ) -> TenantCredential | None:
        """Return the active credential for ``(tenant_id, purpose)`` or None.

        Resolution order:
          1. Check in-memory cache. Hit → return the cached
             :class:`TenantCredential` if not expired (within TTL).
          2. Cache miss / expired → query the store via
             :meth:`CredentialStore.get_active_for_purpose`. The store
             resolves a single row across all providers for the requested
             purpose, falling back to ``purpose='both'`` automatically.
          3. Decrypt using AAD bound to the row's stored
             ``(tenant_id, provider, purpose)`` — NOT the queried purpose.
             Stale AAD = tampering; cipher raises :class:`DecryptionError`,
             we mark the row invalid and return None.
          4. Insert into cache, evicting the oldest if the LRU is full.

        Args:
            tenant_id: The active tenant from
                :py:func:`engramia._context.get_scope`.
            purpose: ``"llm"`` (default) or ``"embedding"``.

        Returns:
            :class:`TenantCredential` with plaintext ``api_key``, or
            ``None`` if no usable credential exists.
        """
        if not self._backends:
            return None

        cached = self._cache_get(tenant_id, purpose)
        if cached is not None:
            return cached

        row = self._store.get_active_for_purpose(tenant_id, purpose)  # type: ignore[arg-type]
        if row is None:
            return None

        try:
            plaintext = self._decrypt(row)
        except DecryptionError:
            _log.warning(
                "CREDENTIAL_DECRYPT_FAILURE row_id=%s tenant=%s provider=%s backend=%s — marking invalid",
                row.id,
                tenant_id,
                row.provider,
                row.backend,
            )
            self._store.mark_invalid(row.id, "Decryption failed")
            return None
        except VaultBackendError as exc:
            # Vault unreachable / auth failed: do NOT mark the row invalid
            # (the credential is fine, the infrastructure isn't). Return
            # None so the caller maps to 503; cache stays untouched so a
            # subsequent request after Vault recovers immediately succeeds.
            _log.warning(
                "VAULT_UNREACHABLE row_id=%s tenant=%s — fail-closed: %s",
                row.id,
                tenant_id,
                exc,
            )
            return None

        cred = self._row_to_tenant_credential(row, plaintext)
        self._cache_put(tenant_id, purpose, cred)
        # Best-effort touch — non-blocking failure path.
        self._store.touch_last_used(cred.id)
        return cred

    def resolve_by_id(self, tenant_id: str, credential_id: str) -> TenantCredential | None:
        """Resolve a specific credential by id (used for failover chain build).

        Unlike :meth:`resolve` (which queries by purpose and caches by
        ``(tenant_id, purpose)``), this method targets one row directly. Used
        by :func:`engramia.providers.tenant_scoped._build_llm_chain` to
        materialise each fallback credential listed in
        ``primary.failover_chain``.

        No caching at this layer — the chain itself is cached one level up
        in :class:`TenantScopedLLMProvider`, and adding another cache here
        would just duplicate eviction logic. Decryption is per-call, but
        the chain cache means it only happens on cold start / invalidation.
        """
        if not self._backends:
            return None
        row = self._store.get_by_id(tenant_id, credential_id)
        if row is None:
            return None
        if row.status != "active":
            return None
        try:
            plaintext = self._decrypt(row)
        except DecryptionError:
            _log.warning(
                "CREDENTIAL_DECRYPT_FAILURE row_id=%s tenant=%s backend=%s — failover skip",
                row.id,
                tenant_id,
                row.backend,
            )
            self._store.mark_invalid(row.id, "Decryption failed")
            return None
        except VaultBackendError as exc:
            _log.warning(
                "VAULT_UNREACHABLE row_id=%s tenant=%s — failover skip: %s",
                row.id,
                tenant_id,
                exc,
            )
            return None
        return self._row_to_tenant_credential(row, plaintext)

    @staticmethod
    def _row_to_tenant_credential(row: StoredCredential, plaintext: str) -> TenantCredential:
        """Construct a :class:`TenantCredential` from a decrypted row.

        Centralised here so :meth:`resolve` and :meth:`resolve_by_id`
        cannot drift on field mappings.
        """
        return TenantCredential(
            id=row.id,
            tenant_id=row.tenant_id,
            provider=row.provider,
            purpose=row.purpose,
            api_key=plaintext,
            key_fingerprint=row.key_fingerprint,
            base_url=row.base_url,
            default_model=row.default_model,
            default_embed_model=row.default_embed_model,
            role_models=row.role_models or {},
            failover_chain=row.failover_chain or [],
            role_cost_limits=row.role_cost_limits or {},
            status=row.status,
            last_used_at=row.last_used_at,
            last_validated_at=row.last_validated_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def invalidate(self, tenant_id: str) -> None:
        """Drop all cached credentials for one tenant.

        Called from :class:`engramia.credentials.store.CredentialStore` on
        upsert / patch / revoke so that the next request re-resolves from
        the DB and observes the change immediately.
        """
        with self._lock:
            keys_to_drop = [k for k in self._cache if k[0] == tenant_id]
            for k in keys_to_drop:
                del self._cache[k]

    def invalidate_all(self) -> None:
        """Drop the entire cache. Intended for tests and the master-key
        rotation migration."""
        with self._lock:
            self._cache.clear()

    @property
    def cache_size(self) -> int:
        """Number of entries currently in the cache. Exposed for the
        ``engramia_credential_cache_size`` Prometheus gauge."""
        with self._lock:
            return len(self._cache)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _decrypt(self, row: StoredCredential) -> str:
        """Dispatch decryption to the row's configured backend.

        The backend is resolved by the ``backend`` marker on the row
        (set by migration 028 with default ``'local'``; flipped to
        ``'vault'`` by the bulk migration script). Both backends bind
        the ciphertext to the ``(tenant_id, provider, purpose)`` triple,
        either via AES-GCM AAD (local) or Vault Transit ``context``
        (vault), so a row swap inside the DB is detected at decrypt.
        """
        backend = self._backends.get(row.backend)
        if backend is None:
            # Unknown backend marker — defensive log + treat as decrypt
            # failure so the row is skipped rather than crashing the
            # request. Indicates a misconfigured deployment (e.g. vault
            # row but engramia[vault] extra not installed).
            _log.error(
                "UNKNOWN_BACKEND row_id=%s tenant=%s backend=%r — marking invalid (configured backends: %s)",
                row.id,
                row.tenant_id,
                row.backend,
                list(self._backends.keys()),
            )
            raise DecryptionError(f"No backend registered for {row.backend!r}")
        blob = EncryptedBlob(
            ciphertext=row.ciphertext_blob,
            nonce=row.nonce,
            auth_tag=row.auth_tag,
            key_version=row.key_version,
        )
        return backend.decrypt(
            tenant_id=row.tenant_id,
            provider=row.provider,
            purpose=row.purpose,
            blob=blob,
        )

    # ------------------------------------------------------------------
    # Cache primitives
    # ------------------------------------------------------------------

    def _cache_get(self, tenant_id: str, purpose: str) -> TenantCredential | None:
        now = time.time()
        with self._lock:
            entry = self._cache.get((tenant_id, purpose))
            if entry is None:
                return None
            expires_at, cred = entry
            if now >= expires_at:
                del self._cache[(tenant_id, purpose)]
                return None
            # LRU touch — move to end on hit
            self._cache.move_to_end((tenant_id, purpose))
            return cred

    def _cache_put(self, tenant_id: str, purpose: str, cred: TenantCredential) -> None:
        expires_at = time.time() + _CACHE_TTL_SECONDS
        with self._lock:
            self._cache[(tenant_id, purpose)] = (expires_at, cred)
            self._cache.move_to_end((tenant_id, purpose))
            while len(self._cache) > _CACHE_MAX_ENTRIES:
                self._cache.popitem(last=False)

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tenant-scoped LLM and embedding provider wrappers for BYOK.

These wrappers are the bridge between the existing single-instance
Memory facade and the per-tenant credential resolution introduced in
Phase 6.6. The Memory factory builds **one** wrapper at startup; on
every call, the wrapper:

1. Reads the active tenant from :func:`engramia._context.get_scope`.
2. Asks :class:`engramia.credentials.resolver.CredentialResolver` for
   that tenant's credential (LRU+TTL cached internally).
3. Builds the **failover chain** for that credential — primary plus the
   credentials referenced in ``failover_chain`` (if any). The chain is
   cached as a unit keyed by ``(tenant_id, primary_provider, role)``.
4. Iterates the chain on call: returns on first success, falls over on
   transient errors (5xx/timeout/network), fails fast on auth-class
   errors (see :mod:`engramia.providers._errors`).
5. Falls back to :class:`engramia.providers.demo.DemoProvider` when no
   credential exists, so a tenant who skipped onboarding still gets a
   functional (if synthetic) response.

Per-role routing (Phase 6.6 #2): the cache key includes ``role`` because
``cred.model_for_role(role)`` is resolved at chain build time — different
roles produce different concrete provider instances with different model
ids. ``role_models`` is honored on every credential in the chain
independently, so failover from openai (eval=gpt-4.1-mini) to anthropic
(eval=claude-haiku) preserves the tenant's intent.

Per-role routing applies to LLM calls only. Embedding model selection
is per-credential via ``default_embed_model`` — there is no per-role
embedding routing because embeddings have no eval/coder/architect
distinction.

Cache invalidation is delegated to the resolver — when the resolver
invalidates a tenant on credential change, the next call rebuilds the
chain with the rotated key. The ``_PROVIDER_CACHE_MAX`` size accounts
for ``tenants × providers × roles`` cardinality (post-#2 expansion);
512 was sufficient pre-routing but now LRU-thrashes at scale.
"""

from __future__ import annotations

import collections
import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from engramia._context import get_scope
from engramia.providers._errors import is_auth_error
from engramia.providers.base import EmbeddingProvider, LLMProvider
from engramia.providers.demo import DemoProvider
from engramia.providers.roles import KNOWN_ROLES

if TYPE_CHECKING:
    from engramia.billing.role_metering import RoleMeter
    from engramia.credentials.models import TenantCredential
    from engramia.credentials.resolver import CredentialResolver
    from engramia.credentials.store import CredentialStore

_log = logging.getLogger(__name__)

# Bumped from 512 in #2: per-role expansion multiplies cache cardinality
# (tenants × providers × roles). 4096 entries × ~250 B/entry ≈ 1 MB —
# acceptable, prevents LRU thrash for active tenants. Adjust if Prometheus
# ``engramia_provider_cache_eviction_total`` shows sustained churn.
_PROVIDER_CACHE_MAX: Final[int] = 4096

# Failover safety cap — primary + at most 2 fallback credentials. The API
# layer enforces this at PATCH time; this constant is the read-side guard
# against a hand-edited DB row exceeding it.
_FAILOVER_CHAIN_MAX_LEN: Final[int] = 3


@dataclass
class _ChainEntry:
    """One node in a failover chain — provider plus the metadata the
    cost-ceiling meter needs after a successful call.

    Keeping ``credential_id`` / ``provider_type`` / ``model`` alongside
    the provider instance avoids re-resolving them from the resolver
    cache after every call.
    """

    provider: LLMProvider
    credential_id: str
    provider_type: str
    model: str


def _build_one_llm(cred: TenantCredential, role: str) -> LLMProvider:
    """Construct one concrete LLM provider for a single credential.

    Resolves the model via ``cred.model_for_role(role)`` so per-role
    routing (Phase 6.6 #2) is applied uniformly. Used both for the
    primary credential and for each fallback in the failover chain.

    Lazy imports keep the optional SDK extras optional. When a tenant
    has Anthropic configured but the cloud only has the openai extra
    installed, the route handler raises a clear ImportError instead of
    silently degrading.
    """
    model = cred.model_for_role(role)
    if cred.provider == "openai":
        from engramia.providers.openai import OpenAIProvider

        return OpenAIProvider(api_key=cred.api_key, model=model, base_url=cred.base_url)
    if cred.provider == "anthropic":
        from engramia.providers.anthropic import AnthropicProvider

        return AnthropicProvider(api_key=cred.api_key, model=model)
    if cred.provider == "gemini":
        from engramia.providers.gemini import GeminiProvider

        return GeminiProvider(api_key=cred.api_key, model=model)
    if cred.provider == "ollama":
        from engramia.providers.ollama import OllamaProvider

        return OllamaProvider(
            api_key=cred.api_key,
            model=model,
            base_url=cred.base_url or "http://localhost:11434/v1",
        )
    if cred.provider == "openai_compat":
        # OpenAICompat reuses OpenAIProvider with explicit base_url
        from engramia.providers.openai import OpenAIProvider

        return OpenAIProvider(api_key=cred.api_key, model=model, base_url=cred.base_url)
    raise ValueError(f"Unknown provider for tenant credential: {cred.provider!r}")


def _build_llm_chain(
    cred: TenantCredential,
    role: str,
    store: CredentialStore | None,
    resolver: CredentialResolver,
) -> list[_ChainEntry]:
    """Build the ordered failover chain for a primary credential.

    Each entry carries the provider instance plus the metadata the
    cost-ceiling meter needs (credential_id, provider_type, resolved
    model) so the caller does not have to re-resolve them after a
    successful call.

    The chain is ``[primary]`` plus one entry per active credential
    referenced in ``cred.failover_chain``. Inactive (revoked/invalid),
    cross-tenant, or unresolvable references are silently skipped — the
    chain is best-effort, not strictly enforced. A primary that can't
    even be built (e.g. unknown provider after a downgrade) raises;
    the call would have failed regardless.
    """
    chain: list[_ChainEntry] = [
        _ChainEntry(
            provider=_build_one_llm(cred, role),
            credential_id=cred.id,
            provider_type=cred.provider,
            model=cred.model_for_role(role),
        )
    ]
    if not cred.failover_chain or store is None:
        return chain
    seen: set[str] = {cred.id}
    for fallback_id in cred.failover_chain[: _FAILOVER_CHAIN_MAX_LEN - 1]:
        if fallback_id in seen:
            continue  # silently skip self-ref or duplicate (defence in depth)
        seen.add(fallback_id)
        try:
            fallback = resolver.resolve_by_id(cred.tenant_id, fallback_id)
        except Exception as exc:  # broad: store unavailable, decrypt fail, etc.
            _log.warning(
                "failover.resolve_skipped tenant=%s fallback_id=%s reason=%s",
                cred.tenant_id,
                fallback_id,
                exc,
            )
            continue
        if fallback is None or fallback.status != "active":
            continue
        try:
            chain.append(
                _ChainEntry(
                    provider=_build_one_llm(fallback, role),
                    credential_id=fallback.id,
                    provider_type=fallback.provider,
                    model=fallback.model_for_role(role),
                )
            )
        except (ValueError, ImportError) as exc:
            _log.warning(
                "failover.build_skipped tenant=%s fallback_id=%s provider=%s reason=%s",
                cred.tenant_id,
                fallback_id,
                fallback.provider,
                exc,
            )
            continue
    return chain


def _build_embeddings(cred: TenantCredential) -> EmbeddingProvider:
    """Construct the concrete embedding provider for a credential."""
    model = cred.default_embed_model or "text-embedding-3-small"
    if cred.provider in ("openai", "openai_compat"):
        from engramia.providers.openai import OpenAIEmbeddings

        return OpenAIEmbeddings(api_key=cred.api_key, model=model, base_url=cred.base_url)
    if cred.provider == "gemini":
        from engramia.providers.gemini import GeminiEmbeddings

        return GeminiEmbeddings(api_key=cred.api_key, model=cred.default_embed_model or "gemini-embedding-001")
    if cred.provider == "ollama":
        from engramia.providers.ollama import OllamaEmbeddings

        return OllamaEmbeddings(
            api_key=cred.api_key,
            model=cred.default_embed_model or "nomic-embed-text",
            base_url=cred.base_url or "http://localhost:11434/v1",
        )
    raise ValueError(
        f"Provider {cred.provider!r} does not offer embeddings — "
        "configure a separate (provider, purpose='embedding') credential."
    )


class TenantScopedLLMProvider(LLMProvider):
    """LLM provider that resolves the failover chain per request.

    Reads the active tenant from the scope contextvar set by
    ``require_auth`` (or by tests via ``set_scope``). Falls back to a
    shared :class:`DemoProvider` when no credential is configured.

    Failover semantics (Phase 6.6 #2):

    * Chain = ``[primary, *failover_chain]`` (max 3 entries, inactive
      members skipped).
    * On call, iterate the chain. First success returns immediately.
    * **Auth-class** errors (auth/perm/bad-request) on **any** chain
      member raise immediately — never failover. This protects against
      masking rotation/revocation signals and against silently widening
      access via a different credential.
    * **Transient** errors (5xx/timeout/network/rate-limit) cause
      failover to the next chain member. Log + Prometheus counter
      record the event; the tenant still pays for the failed primary
      call (provider already metered duration).
    * Empty chain after build (primary unbuildable + no fallback) is a
      programmer error — the chain builder always returns at least one.

    Args:
        resolver: Bound :class:`CredentialResolver`.
        store: Optional :class:`CredentialStore` for failover_chain
            resolution. When ``None`` (no DB engine, dev mode) failover
            is silently disabled — chain is always just the primary.
        role_meter: Optional :class:`RoleMeter` for the per-role cost
            ceiling preflight (Phase 6.6 #2b). When ``None`` (no DB
            engine), the gate is silently disabled — ceilings are not
            enforced. When the gate fires, the runtime swaps the role's
            model selection to ``default_model`` for that one call.
        fallback: Provider used when the resolver returns ``None``.
            Defaults to a fresh :class:`DemoProvider` per app instance.
    """

    def __init__(
        self,
        resolver: CredentialResolver,
        store: CredentialStore | None = None,
        role_meter: RoleMeter | None = None,
        fallback: LLMProvider | None = None,
    ) -> None:
        self._resolver = resolver
        self._store = store
        self._role_meter = role_meter
        self._fallback = fallback or DemoProvider()
        # Cache stores chains keyed by primary (tenant, provider, role).
        self._cache: collections.OrderedDict[tuple[str, str, str], list[_ChainEntry]] = collections.OrderedDict()
        self._lock = threading.Lock()

    def call(
        self,
        prompt: str,
        system: str | None = None,
        role: str = "default",
    ) -> str:
        if role not in KNOWN_ROLES:
            # Unknown role is allowed (Enterprise custom roles) but logged
            # so a typo (``"evel"`` -> falls back to default_model silently)
            # surfaces in observability.
            _log.info(
                "provider.unknown_role role=%r — falling back to default_model",
                role,
            )

        scope = get_scope()
        cred = self._resolver.resolve(scope.tenant_id, "llm")
        if cred is None:
            return self._fallback.call(prompt, system=system, role=role)

        # Preflight cost ceiling gate (Phase 6.6 #2b).
        # If this credential has a role_cost_limit for the requested role
        # AND the current month's spend has reached it, swap the call's
        # role to "default" so the chain build uses ``default_model``
        # instead of the (more expensive) override. The credential row
        # is unchanged; only this single call routes to default.
        effective_role = self._apply_cost_ceiling(cred, role, scope.tenant_id)

        chain = self._get_or_build_chain(cred, effective_role)

        last_transient: Exception | None = None
        for index, entry in enumerate(chain):
            try:
                result = entry.provider.call(prompt, system=system, role=effective_role)
                self._meter_after_call(
                    entry=entry,
                    role=effective_role,
                    tenant_id=scope.tenant_id,
                )
                return result
            except Exception as exc:
                if is_auth_error(exc):
                    # Fail fast — never failover on auth-class errors.
                    raise
                last_transient = exc
                if index + 1 < len(chain):
                    _log.warning(
                        "llm.failover tenant=%s chain_pos=%d->%d reason=%s",
                        scope.tenant_id,
                        index,
                        index + 1,
                        exc,
                    )
                    self._observe_failover(scope.tenant_id, index + 1)
        # Whole chain exhausted with transient errors — surface the last one.
        if last_transient is not None:
            raise last_transient
        # Defensive: chain was empty. Should not happen — _build_llm_chain
        # always returns at least the primary entry.
        raise RuntimeError("Empty LLM failover chain — should not happen")

    def invalidate(self, tenant_id: str) -> None:
        """Drop cached chains for a tenant.

        Called from the credential routes after upsert/patch/revoke so
        the next request rebuilds with the new key, model mapping, or
        failover chain. Mirrors :meth:`CredentialResolver.invalidate`.

        Note on cross-credential invalidation: when credential B is
        revoked but credential A's failover_chain references B, A's
        cached chain still includes B's stale provider until invalidated.
        Because both share the same tenant_id, a tenant-scoped flush
        catches both — no per-credential index needed.
        """
        with self._lock:
            keys = [k for k in self._cache if k[0] == tenant_id]
            for k in keys:
                del self._cache[k]

    def _get_or_build_chain(self, cred: TenantCredential, role: str) -> list[_ChainEntry]:
        key = (cred.tenant_id, cred.provider, role)
        with self._lock:
            existing = self._cache.get(key)
            if existing is not None:
                self._cache.move_to_end(key)
                return existing
        chain = _build_llm_chain(cred, role, self._store, self._resolver)
        with self._lock:
            self._cache[key] = chain
            self._cache.move_to_end(key)
            while len(self._cache) > _PROVIDER_CACHE_MAX:
                self._cache.popitem(last=False)
        return chain

    @staticmethod
    def _observe_failover(tenant_id: str, fallback_position: int) -> None:
        """Record a failover event in Prometheus (best-effort)."""
        try:
            from engramia.telemetry import metrics as _metrics

            observer = getattr(_metrics, "observe_failover", None)
            if observer is not None:
                observer(tenant_id, fallback_position)
        except Exception:
            pass  # telemetry never breaks the hot path

    def _meter_after_call(
        self,
        *,
        entry: _ChainEntry,
        role: str,
        tenant_id: str,
    ) -> None:
        """Read the just-completed call's usage from the provider TLS and
        write it into the role spend counter (Phase 6.6 #2b).

        Reads from ``provider._tls.last_usage`` (set by the provider
        after a successful API response) and clears it so a subsequent
        retry path on the same thread cannot double-count. When the
        provider does not expose usage (Ollama, custom openai_compat
        endpoints) or the rate card has no entry for the
        ``(provider_type, model)`` pair, the meter call is a silent
        no-op — the gate logs a warning at most.

        Failures here never propagate: the response was already produced
        and metering must not retroactively invalidate it.
        """
        if self._role_meter is None:
            return
        tls = getattr(entry.provider, "_tls", None)
        if tls is None:
            return
        usage = getattr(tls, "last_usage", None)
        if usage is None:
            return
        # Clear immediately so the next call on this thread cannot reuse
        # a stale read if the provider response path skips the assignment
        # (e.g. mocked SDK in tests).
        tls.last_usage = None
        try:
            from engramia.billing.rate_cards import cost_for

            cost_cents = cost_for(
                entry.provider_type,
                entry.model,
                int(usage.get("tokens_in", 0)),
                int(usage.get("tokens_out", 0)),
            )
            if cost_cents is None:
                return  # provider/model not on rate card — silently skip
            self._role_meter.increment_spend(
                tenant_id=tenant_id,
                credential_id=entry.credential_id,
                role=role,
                cost_cents=cost_cents,
                tokens_in=int(usage.get("tokens_in", 0)),
                tokens_out=int(usage.get("tokens_out", 0)),
            )
        except Exception:
            _log.debug("post-call metering failed (non-fatal)", exc_info=True)

    def _apply_cost_ceiling(
        self,
        cred: TenantCredential,
        role: str,
        tenant_id: str,
    ) -> str:
        """Decide whether the role override is still under its monthly budget.

        Returns ``role`` unchanged when:
        - There is no ``RoleMeter`` (no DB engine).
        - The role has no override (``role`` not in ``role_models``) — the
          ceiling does not protect ``default_model`` against itself.
        - The role override has no ``role_cost_limits`` entry.
        - Current month's spend is below the cap.

        Returns ``"default"`` when the cap has been reached. The chain
        builder then uses ``default_model`` for this one call. The
        credential row is **not** mutated — the next month rolls over
        naturally because the counter key includes ``YYYY-MM``.

        Fail-open: if the meter read raises (DB blip), we let the call
        through with the original role. One over-budget call is a
        cheaper failure than blocking traffic on a transient DB issue.
        """
        if self._role_meter is None:
            return role
        cap = cred.cost_ceiling_for_role(role)
        if cap is None:
            return role
        try:
            spend = self._role_meter.get_spend(
                tenant_id=tenant_id,
                credential_id=cred.id,
                role=role,
            )
        except Exception:
            _log.debug(
                "role_meter.get_spend failed — fail-open tenant=%s role=%s",
                tenant_id,
                role,
                exc_info=True,
            )
            return role
        if spend < cap:
            return role
        # Ceiling reached — log + audit + Prometheus, then fall back.
        _log.warning(
            "ROLE_CEILING_EXCEEDED tenant=%s cred=%s role=%s spend=%d cap=%d — falling back to default_model",
            tenant_id,
            cred.id,
            role,
            spend,
            cap,
        )
        try:
            from engramia.telemetry import metrics as _metrics

            observer = getattr(_metrics, "observe_role_ceiling_fallback", None)
            if observer is not None:
                observer(tenant_id, role)
        except Exception:
            pass
        return "default"


class TenantScopedEmbeddingProvider(EmbeddingProvider):
    """Embedding provider that resolves per request from the scope contextvar.

    When the active tenant has no embedding-capable credential, falls
    back to ``LocalEmbeddings`` (sentence-transformers) so tenants in
    demo mode can still exercise the recall path with a non-trivial
    embedding. The fallback is constructed lazily on first use to avoid
    pulling sentence-transformers into the dependency closure of every
    instance.

    Args:
        resolver: Bound :class:`CredentialResolver`.
        fallback: Optional explicit fallback. None means lazy-build a
            :class:`engramia.providers.local_embeddings.LocalEmbeddings`
            on first cache miss.
    """

    def __init__(
        self,
        resolver: CredentialResolver,
        fallback: EmbeddingProvider | None = None,
    ) -> None:
        self._resolver = resolver
        self._fallback: EmbeddingProvider | None = fallback
        self._fallback_lock = threading.Lock()
        self._cache: collections.OrderedDict[tuple[str, str], EmbeddingProvider] = collections.OrderedDict()
        self._lock = threading.Lock()

    def embed(self, text: str) -> list[float]:
        provider = self._resolve_provider()
        return provider.embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        provider = self._resolve_provider()
        return provider.embed_batch(texts)

    def invalidate(self, tenant_id: str) -> None:
        """Drop cached concrete providers for a tenant."""
        with self._lock:
            keys = [k for k in self._cache if k[0] == tenant_id]
            for k in keys:
                del self._cache[k]

    def _resolve_provider(self) -> EmbeddingProvider:
        scope = get_scope()
        # Prefer an embedding-purpose credential, then fall back to an LLM
        # credential whose provider also offers embeddings (OpenAI, Gemini,
        # Ollama do; Anthropic does not).
        cred = self._resolver.resolve(scope.tenant_id, "embedding")
        if cred is None:
            cred = self._resolver.resolve(scope.tenant_id, "llm")
            if cred is None or cred.provider == "anthropic":
                return self._get_fallback()
        try:
            return self._get_or_build_embeddings(cred)
        except (ValueError, ImportError) as exc:
            _log.debug(
                "TenantScopedEmbeddingProvider: provider %r has no embeddings (%s) — using fallback",
                cred.provider,
                exc,
            )
            return self._get_fallback()

    def _get_or_build_embeddings(self, cred: TenantCredential) -> EmbeddingProvider:
        key = (cred.tenant_id, cred.provider)
        with self._lock:
            existing = self._cache.get(key)
            if existing is not None:
                self._cache.move_to_end(key)
                return existing
        provider = _build_embeddings(cred)
        with self._lock:
            self._cache[key] = provider
            self._cache.move_to_end(key)
            while len(self._cache) > _PROVIDER_CACHE_MAX:
                self._cache.popitem(last=False)
        return provider

    def _get_fallback(self) -> EmbeddingProvider:
        if self._fallback is not None:
            return self._fallback
        with self._fallback_lock:
            if self._fallback is not None:
                return self._fallback
            try:
                from engramia.providers.local_embeddings import LocalEmbeddings

                self._fallback = LocalEmbeddings()
                _log.info("TenantScopedEmbeddingProvider: lazy-initialised LocalEmbeddings fallback.")
            except ImportError as exc:
                raise RuntimeError(
                    "No embedding provider configured for the active tenant and "
                    "sentence-transformers is not installed. Add a credential or "
                    "install: pip install 'engramia[local]'."
                ) from exc
        return self._fallback

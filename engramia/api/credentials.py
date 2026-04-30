# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""REST endpoints for the BYOK credential subsystem (Phase 6.6).

Mounted at ``/v1/credentials/`` from :func:`engramia.api.app.create_app`.
All endpoints require the ``credentials:read`` or ``credentials:write``
permission (admin+ role). The plaintext ``api_key`` enters the system
exactly once — in the body of ``POST /v1/credentials`` — and is encrypted
before any DB write or audit log entry.

Endpoints:

| Method | Path                              | Permission           | Purpose                                           |
|--------|-----------------------------------|----------------------|---------------------------------------------------|
| POST   | /v1/credentials                   | credentials:write    | Create or replace a credential (UPSERT)           |
| GET    | /v1/credentials                   | credentials:read     | List all credentials for the active tenant       |
| GET    | /v1/credentials/{id}              | credentials:read     | Get one credential's metadata (no plaintext)     |
| PATCH  | /v1/credentials/{id}              | credentials:write    | Update non-secret fields (model, role_models...) |
| DELETE | /v1/credentials/{id}              | credentials:write    | Soft-delete (status='revoked'); audit retained   |
| POST   | /v1/credentials/{id}/validate     | credentials:write    | Re-validate against provider; rate-limited 1/min |

Decision recap:
- A3: synchronous validation timeout 5s (in :mod:`engramia.credentials.validator`).
- A4: reject on validation failure (HTTP 400, no DB write).
- A5: no idempotency key — UPSERT on (tenant_id, provider, purpose) is
  natively idempotent.
- A10: ``key_fingerprint`` is the last-4-char display string; full plaintext
  is never echoed back, not even to the creator.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from engramia._context import get_scope
from engramia.api.auth import require_auth
from engramia.api.deps import get_auth_context
from engramia.api.errors import ErrorCode
from engramia.api.permissions import require_permission
from engramia.billing.entitlements import require_feature
from engramia.credentials import (
    AESGCMCipher,
    CredentialCreate,
    CredentialPublicView,
    CredentialResolver,
    CredentialStore,
    CredentialUpdate,
    FailoverChainUpdate,
    PatchOutcome,
    RoleCostLimitsUpdate,
    RoleModelsUpdate,
    StoredCredential,
    fingerprint_for,
)
from engramia.credentials import (
    validate as validate_credential,
)
from engramia.types import AuthContext  # noqa: TC001 — FastAPI needs this at runtime for OpenAPI schema

_log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/credentials",
    tags=["Credentials (BYOK)"],
    dependencies=[Depends(require_auth)],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _byok_components(request: Request) -> tuple[CredentialStore, CredentialResolver, AESGCMCipher | None]:
    """Pull store / resolver / cipher off ``app.state`` or fail fast.

    Setting these on ``app.state`` happens in :func:`create_app` only when
    ``ENGRAMIA_BYOK_ENABLED=true``. When disabled, every credential
    endpoint returns 503 — the dashboard knows to hide the LLM-Providers
    section in that case via the same flag exposed at /v1/version.
    """
    state = request.app.state
    store: CredentialStore | None = getattr(state, "credential_store", None)
    resolver: CredentialResolver | None = getattr(state, "credential_resolver", None)
    cipher: AESGCMCipher | None = getattr(state, "credential_cipher", None)
    if store is None or resolver is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": ErrorCode.BYOK_NOT_ENABLED,
                "detail": (
                    "BYOK is not enabled on this Engramia instance. "
                    "Set ENGRAMIA_BYOK_ENABLED=true and provide "
                    "ENGRAMIA_CREDENTIALS_KEY to enable per-tenant credentials."
                ),
            },
        )
    return store, resolver, cipher


def _to_public_view(row: StoredCredential) -> CredentialPublicView:
    """Serialise a stored row to the public schema (no plaintext)."""
    return CredentialPublicView(
        id=row.id,
        provider=row.provider,
        purpose=row.purpose,
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
        last_validation_error=row.last_validation_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _etag_from(row: StoredCredential) -> str:
    """Derive the ETag header value from the row's ``updated_at`` timestamp.

    ISO-8601 in UTC, quoted per RFC 9110. The dashboard reads this from the
    response header (or from the public view's ``updated_at`` field) and
    sends it back as ``If-Match`` on subsequent PATCHes to detect
    concurrent edits — a second admin saving a different role mapping
    while the first one was still editing.
    """
    if row.updated_at is None:
        # Defensive — DB always sets a default. Use a sentinel that never
        # matches a real timestamp so the optimistic-concurrency check
        # does not silently succeed.
        return '"unknown"'
    return f'"{row.updated_at.isoformat()}"'


def _parse_if_match(header_value: str | None) -> datetime | None:
    """Parse an ``If-Match`` header into a :class:`datetime` for comparison.

    Accepts the quoted ISO-8601 form produced by :func:`_etag_from`. Returns
    ``None`` when the header is absent — the route handler decides whether
    that means 428 (mandatory) or fall-through (legacy endpoint).
    """
    if not header_value:
        return None
    raw = header_value.strip().strip('"')
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        # Treat unparseable If-Match as a stale ETag (caller maps to 412).
        # Returning a sentinel that never matches keeps the path uniform
        # without a separate "malformed" branch.
        return datetime.fromisoformat("1970-01-01T00:00:00+00:00")


def _require_if_match(
    request: Request, current_row: StoredCredential
) -> datetime:
    """Enforce mandatory ``If-Match`` on the role-models / failover endpoints.

    Per design B9: both endpoints require ``If-Match`` to make lost-update
    impossible by construction. There are no legacy clients (these routes
    are net-new in Phase 6.6 #2), so strictness is free.

    Raises:
        HTTPException 428: header absent.
        HTTPException 412: header present but does not match the current
            ``updated_at`` — caller is racing another writer.
    """
    header = request.headers.get("if-match")
    if not header:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={
                "error_code": ErrorCode.PRECONDITION_REQUIRED,
                "detail": "If-Match header is required for this endpoint.",
                "current_etag": _etag_from(current_row),
            },
        )
    parsed = _parse_if_match(header)
    if parsed is None or parsed != current_row.updated_at:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={
                "error_code": ErrorCode.PRECONDITION_FAILED,
                "detail": "If-Match does not match current ETag — credential was modified by another writer.",
                "current_etag": _etag_from(current_row),
            },
        )
    return parsed


def _get_subscription(request: Request, tenant_id: str) -> Any:
    """Resolve the active subscription for the entitlement gate.

    Falls through to a developer-tier default when the billing service is
    not configured (env-only deploys, tests). The entitlement check then
    fails for any feature with ``min_tier > "developer"`` — exactly the
    outcome we want for a misconfigured cloud, since silent grant of paid
    features is a worse failure mode than a 402.
    """
    billing_svc = getattr(request.app.state, "billing_service", None)
    if billing_svc is None:
        from engramia.billing.models import BillingSubscription

        return BillingSubscription.developer_default(tenant_id)
    return billing_svc.get_subscription(tenant_id)


def _invalidate_provider_cache(request: Request, tenant_id: str) -> None:
    """Drop the per-tenant provider chain cache after a credential change.

    The Memory facade holds at most one :class:`TenantScopedLLMProvider`
    plus one :class:`TenantScopedEmbeddingProvider`. Both expose
    ``invalidate(tenant_id)``. Find them via app.state and call —
    silently no-op when the deploy uses an unwrapped LLM provider
    (self-host, single-tenant).
    """
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        return
    llm = getattr(memory, "_llm", None) or getattr(memory, "llm", None)
    embed = getattr(memory, "_embed", None) or getattr(memory, "embed", None)
    for provider in (llm, embed):
        invalidator = getattr(provider, "invalidate", None)
        if callable(invalidator):
            try:
                invalidator(tenant_id)
            except Exception:
                _log.debug("provider cache invalidate failed (non-fatal)", exc_info=True)


def _role_models_diff(
    before: dict[str, str], after: dict[str, str]
) -> dict[str, Any]:
    """Compute an audit-friendly diff for ``credential_role_models_updated``.

    The diff is published in structured logs (Loki) so an operator
    investigating a bill spike can see exactly which role flipped to
    which model. Returns three buckets — added / removed / changed —
    each empty when there is nothing in that category.
    """
    added = {k: after[k] for k in after if k not in before}
    removed = sorted([k for k in before if k not in after])
    changed = {
        k: [before[k], after[k]] for k in before if k in after and before[k] != after[k]
    }
    return {"added": added, "removed": removed, "changed": changed}


def _role_cost_limits_diff(
    before: dict[str, int], after: dict[str, int]
) -> dict[str, Any]:
    """Audit diff for ``credential_role_cost_limits_updated`` events.

    Same shape as the role-models diff — kept separate so the values are
    typed as ints (cents) and the audit consumer doesn't accidentally
    parse them as model strings.
    """
    added = {k: after[k] for k in after if k not in before}
    removed = sorted([k for k in before if k not in after])
    changed = {
        k: [before[k], after[k]] for k in before if k in after and before[k] != after[k]
    }
    return {"added": added, "removed": removed, "changed": changed}


def _audit_credential_event(
    request: Request,
    *,
    action: str,
    tenant_id: str,
    detail: dict[str, Any],
) -> None:
    """Best-effort audit log entry. Never raises.

    Resolves the project_id from the active scope (None for tenant-level
    events like credential rotation that aren't tied to a single project),
    then writes via the shared :func:`engramia.api.audit.log_db_event`
    helper. The ``detail`` dict ends up in ``audit_log.detail`` JSONB —
    callers must guarantee no plaintext secret enters this dict.
    """
    try:
        from engramia.api.audit import log_db_event

        engine = getattr(request.app.state, "auth_engine", None)
        if engine is None:
            return  # No DB → no audit log; existing pattern in keys.py
        scope = get_scope()
        project_id = scope.project_id if scope.project_id != "default" else None
        log_db_event(
            engine,
            tenant_id=tenant_id,
            project_id=project_id,
            action=action,
            resource_type="credential",
            resource_id=detail.get("credential_id"),
        )
        # The detail dict is logged separately via the structured logger
        # so it lands in Loki without bloating the audit_log table. The
        # log_redactor (PR2) scrubs anything that looks like a secret.
        _log.info("audit_credential action=%s tenant=%s detail=%s", action, tenant_id, detail)
    except Exception:
        _log.warning("Audit log emit failed for action=%s (non-fatal)", action, exc_info=True)


# ---------------------------------------------------------------------------
# POST /v1/credentials — create or upsert
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=CredentialPublicView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_permission("credentials:write")],
)
def create_credential(
    body: CredentialCreate,
    request: Request,
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> CredentialPublicView:
    """Create or replace the credential for ``(tenant, provider, purpose)``.

    The plaintext ``api_key`` is read once via SecretStr.get_secret_value(),
    validated against the provider's /models endpoint, encrypted with
    AES-256-GCM bound to AAD ``f"{tenant_id}:{provider}:{purpose}"``, and
    written via UPSERT. The provider-side validation is synchronous (5s
    timeout). Failure paths:

    - 400 with category=auth_failed: provider rejected the key (401/403).
    - 400 with category=unreachable: timeout / 5xx / network error.
    - 400 with category=config: missing base_url for openai_compat,
      malformed Ollama URL, etc.

    On success, the LRU cache for this tenant is invalidated so the next
    /v1/evaluate request observes the new key without TTL delay.
    """
    store, resolver, cipher = _byok_components(request)
    if cipher is None:
        # Defensive — _byok_components only returns when store+resolver are
        # set, but cipher could in principle be None if BYOK is configured
        # in resolver-only mode (used in tests). Reject create.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": ErrorCode.BYOK_NOT_ENABLED,
                "detail": "Credential cipher not configured (master key missing).",
            },
        )

    tenant_id = (auth_ctx.tenant_id if auth_ctx else None) or get_scope().tenant_id
    creator_id = (auth_ctx.key_id if auth_ctx else None) or "system"

    plaintext = body.api_key.get_secret_value()
    fingerprint = fingerprint_for(plaintext)

    # Synchronous validation ping (decision A3, A4).
    result = validate_credential(body.provider, plaintext, base_url=body.base_url)
    if not result.success:
        # Audit the rejection (no fingerprint logged because the row was
        # not persisted — the tenant just submitted a bad key).
        _audit_credential_event(
            request,
            action="credential_validation_failed",
            tenant_id=tenant_id,
            detail={"provider": body.provider, "category": result.category},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": ErrorCode.CREDENTIAL_VALIDATION_FAILED,
                "detail": result.error or "Credential validation failed.",
                "provider": body.provider,
                "category": result.category,
            },
        )

    # Encrypt with AAD bound to the (tenant, provider, purpose) triple.
    aad = f"{tenant_id}:{body.provider}:{body.purpose}".encode()
    encrypted_key, nonce, auth_tag = cipher.encrypt(plaintext, aad)

    # Persist via UPSERT.
    row_id = store.upsert(
        tenant_id=tenant_id,
        provider=body.provider,
        purpose=body.purpose,
        encrypted_key=encrypted_key,
        nonce=nonce,
        auth_tag=auth_tag,
        key_version=cipher.key_version,
        key_fingerprint=fingerprint,
        base_url=body.base_url,
        default_model=body.default_model,
        default_embed_model=body.default_embed_model,
        created_by=creator_id,
    )
    if row_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": ErrorCode.STORAGE_ERROR,
                "detail": "Credential store unavailable (no DB engine).",
            },
        )

    # Mark as validated since the ping succeeded.
    store.mark_validated(row_id, error=None)

    # Drop any cached resolution so the next request sees the new key.
    resolver.invalidate(tenant_id)

    # Audit log: only fingerprint, never plaintext.
    _audit_credential_event(
        request,
        action="credential_created",
        tenant_id=tenant_id,
        detail={
            "provider": body.provider,
            "purpose": body.purpose,
            "key_fingerprint": fingerprint,
            "credential_id": row_id,
        },
    )

    # Re-read to populate timestamps in the public view.
    row = store.get_by_id(tenant_id, row_id)
    if row is None:
        # Should not happen — we just wrote it. Fall back to a synthetic view.
        return CredentialPublicView(
            id=row_id,
            provider=body.provider,
            purpose=body.purpose,
            key_fingerprint=fingerprint,
            base_url=body.base_url,
            default_model=body.default_model,
            default_embed_model=body.default_embed_model,
            status="active",
        )
    return _to_public_view(row)


# ---------------------------------------------------------------------------
# GET /v1/credentials — list
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[CredentialPublicView],
    dependencies=[require_permission("credentials:read")],
)
def list_credentials(
    request: Request,
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> list[CredentialPublicView]:
    """Return every credential row for the active tenant — including revoked.

    The dashboard renders revoked rows greyed out so the tenant can see
    what was rotated and when.
    """
    store, _resolver, _cipher = _byok_components(request)
    tenant_id = (auth_ctx.tenant_id if auth_ctx else None) or get_scope().tenant_id
    rows = store.list_for_tenant(tenant_id)
    return [_to_public_view(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /v1/credentials/{id}
# ---------------------------------------------------------------------------


@router.get(
    "/{credential_id}",
    response_model=CredentialPublicView,
    dependencies=[require_permission("credentials:read")],
)
def get_credential(
    credential_id: str,
    request: Request,
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> CredentialPublicView:
    """Get a single credential by id, scoped to the active tenant.

    The store enforces ``WHERE tenant_id = :tid`` on every read, so a
    cross-tenant id guess returns 404 — not 403 — to avoid leaking the
    existence of another tenant's credential id.
    """
    store, _resolver, _cipher = _byok_components(request)
    tenant_id = (auth_ctx.tenant_id if auth_ctx else None) or get_scope().tenant_id
    row = store.get_by_id(tenant_id, credential_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": ErrorCode.CREDENTIAL_NOT_FOUND, "detail": "Credential not found."},
        )
    return _to_public_view(row)


# ---------------------------------------------------------------------------
# PATCH /v1/credentials/{id}
# ---------------------------------------------------------------------------


@router.patch(
    "/{credential_id}",
    response_model=CredentialPublicView,
    dependencies=[require_permission("credentials:write")],
)
def update_credential(
    credential_id: str,
    body: CredentialUpdate,
    request: Request,
    response: Response,
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> CredentialPublicView:
    """Update non-secret fields (default_model, default_embed_model, base_url).

    Per-role routing (``role_models``) and failover chain are NOT edited
    via this endpoint — they live on dedicated tier-gated sub-resources
    (``/role-models`` and ``/failover-chain``) so the Business+ entitlement
    check happens at route level rather than inside the handler.

    The api_key cannot be changed here — to rotate, POST a fresh credential
    on the same (provider, purpose) triple. Keeping rotation explicit at
    the API layer makes the audit log unambiguous: every key rotation has
    its own ``credential_created`` event with the new fingerprint.
    """
    store, resolver, _cipher = _byok_components(request)
    tenant_id = (auth_ctx.tenant_id if auth_ctx else None) or get_scope().tenant_id

    outcome = store.patch(
        tenant_id=tenant_id,
        credential_id=credential_id,
        base_url=body.base_url,
        default_model=body.default_model,
        default_embed_model=body.default_embed_model,
    )
    if outcome in (PatchOutcome.NOT_FOUND, PatchOutcome.NO_DB):
        # Probe so empty-body case can return the current row instead of 404.
        existing = store.get_by_id(tenant_id, credential_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": ErrorCode.CREDENTIAL_NOT_FOUND, "detail": "Credential not found."},
            )
        response.headers["ETag"] = _etag_from(existing)
        return _to_public_view(existing)
    if outcome == PatchOutcome.EMPTY_BODY:
        existing = store.get_by_id(tenant_id, credential_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": ErrorCode.CREDENTIAL_NOT_FOUND, "detail": "Credential not found."},
            )
        response.headers["ETag"] = _etag_from(existing)
        return _to_public_view(existing)

    resolver.invalidate(tenant_id)
    _invalidate_provider_cache(request, tenant_id)
    _audit_credential_event(
        request,
        action="credential_updated",
        tenant_id=tenant_id,
        detail={
            "credential_id": credential_id,
            "fields": [k for k in body.model_dump(exclude_none=True) if k != "api_key"],
        },
    )

    row = store.get_by_id(tenant_id, credential_id)
    assert row is not None  # we just patched it
    response.headers["ETag"] = _etag_from(row)
    return _to_public_view(row)


# ---------------------------------------------------------------------------
# PATCH /v1/credentials/{id}/role-models — Business+ only, mandatory If-Match
# ---------------------------------------------------------------------------


@router.patch(
    "/{credential_id}/role-models",
    response_model=CredentialPublicView,
    dependencies=[require_permission("credentials:role_models:write")],
)
def update_role_models(
    credential_id: str,
    body: RoleModelsUpdate,
    request: Request,
    response: Response,
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> CredentialPublicView:
    """Replace the per-role model mapping for a credential (Business+).

    Full-replace semantics — the body is the new map in its entirety.
    Send ``{"role_models": {}}`` to clear all overrides. Mandatory
    ``If-Match`` header (the ``ETag`` from a previous GET / PATCH) prevents
    lost updates when two admins edit concurrently.

    Tier gate: the entitlement check (``byok.role_models``) runs **before**
    the optimistic-concurrency check, so a Pro-tier admin attempting to
    edit a Business-grandfathered config gets ``402 ENTITLEMENT_REQUIRED``
    rather than ``412 PRECONDITION_FAILED``. The error body carries
    ``current_tier`` and ``required_tier`` for the dashboard upgrade CTA.

    Empty-map clear is allowed on any tier — it is the legitimate exit
    from a downgrade grace state where the tenant cleans up before
    losing the feature.
    """
    store, resolver, _cipher = _byok_components(request)
    tenant_id = (auth_ctx.tenant_id if auth_ctx else None) or get_scope().tenant_id

    existing = store.get_by_id(tenant_id, credential_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": ErrorCode.CREDENTIAL_NOT_FOUND, "detail": "Credential not found."},
        )

    # Tier gate — only when the body sets a non-empty map. An empty {}
    # is the downgrade exit (always allowed).
    if body.role_models:
        sub = _get_subscription(request, tenant_id)
        require_feature(sub, "byok.role_models")

    if_match = _require_if_match(request, existing)

    outcome = store.patch(
        tenant_id=tenant_id,
        credential_id=credential_id,
        role_models=body.role_models,
        if_match_updated_at=if_match,
    )
    if outcome == PatchOutcome.PRECONDITION_FAILED:
        # Race: someone else patched between our GET and our PATCH.
        refreshed = store.get_by_id(tenant_id, credential_id)
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={
                "error_code": ErrorCode.PRECONDITION_FAILED,
                "detail": "Credential was modified concurrently — re-read and retry.",
                "current_etag": _etag_from(refreshed) if refreshed else None,
            },
        )
    if outcome == PatchOutcome.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": ErrorCode.CREDENTIAL_NOT_FOUND, "detail": "Credential not found."},
        )

    resolver.invalidate(tenant_id)
    _invalidate_provider_cache(request, tenant_id)

    diff = _role_models_diff(existing.role_models or {}, body.role_models)
    _audit_credential_event(
        request,
        action="credential_role_models_updated",
        tenant_id=tenant_id,
        detail={
            "credential_id": credential_id,
            "role_models_diff": diff,
        },
    )

    row = store.get_by_id(tenant_id, credential_id)
    assert row is not None
    response.headers["ETag"] = _etag_from(row)
    return _to_public_view(row)


# ---------------------------------------------------------------------------
# PATCH /v1/credentials/{id}/role-cost-limits — Business+ only, mandatory If-Match
# ---------------------------------------------------------------------------


@router.patch(
    "/{credential_id}/role-cost-limits",
    response_model=CredentialPublicView,
    dependencies=[require_permission("credentials:role_cost_limits:write")],
)
def update_role_cost_limits(
    credential_id: str,
    body: RoleCostLimitsUpdate,
    request: Request,
    response: Response,
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> CredentialPublicView:
    """Set per-role monthly $ ceilings for this credential (Business+).

    Map shape: ``{role: max_cents_per_month}``. When a role's spend
    reaches its cap in the current UTC month, the runtime falls back
    to ``default_model`` for that role until the calendar month rolls
    over. Service continuity wins over rigid caps — there is no 429.

    The ceiling protects the **role override** in ``role_models``. It
    does not apply when the role has no override (the call would already
    use ``default_model`` regardless). This is a deliberate design choice
    documented in the per-role-routing docs.

    Same gating shape as the role-models endpoint: tier check on
    non-empty body, mandatory If-Match, admin+ only, audit diff in
    structured logs. Empty {} clears all ceilings on any tier (downgrade
    exit).
    """
    store, resolver, _cipher = _byok_components(request)
    tenant_id = (auth_ctx.tenant_id if auth_ctx else None) or get_scope().tenant_id

    existing = store.get_by_id(tenant_id, credential_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": ErrorCode.CREDENTIAL_NOT_FOUND, "detail": "Credential not found."},
        )

    if body.role_cost_limits:
        sub = _get_subscription(request, tenant_id)
        require_feature(sub, "byok.role_cost_ceiling")

    if_match = _require_if_match(request, existing)

    outcome = store.patch(
        tenant_id=tenant_id,
        credential_id=credential_id,
        role_cost_limits=body.role_cost_limits,
        if_match_updated_at=if_match,
    )
    if outcome == PatchOutcome.PRECONDITION_FAILED:
        refreshed = store.get_by_id(tenant_id, credential_id)
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={
                "error_code": ErrorCode.PRECONDITION_FAILED,
                "detail": "Credential was modified concurrently — re-read and retry.",
                "current_etag": _etag_from(refreshed) if refreshed else None,
            },
        )
    if outcome == PatchOutcome.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": ErrorCode.CREDENTIAL_NOT_FOUND, "detail": "Credential not found."},
        )

    resolver.invalidate(tenant_id)
    _invalidate_provider_cache(request, tenant_id)

    diff = _role_cost_limits_diff(
        existing.role_cost_limits or {},
        body.role_cost_limits,
    )
    _audit_credential_event(
        request,
        action="credential_role_cost_limits_updated",
        tenant_id=tenant_id,
        detail={"credential_id": credential_id, "role_cost_limits_diff": diff},
    )

    row = store.get_by_id(tenant_id, credential_id)
    assert row is not None
    response.headers["ETag"] = _etag_from(row)
    return _to_public_view(row)


# ---------------------------------------------------------------------------
# PATCH /v1/credentials/{id}/failover-chain — Business+ only, mandatory If-Match
# ---------------------------------------------------------------------------


@router.patch(
    "/{credential_id}/failover-chain",
    response_model=CredentialPublicView,
    dependencies=[require_permission("credentials:failover_chain:write")],
)
def update_failover_chain(
    credential_id: str,
    body: FailoverChainUpdate,
    request: Request,
    response: Response,
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> CredentialPublicView:
    """Replace the provider failover chain for a credential (Business+).

    The chain is an ordered list of **other** active credential ids in the
    same tenant. On a transient error from this credential's primary call,
    the runtime tries each entry in order before raising. Auth-class errors
    on any entry fail fast — they never trigger failover, so a rotated key
    surfaces immediately rather than being masked by a working backup.

    Body validation rejects:

    * Self-reference (``id`` in the chain matches the URL ``credential_id``).
    * Duplicates within the chain.
    * Unknown / cross-tenant ids — looked up with ``store.get_by_id``
      (tenant-scoped WHERE, so cross-tenant ids return 404 here).
    * Inactive entries (status != active) — would silently skip at runtime,
      so we surface the bad config at PATCH time instead.
    """
    store, resolver, _cipher = _byok_components(request)
    tenant_id = (auth_ctx.tenant_id if auth_ctx else None) or get_scope().tenant_id

    existing = store.get_by_id(tenant_id, credential_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": ErrorCode.CREDENTIAL_NOT_FOUND, "detail": "Credential not found."},
        )

    # Self-reference check — done first so a Business-tier tenant trying
    # to set self-ref still gets the structural error rather than a tier
    # check that would imply they merely need to upgrade.
    if credential_id in body.failover_chain:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": ErrorCode.FAILOVER_CHAIN_INVALID,
                "detail": "failover_chain cannot reference the credential itself.",
            },
        )

    # Cross-tenant + active-status check for each chain entry.
    for fallback_id in body.failover_chain:
        fallback = store.get_by_id(tenant_id, fallback_id)
        if fallback is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error_code": ErrorCode.FAILOVER_CHAIN_INVALID,
                    "detail": f"failover_chain references unknown credential id: {fallback_id!r}",
                },
            )
        if fallback.status != "active":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error_code": ErrorCode.FAILOVER_CHAIN_INVALID,
                    "detail": f"failover_chain entry {fallback_id!r} is not active (status={fallback.status!r}).",
                },
            )

    # Tier gate — only when setting a non-empty chain. Empty list is the
    # downgrade exit and always allowed.
    if body.failover_chain:
        sub = _get_subscription(request, tenant_id)
        require_feature(sub, "byok.failover_chain")

    if_match = _require_if_match(request, existing)

    outcome = store.patch(
        tenant_id=tenant_id,
        credential_id=credential_id,
        failover_chain=body.failover_chain,
        if_match_updated_at=if_match,
    )
    if outcome == PatchOutcome.PRECONDITION_FAILED:
        refreshed = store.get_by_id(tenant_id, credential_id)
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={
                "error_code": ErrorCode.PRECONDITION_FAILED,
                "detail": "Credential was modified concurrently — re-read and retry.",
                "current_etag": _etag_from(refreshed) if refreshed else None,
            },
        )
    if outcome == PatchOutcome.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": ErrorCode.CREDENTIAL_NOT_FOUND, "detail": "Credential not found."},
        )

    resolver.invalidate(tenant_id)
    _invalidate_provider_cache(request, tenant_id)

    _audit_credential_event(
        request,
        action="credential_failover_chain_updated",
        tenant_id=tenant_id,
        detail={
            "credential_id": credential_id,
            "previous_chain": existing.failover_chain or [],
            "new_chain": body.failover_chain,
        },
    )

    row = store.get_by_id(tenant_id, credential_id)
    assert row is not None
    response.headers["ETag"] = _etag_from(row)
    return _to_public_view(row)


# ---------------------------------------------------------------------------
# DELETE /v1/credentials/{id} — soft-delete (status=revoked)
# ---------------------------------------------------------------------------


@router.delete(
    "/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_permission("credentials:write")],
)
def revoke_credential(
    credential_id: str,
    request: Request,
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> None:
    """Soft-delete: status='revoked'. Audit row preserved.

    After revocation, the credential no longer resolves; subsequent LLM
    calls fall back to demo mode until a new credential is created via
    POST /v1/credentials.
    """
    store, resolver, _cipher = _byok_components(request)
    tenant_id = (auth_ctx.tenant_id if auth_ctx else None) or get_scope().tenant_id
    revoked = store.revoke(tenant_id, credential_id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": ErrorCode.CREDENTIAL_NOT_FOUND,
                "detail": "Credential not found or already revoked.",
            },
        )
    resolver.invalidate(tenant_id)
    _audit_credential_event(
        request,
        action="credential_revoked",
        tenant_id=tenant_id,
        detail={"credential_id": credential_id},
    )


# ---------------------------------------------------------------------------
# POST /v1/credentials/{id}/validate — re-validate without overwrite
# ---------------------------------------------------------------------------


@router.post(
    "/{credential_id}/validate",
    response_model=CredentialPublicView,
    dependencies=[require_permission("credentials:write")],
)
def validate_existing_credential(
    credential_id: str,
    request: Request,
    auth_ctx: AuthContext | None = Depends(get_auth_context),
) -> CredentialPublicView:
    """Decrypt the stored credential and ping the provider's /models again.

    Useful after a 401 from the provider (key rotated externally) to
    confirm the failure mode and update ``last_validation_error``.

    On success: status reset to ``active``, last_validation_error cleared.
    On failure: status -> 'invalid', last_validation_error populated.

    Rate-limited at 1/min per tenant (TODO once a per-route limiter is
    available; for now the global per-key limiter applies).
    """
    store, resolver, cipher = _byok_components(request)
    if cipher is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": ErrorCode.BYOK_NOT_ENABLED,
                "detail": "Credential cipher not configured.",
            },
        )

    tenant_id = (auth_ctx.tenant_id if auth_ctx else None) or get_scope().tenant_id
    row = store.get_by_id(tenant_id, credential_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": ErrorCode.CREDENTIAL_NOT_FOUND, "detail": "Credential not found."},
        )

    aad = f"{row.tenant_id}:{row.provider}:{row.purpose}".encode()
    try:
        plaintext = cipher.decrypt(row.encrypted_key, row.nonce, row.auth_tag, aad)
    except Exception:
        store.mark_invalid(credential_id, "Decryption failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": ErrorCode.INTERNAL_ERROR,
                "detail": "Could not decrypt the stored credential.",
            },
        ) from None

    result = validate_credential(row.provider, plaintext, base_url=row.base_url)
    if result.success:
        store.mark_validated(credential_id, error=None)
        # If the row was previously invalid, flip it back to active.
        if row.status != "active":
            store.upsert(
                tenant_id=row.tenant_id,
                provider=row.provider,
                purpose=row.purpose,
                encrypted_key=row.encrypted_key,
                nonce=row.nonce,
                auth_tag=row.auth_tag,
                key_version=row.key_version,
                key_fingerprint=row.key_fingerprint,
                base_url=row.base_url,
                default_model=row.default_model,
                default_embed_model=row.default_embed_model,
                created_by="system_revalidate",
            )
            resolver.invalidate(tenant_id)
    else:
        store.mark_invalid(credential_id, result.error or "Validation failed")

    _audit_credential_event(
        request,
        action="credential_validated",
        tenant_id=tenant_id,
        detail={
            "credential_id": credential_id,
            "success": result.success,
            "category": result.category,
        },
    )

    refreshed = store.get_by_id(tenant_id, credential_id)
    assert refreshed is not None
    return _to_public_view(refreshed)

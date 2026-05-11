# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Admin Dashboard BYOK credentials endpoints.

Phase 3 surface — list which LLM providers a tenant has configured
(without ever decrypting), force-clear keys (incident response, marks
rows as 'revoked' so the tenant gets a clear audit signal), inspect
vault backend health.

The plaintext key NEVER touches the admin endpoint. Only fingerprints
and metadata (provider, purpose, last_used, last_validated_at).
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from engramia.admin_auth.service import AdminAuthService
from engramia.api.admin.audit import log_admin_event, update_admin_event_status
from engramia.api.admin.deps import (
    AdminContext,
    _client_ip,
    get_admin_auth_service,
    require_fresh_totp,
    require_super_admin,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/credentials", tags=["Admin Credentials"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CredentialRow(BaseModel):
    id: str
    provider: str
    purpose: str
    key_fingerprint: str
    base_url: str | None = None
    default_model: str | None = None
    default_embed_model: str | None = None
    status: str  # active | revoked | invalid
    last_used_at: datetime | None = None
    last_validated_at: datetime | None = None
    last_validation_error: str | None = None
    created_at: datetime
    updated_at: datetime


class TenantCredentialsResponse(BaseModel):
    tenant_id: str
    tenant_name: str | None = None
    credentials: list[CredentialRow]
    backend: str = Field(
        description="Configured credential backend: 'local' (AES-GCM) or 'vault' (Vault Transit).",
    )


class ForceClearBody(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)
    providers: list[str] | None = Field(
        default=None,
        description=(
            "Optional subset of providers to clear (openai, anthropic, …). "
            "Defaults to all of tenant's credentials when omitted."
        ),
    )


class ForceClearResponse(BaseModel):
    tenant_id: str
    cleared_count: int
    cleared_ids: list[str]


class VaultHealthEntry(BaseModel):
    tenant_id: str
    backend: str
    healthy: bool
    last_failover_at: datetime | None = None
    note: str | None = None


class VaultHealthResponse(BaseModel):
    backend_configured: str
    entries: list[VaultHealthEntry]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _environment() -> str:
    import os as _os
    return _os.environ.get("ENGRAMIA_ENVIRONMENT", "unknown").strip().lower() or "unknown"


def _configured_backend() -> str:
    import os as _os
    return _os.environ.get("ENGRAMIA_CREDENTIALS_BACKEND", "local").strip().lower() or "local"


# ---------------------------------------------------------------------------
# GET /v1/admin/credentials/vault-health
#
# IMPORTANT: this MUST be declared before the ``/{tenant_id}`` path below,
# otherwise FastAPI's first-match-wins routing treats "vault-health" as a
# tenant_id parameter and the request 404s on "Tenant not found".
# ---------------------------------------------------------------------------


@router.get(
    "/vault-health",
    response_model=VaultHealthResponse,
    summary="Vault Transit backend health per tenant",
)
async def vault_health(
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> VaultHealthResponse:
    backend = _configured_backend()

    if backend != "vault":
        # Local AES-GCM backend has no remote health — return empty.
        return VaultHealthResponse(
            backend_configured=backend,
            entries=[],
        )

    # Vault Transit path — probe each tenant's transit key by attempting a
    # no-op (sys/health endpoint via VaultTransitBackend.health() if it
    # exposes that helper). Best-effort; surface failures per tenant.
    engine = svc._engine  # noqa: SLF001
    with engine.begin() as conn:
        tenant_rows = conn.execute(
            text("SELECT DISTINCT tenant_id FROM tenant_credentials"),
        ).fetchall()

    entries: list[VaultHealthEntry] = []
    try:
        from engramia.credentials.backends.vault import VaultTransitBackend

        for r in tenant_rows:
            tid = str(r[0])
            try:
                backend_inst = VaultTransitBackend.from_env()
                if hasattr(backend_inst, "health"):
                    healthy = bool(backend_inst.health(tenant_id=tid))
                    note = None
                else:
                    healthy = True
                    note = "Vault backend has no health() probe — reporting reachable"
            except Exception as exc:  # noqa: BLE001
                healthy = False
                note = str(exc)[:200]
            entries.append(
                VaultHealthEntry(
                    tenant_id=tid, backend="vault", healthy=healthy, note=note,
                )
            )
    except ImportError:
        return VaultHealthResponse(
            backend_configured=backend,
            entries=[
                VaultHealthEntry(
                    tenant_id="*",
                    backend=backend,
                    healthy=False,
                    note="Vault backend module not installed (engramia[vault] extra).",
                ),
            ],
        )

    return VaultHealthResponse(backend_configured=backend, entries=entries)


# ---------------------------------------------------------------------------
# GET /v1/admin/credentials/{tenant_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{tenant_id}",
    response_model=TenantCredentialsResponse,
    summary="List BYOK credentials configured for a tenant (no plaintext)",
)
async def list_tenant_credentials(
    tenant_id: str,
    _ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> TenantCredentialsResponse:
    engine = svc._engine  # noqa: SLF001
    with engine.begin() as conn:
        tenant = conn.execute(
            text("SELECT id, name FROM tenants WHERE id = :tid"), {"tid": tenant_id},
        ).first()
        if tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")

        rows = conn.execute(
            text(
                "SELECT id, provider, purpose, key_fingerprint, base_url, "
                "default_model, default_embed_model, status, last_used_at, "
                "last_validated_at, last_validation_error, created_at, updated_at "
                "FROM tenant_credentials WHERE tenant_id = :tid "
                "ORDER BY provider, purpose",
            ),
            {"tid": tenant_id},
        ).fetchall()

    return TenantCredentialsResponse(
        tenant_id=str(tenant[0]),
        tenant_name=str(tenant[1]) if tenant[1] else None,
        backend=_configured_backend(),
        credentials=[
            CredentialRow(
                id=str(r[0]),
                provider=str(r[1]),
                purpose=str(r[2]),
                key_fingerprint=str(r[3]),
                base_url=str(r[4]) if r[4] else None,
                default_model=str(r[5]) if r[5] else None,
                default_embed_model=str(r[6]) if r[6] else None,
                status=str(r[7]),
                last_used_at=r[8],
                last_validated_at=r[9],
                last_validation_error=str(r[10]) if r[10] else None,
                created_at=r[11],
                updated_at=r[12],
            )
            for r in rows
        ],
    )


# ---------------------------------------------------------------------------
# POST /v1/admin/credentials/{tenant_id}/clear
# ---------------------------------------------------------------------------


@router.post(
    "/{tenant_id}/clear",
    response_model=ForceClearResponse,
    summary="Force-clear BYOK credentials (incident response)",
    dependencies=[Depends(require_fresh_totp())],
)
async def force_clear_credentials(
    request: Request,
    tenant_id: str,
    body: ForceClearBody = Body(...),
    ctx: AdminContext = Depends(require_super_admin),
    svc: AdminAuthService = Depends(get_admin_auth_service),
) -> ForceClearResponse:
    engine = svc._engine  # noqa: SLF001
    event_id = log_admin_event(
        engine,
        actor_admin_user_id=ctx.admin_user_id,
        action="credentials.force_clear",
        resource_type="tenant",
        resource_id=tenant_id,
        environment=_environment(),
        ip_address=_client_ip(request),
        detail={
            "reason": body.reason[:300],
            "providers": body.providers or "all",
        },
    )

    try:
        with engine.begin() as conn:
            tenant = conn.execute(
                text("SELECT id FROM tenants WHERE id = :tid"), {"tid": tenant_id},
            ).first()
            if tenant is None:
                update_admin_event_status(
                    engine, event_id=event_id, status="failed", error="tenant_not_found",
                )
                raise HTTPException(status_code=404, detail="Tenant not found")

            params: dict = {"tid": tenant_id}
            if body.providers:
                placeholders = ",".join(f":p{i}" for i, _ in enumerate(body.providers))
                provider_filter = f" AND provider IN ({placeholders})"
                for i, p in enumerate(body.providers):
                    params[f"p{i}"] = p
            else:
                provider_filter = ""

            # Mark as revoked (not DELETE). Auditable, lets us see what was
            # cleared and when. Customer-side: their next API call routed
            # through that key gets a clear "credentials revoked" error,
            # not a silent fallback.
            result = conn.execute(
                text(
                    "UPDATE tenant_credentials SET status = 'revoked', "
                    "updated_at = now() "
                    f"WHERE tenant_id = :tid AND status = 'active'{provider_filter} "
                    "RETURNING id",
                ),
                params,
            ).fetchall()
            cleared_ids = [str(r[0]) for r in result]

        update_admin_event_status(
            engine, event_id=event_id, status="succeeded",
            result_detail={"cleared_count": len(cleared_ids), "cleared_ids": cleared_ids},
        )
        return ForceClearResponse(
            tenant_id=tenant_id, cleared_count=len(cleared_ids), cleared_ids=cleared_ids,
        )

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        update_admin_event_status(engine, event_id=event_id, status="failed", error=str(exc))
        raise



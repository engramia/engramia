# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""CRUD operations for the ``tenant_credentials`` table.

Plain raw SQL via ``sqlalchemy.text``, mirroring the style of
``engramia/billing/service.py``: thin DB layer with explicit queries,
no ORM lazy-loading surprises, easy to grep for.

Design rules:

- The store is **scope-blind** at the function level — every method takes
  ``tenant_id`` as an explicit parameter. The caller is responsible for
  passing the right tenant_id (typically from
  :py:func:`engramia._context.get_scope`). This keeps the store
  test-friendly and makes cross-tenant access bugs visible at the call
  site rather than hidden inside the layer.

- The plaintext ``api_key`` never enters this module's signatures. Encryption
  happens **before** :meth:`CredentialStore.create`, decryption happens in
  :class:`CredentialResolver` after fetching a row.

- Soft-delete (``status='revoked'``) preserves the audit trail. Hard delete
  is reserved for tenant-cascade (handled by the FK ON DELETE CASCADE).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlalchemy.exc
from sqlalchemy import text

if TYPE_CHECKING:
    import datetime

    from engramia.credentials.models import ProviderType, PurposeType, StatusType

_log = logging.getLogger(__name__)


@dataclass
class StoredCredential:
    """Raw row data as returned by SELECT — encrypted, not yet usable.

    Fields mirror the migration 023 schema. The store returns these to the
    resolver, which decrypts ``encrypted_key`` and constructs a
    :class:`engramia.credentials.models.TenantCredential` for downstream use.
    """

    id: str
    tenant_id: str
    provider: ProviderType
    purpose: PurposeType
    encrypted_key: bytes
    nonce: bytes
    auth_tag: bytes
    key_version: int
    key_fingerprint: str
    base_url: str | None
    default_model: str | None
    default_embed_model: str | None
    role_models: dict[str, str]
    status: StatusType
    last_used_at: datetime.datetime | None
    last_validated_at: datetime.datetime | None
    last_validation_error: str | None
    created_at: datetime.datetime | None
    created_by: str | None


_SELECT_COLUMNS = (
    "id, tenant_id, provider, purpose, "
    "encrypted_key, nonce, auth_tag, key_version, key_fingerprint, "
    "base_url, default_model, default_embed_model, role_models, "
    "status, last_used_at, last_validated_at, last_validation_error, "
    "created_at, created_by"
)


def _row_to_stored(row: Any) -> StoredCredential:
    """Convert a SQLAlchemy row tuple to a :class:`StoredCredential`."""
    return StoredCredential(
        id=row[0],
        tenant_id=row[1],
        provider=row[2],
        purpose=row[3],
        encrypted_key=bytes(row[4]),
        nonce=bytes(row[5]),
        auth_tag=bytes(row[6]),
        key_version=row[7],
        key_fingerprint=row[8],
        base_url=row[9],
        default_model=row[10],
        default_embed_model=row[11],
        role_models=row[12] or {},
        status=row[13],
        last_used_at=row[14],
        last_validated_at=row[15],
        last_validation_error=row[16],
        created_at=row[17],
        created_by=row[18],
    )


class CredentialStore:
    """Per-tenant CRUD for ``tenant_credentials`` via raw SQL.

    All methods are safe to call with ``engine=None`` — they return
    no-op results matching the dev/JSON-storage path. This mirrors
    :class:`engramia.billing.service.BillingService` so the API can be
    unconditionally constructed even when no DB is configured.
    """

    def __init__(self, engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Read paths
    # ------------------------------------------------------------------

    def get(
        self,
        tenant_id: str,
        provider: ProviderType,
        purpose: PurposeType,
    ) -> StoredCredential | None:
        """Return the active credential for ``(tenant_id, provider, purpose)``.

        Returns ``None`` when:
          - the engine is not configured (dev / JSON storage),
          - no row exists,
          - the row exists but is not in ``status='active'`` (revoked / invalid
            credentials are kept for audit but not resolvable).
        """
        if self._engine is None:
            return None
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text(
                        f"SELECT {_SELECT_COLUMNS} FROM tenant_credentials "
                        "WHERE tenant_id = :tid AND provider = :prov "
                        "AND purpose = :purp AND status = 'active'"
                    ),
                    {"tid": tenant_id, "prov": provider, "purp": purpose},
                ).fetchone()
        except sqlalchemy.exc.SQLAlchemyError:
            _log.warning("CredentialStore.get DB error", exc_info=True)
            return None
        return _row_to_stored(row) if row else None

    def get_active_for_purpose(
        self,
        tenant_id: str,
        purpose: PurposeType,
    ) -> StoredCredential | None:
        """Return the active credential serving ``purpose`` for any provider.

        Used by :class:`CredentialResolver` which doesn't know which provider
        the tenant configured. Tries an exact ``purpose`` match first, then
        falls back to ``purpose='both'`` (so a single credential covering
        both LLM and embedding works for either query).

        At most one provider can be active per ``(tenant_id, purpose)`` from
        the UNIQUE constraint, so the result is unambiguous.
        """
        if self._engine is None:
            return None
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text(
                        f"SELECT {_SELECT_COLUMNS} FROM tenant_credentials "
                        "WHERE tenant_id = :tid AND status = 'active' "
                        "AND (purpose = :purp OR purpose = 'both') "
                        "ORDER BY (purpose = :purp) DESC, created_at DESC "
                        "LIMIT 1"
                    ),
                    {"tid": tenant_id, "purp": purpose},
                ).fetchone()
        except sqlalchemy.exc.SQLAlchemyError:
            _log.warning("CredentialStore.get_active_for_purpose DB error", exc_info=True)
            return None
        return _row_to_stored(row) if row else None

    def get_by_id(self, tenant_id: str, credential_id: str) -> StoredCredential | None:
        """Return a row by primary key, scoped to the requesting tenant.

        ``tenant_id`` is enforced in the WHERE clause so a caller cannot
        accidentally read another tenant's credential by guessing UUIDs.
        """
        if self._engine is None:
            return None
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text(f"SELECT {_SELECT_COLUMNS} FROM tenant_credentials WHERE id = :id AND tenant_id = :tid"),
                    {"id": credential_id, "tid": tenant_id},
                ).fetchone()
        except sqlalchemy.exc.SQLAlchemyError:
            _log.warning("CredentialStore.get_by_id DB error", exc_info=True)
            return None
        return _row_to_stored(row) if row else None

    def list_for_tenant(self, tenant_id: str) -> list[StoredCredential]:
        """Return every credential row for a tenant — including revoked.

        The dashboard needs to show "your previous OpenAI key was revoked
        on …" so we expose all statuses. The route handler is responsible
        for converting these to :class:`CredentialPublicView` (no plaintext).
        """
        if self._engine is None:
            return []
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    text(
                        f"SELECT {_SELECT_COLUMNS} FROM tenant_credentials "
                        "WHERE tenant_id = :tid ORDER BY provider, purpose, created_at DESC"
                    ),
                    {"tid": tenant_id},
                ).fetchall()
        except sqlalchemy.exc.SQLAlchemyError:
            _log.warning("CredentialStore.list_for_tenant DB error", exc_info=True)
            return []
        return [_row_to_stored(r) for r in rows]

    # ------------------------------------------------------------------
    # Write paths
    # ------------------------------------------------------------------

    def upsert(
        self,
        *,
        tenant_id: str,
        provider: ProviderType,
        purpose: PurposeType,
        encrypted_key: bytes,
        nonce: bytes,
        auth_tag: bytes,
        key_version: int,
        key_fingerprint: str,
        base_url: str | None,
        default_model: str | None,
        default_embed_model: str | None,
        created_by: str,
    ) -> str | None:
        """Insert or replace the credential for ``(tenant_id, provider, purpose)``.

        On conflict on the unique triple, the existing row is updated:
        ciphertext + fingerprint + base_url + default_model are replaced,
        ``status`` is reset to ``active`` (so a previously-revoked key slot
        is re-activated by the new value), and ``role_models`` is left
        intact (PATCH endpoint owns it).

        Returns the row id of the new or updated record, or ``None`` if
        ``engine`` is unset.

        Raises:
            sqlalchemy.exc.SQLAlchemyError: DB-level failure. The route
                handler should catch and return 500 / 503.
        """
        if self._engine is None:
            return None
        params = {
            "tid": tenant_id,
            "prov": provider,
            "purp": purpose,
            "ek": encrypted_key,
            "nonce": nonce,
            "tag": auth_tag,
            "kv": key_version,
            "fp": key_fingerprint,
            "burl": base_url,
            "dm": default_model,
            "dem": default_embed_model,
            "cb": created_by,
        }
        with self._engine.begin() as conn:
            row = conn.execute(
                text("""
                    INSERT INTO tenant_credentials (
                        tenant_id, provider, purpose,
                        encrypted_key, nonce, auth_tag,
                        key_version, key_fingerprint,
                        base_url, default_model, default_embed_model,
                        status, created_by
                    ) VALUES (
                        :tid, :prov, :purp,
                        :ek, :nonce, :tag,
                        :kv, :fp,
                        :burl, :dm, :dem,
                        'active', :cb
                    )
                    ON CONFLICT (tenant_id, provider, purpose) DO UPDATE SET
                        encrypted_key = EXCLUDED.encrypted_key,
                        nonce = EXCLUDED.nonce,
                        auth_tag = EXCLUDED.auth_tag,
                        key_version = EXCLUDED.key_version,
                        key_fingerprint = EXCLUDED.key_fingerprint,
                        base_url = EXCLUDED.base_url,
                        default_model = EXCLUDED.default_model,
                        default_embed_model = EXCLUDED.default_embed_model,
                        status = 'active',
                        last_validation_error = NULL,
                        updated_at = now()
                    RETURNING id
                """),
                params,
            ).fetchone()
        return row[0] if row else None

    def patch(
        self,
        *,
        tenant_id: str,
        credential_id: str,
        base_url: str | None = None,
        default_model: str | None = None,
        default_embed_model: str | None = None,
        role_models: dict[str, str] | None = None,
    ) -> bool:
        """Update non-secret fields. Returns True if a row was updated.

        ``api_key`` is intentionally NOT a parameter — rotation must go
        through :meth:`upsert` so the encryption path is exercised and the
        old fingerprint is preserved in the audit log.
        """
        if self._engine is None:
            return False
        # Build a partial UPDATE so unset fields are not nulled out.
        sets: list[str] = []
        params: dict[str, Any] = {"id": credential_id, "tid": tenant_id}
        if base_url is not None:
            sets.append("base_url = :burl")
            params["burl"] = base_url
        if default_model is not None:
            sets.append("default_model = :dm")
            params["dm"] = default_model
        if default_embed_model is not None:
            sets.append("default_embed_model = :dem")
            params["dem"] = default_embed_model
        if role_models is not None:
            sets.append("role_models = :rm")
            # SQLAlchemy maps Python dict to JSONB on PostgreSQL.
            params["rm"] = role_models
        if not sets:
            return False
        sets.append("updated_at = now()")
        sql = "UPDATE tenant_credentials SET " + ", ".join(sets) + " WHERE id = :id AND tenant_id = :tid"
        with self._engine.begin() as conn:
            result = conn.execute(text(sql), params)
        return (result.rowcount or 0) > 0

    def revoke(self, tenant_id: str, credential_id: str) -> bool:
        """Soft-delete: mark status='revoked'. Audit row preserved.

        Returns True if a row was updated.
        """
        if self._engine is None:
            return False
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "UPDATE tenant_credentials SET status = 'revoked', updated_at = now() "
                    "WHERE id = :id AND tenant_id = :tid AND status != 'revoked'"
                ),
                {"id": credential_id, "tid": tenant_id},
            )
        return (result.rowcount or 0) > 0

    def mark_invalid(self, credential_id: str, error: str) -> None:
        """Set status='invalid' after a provider-side 401/403 from validation.

        No tenant_id parameter — this is called from background paths where
        the credential id is the only available handle. The id is a UUID
        so cross-tenant collision is impossible.
        """
        if self._engine is None:
            return
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE tenant_credentials "
                    "SET status = 'invalid', last_validation_error = :err, "
                    "    last_validated_at = now(), updated_at = now() "
                    "WHERE id = :id"
                ),
                {"id": credential_id, "err": error[:512]},
            )

    def touch_last_used(self, credential_id: str) -> None:
        """Set last_used_at to NOW. Best-effort, fire-and-forget.

        Errors are logged at DEBUG and swallowed — touch failures must
        not break the request path that triggered the credential use.
        """
        if self._engine is None:
            return
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text("UPDATE tenant_credentials SET last_used_at = now() WHERE id = :id"),
                    {"id": credential_id},
                )
        except sqlalchemy.exc.SQLAlchemyError:
            _log.debug("touch_last_used failed (non-fatal)", exc_info=True)

    def mark_validated(self, credential_id: str, error: str | None = None) -> None:
        """Update last_validated_at + last_validation_error.

        Called after :class:`engramia.credentials.validator` pings the
        provider. ``error=None`` clears any previous error.
        """
        if self._engine is None:
            return
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE tenant_credentials "
                    "SET last_validated_at = now(), last_validation_error = :err, "
                    "    updated_at = now() "
                    "WHERE id = :id"
                ),
                {"id": credential_id, "err": error[:512] if error else None},
            )

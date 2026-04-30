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

import enum
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlalchemy.exc

if TYPE_CHECKING:
    import datetime
from sqlalchemy import text

if TYPE_CHECKING:
    from engramia.credentials.models import ProviderType, PurposeType, StatusType


class PatchOutcome(enum.Enum):
    """Result categories for :meth:`CredentialStore.patch`.

    The credentials route handlers map each outcome to a distinct HTTP
    response so the dashboard can react correctly (412 -> reload prompt,
    404 -> "deleted by another admin", 422 -> "your form is empty").
    """

    UPDATED = "updated"
    NOT_FOUND = "not_found"
    EMPTY_BODY = "empty_body"
    PRECONDITION_FAILED = "precondition_failed"  # If-Match mismatch
    NO_DB = "no_db"  # engine is None — dev/JSON storage


_log = logging.getLogger(__name__)


@dataclass(init=False)
class StoredCredential:
    """Raw row data as returned by SELECT — encrypted, not yet usable.

    Fields mirror the migrations 023, 025, 026, 028 schema. The store
    returns these to the resolver, which decrypts ``ciphertext_blob`` via
    the per-row ``backend`` and constructs a
    :class:`engramia.credentials.models.TenantCredential` for downstream
    use. Defaults are set for fields added in later migrations so test
    fixtures that pre-date the change keep working without explicit
    keyword args.

    The ``encrypted_key`` property is a back-compat alias for
    ``ciphertext_blob`` — the column was renamed in migration 028 to
    reflect that the bytes are backend-opaque (AES-GCM ciphertext for
    the local backend, ``vault:vN:...`` for the Vault backend).
    """

    id: str
    tenant_id: str
    provider: ProviderType
    purpose: PurposeType
    ciphertext_blob: bytes
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
    failover_chain: list[str] = None  # type: ignore[assignment]
    updated_at: datetime.datetime | None = None
    role_cost_limits: dict[str, int] = None  # type: ignore[assignment]
    #: Backend marker from migration 028. ``"local"`` for AES-GCM rows
    #: (the default since 028's NOT NULL DEFAULT clause), ``"vault"``
    #: for rows re-encrypted by the bulk migration script. The resolver
    #: dispatches per-row to the matching :class:`CredentialBackend`.
    backend: str = "local"

    def __init__(
        self,
        *,
        id: str,
        tenant_id: str,
        provider: ProviderType,
        purpose: PurposeType,
        key_version: int,
        key_fingerprint: str,
        base_url: str | None,
        default_model: str | None,
        default_embed_model: str | None,
        role_models: dict[str, str],
        status: StatusType,
        last_used_at: datetime.datetime | None,
        last_validated_at: datetime.datetime | None,
        last_validation_error: str | None,
        created_at: datetime.datetime | None,
        created_by: str | None,
        nonce: bytes = b"",
        auth_tag: bytes = b"",
        ciphertext_blob: bytes | None = None,
        encrypted_key: bytes | None = None,
        failover_chain: list[str] | None = None,
        updated_at: datetime.datetime | None = None,
        role_cost_limits: dict[str, int] | None = None,
        backend: str = "local",
    ) -> None:
        # Back-compat: accept either ``ciphertext_blob`` (new name from
        # migration 028) or ``encrypted_key`` (pre-028 name still used in
        # test fixtures and the api/credentials.py revalidation path).
        if ciphertext_blob is None and encrypted_key is None:
            raise TypeError(
                "StoredCredential requires either 'ciphertext_blob' or 'encrypted_key' (back-compat alias)."
            )
        self.id = id
        self.tenant_id = tenant_id
        self.provider = provider
        self.purpose = purpose
        self.ciphertext_blob = ciphertext_blob if ciphertext_blob is not None else encrypted_key
        self.nonce = nonce
        self.auth_tag = auth_tag
        self.key_version = key_version
        self.key_fingerprint = key_fingerprint
        self.base_url = base_url
        self.default_model = default_model
        self.default_embed_model = default_embed_model
        self.role_models = role_models
        self.status = status
        self.last_used_at = last_used_at
        self.last_validated_at = last_validated_at
        self.last_validation_error = last_validation_error
        self.created_at = created_at
        self.created_by = created_by
        # Empty list / dict normalisation: NULL columns become [] / {}
        # so downstream readers see one shape regardless of nullability.
        self.failover_chain = failover_chain if failover_chain is not None else []
        self.updated_at = updated_at
        self.role_cost_limits = role_cost_limits if role_cost_limits is not None else {}
        self.backend = backend

    @property
    def encrypted_key(self) -> bytes:
        """Back-compat alias for ``ciphertext_blob`` (renamed in 028).

        Existing callers (tests, ``api/credentials.py`` revalidation
        path) reference ``row.encrypted_key`` — keep them working
        without a sweep. New code should use ``ciphertext_blob``.
        """
        return self.ciphertext_blob


_SELECT_COLUMNS = (
    "id, tenant_id, provider, purpose, "
    "ciphertext_blob, nonce, auth_tag, key_version, key_fingerprint, "
    "base_url, default_model, default_embed_model, role_models, failover_chain, "
    "status, last_used_at, last_validated_at, last_validation_error, "
    "created_at, created_by, updated_at, role_cost_limits, backend"
)


def _row_to_stored(row: Any) -> StoredCredential:
    """Convert a SQLAlchemy row tuple to a :class:`StoredCredential`."""
    return StoredCredential(
        id=row[0],
        tenant_id=row[1],
        provider=row[2],
        purpose=row[3],
        ciphertext_blob=bytes(row[4]),
        nonce=bytes(row[5]),
        auth_tag=bytes(row[6]),
        key_version=row[7],
        key_fingerprint=row[8],
        base_url=row[9],
        default_model=row[10],
        default_embed_model=row[11],
        role_models=row[12] or {},
        failover_chain=row[13] or [],
        status=row[14],
        last_used_at=row[15],
        last_validated_at=row[16],
        last_validation_error=row[17],
        created_at=row[18],
        created_by=row[19],
        updated_at=row[20],
        role_cost_limits=row[21] if len(row) > 21 else None,
        # Migration 028 sets the column with NOT NULL DEFAULT 'local',
        # so older test fixtures inserting fewer columns still resolve.
        backend=(row[22] if len(row) > 22 else "local"),
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
        backend: str = "local",
    ) -> str | None:
        """Insert or replace the credential for ``(tenant_id, provider, purpose)``.

        On conflict on the unique triple, the existing row is updated:
        ciphertext + fingerprint + base_url + default_model + backend are
        replaced, ``status`` is reset to ``active`` (so a previously-
        revoked key slot is re-activated by the new value), and
        ``role_models`` is left intact (PATCH endpoint owns it).

        ``encrypted_key`` is the historical kw arg name; it is the bytes
        that go into the ``ciphertext_blob`` column post-migration-028.
        Local backend rows fill ``nonce``/``auth_tag`` with real bytes;
        Vault backend rows pass ``b""`` for both.

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
            "be": backend,
        }
        with self._engine.begin() as conn:
            row = conn.execute(
                text("""
                    INSERT INTO tenant_credentials (
                        tenant_id, provider, purpose,
                        ciphertext_blob, nonce, auth_tag,
                        key_version, key_fingerprint,
                        base_url, default_model, default_embed_model,
                        status, created_by, backend
                    ) VALUES (
                        :tid, :prov, :purp,
                        :ek, :nonce, :tag,
                        :kv, :fp,
                        :burl, :dm, :dem,
                        'active', :cb, :be
                    )
                    ON CONFLICT (tenant_id, provider, purpose) DO UPDATE SET
                        ciphertext_blob = EXCLUDED.ciphertext_blob,
                        nonce = EXCLUDED.nonce,
                        auth_tag = EXCLUDED.auth_tag,
                        key_version = EXCLUDED.key_version,
                        key_fingerprint = EXCLUDED.key_fingerprint,
                        base_url = EXCLUDED.base_url,
                        default_model = EXCLUDED.default_model,
                        default_embed_model = EXCLUDED.default_embed_model,
                        backend = EXCLUDED.backend,
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
        failover_chain: list[str] | None = None,
        role_cost_limits: dict[str, int] | None = None,
        if_match_updated_at: datetime.datetime | None = None,
    ) -> PatchOutcome:
        """Update non-secret fields. Returns :class:`PatchOutcome`.

        Per-role routing (Phase 6.6 #2) and failover chain are persisted via
        this method. ``api_key`` is intentionally NOT a parameter — rotation
        must go through :meth:`upsert` so the encryption path is exercised
        and the old fingerprint is preserved in the audit log.

        Optimistic-concurrency guard: when ``if_match_updated_at`` is
        provided, the UPDATE includes ``AND updated_at = :etag``. If no
        row matches, the method probes for the credential and returns
        ``PatchOutcome.PRECONDITION_FAILED`` (caller maps to HTTP 412) or
        ``PatchOutcome.NOT_FOUND``. The new endpoints require this guard;
        the legacy main PATCH leaves it as ``None`` for backward compat.

        Args:
            tenant_id: Active tenant; enforced in WHERE clause.
            credential_id: Row primary key.
            base_url, default_model, default_embed_model: Optional non-secret
                fields to patch. ``None`` means "leave unchanged" (per-field
                no-op semantic).
            role_models: Full-replace map. ``None`` = no-op, ``{}`` = clear.
            failover_chain: Full-replace list of credential ids. ``None`` =
                no-op, ``[]`` = clear. The list must reference other
                credential ids in the same tenant; cross-tenant validation
                happens at the API layer (defence in depth).
            if_match_updated_at: ETag basis. When set, UPDATE only succeeds
                if the row's current ``updated_at`` matches.

        Returns:
            :class:`PatchOutcome` describing the result.
        """
        if self._engine is None:
            return PatchOutcome.NO_DB
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
            params["rm"] = role_models
        if failover_chain is not None:
            sets.append("failover_chain = :fc")
            params["fc"] = failover_chain
        if role_cost_limits is not None:
            sets.append("role_cost_limits = :rcl")
            params["rcl"] = role_cost_limits
        if not sets:
            return PatchOutcome.EMPTY_BODY
        sets.append("updated_at = now()")
        where = "WHERE id = :id AND tenant_id = :tid"
        if if_match_updated_at is not None:
            where += " AND updated_at = :etag"
            params["etag"] = if_match_updated_at
        sql = "UPDATE tenant_credentials SET " + ", ".join(sets) + " " + where
        with self._engine.begin() as conn:
            result = conn.execute(text(sql), params)
        if (result.rowcount or 0) > 0:
            return PatchOutcome.UPDATED
        if if_match_updated_at is None:
            return PatchOutcome.NOT_FOUND
        # ETag-aware path: distinguish missing row from stale ETag.
        existing = self.get_by_id(tenant_id, credential_id)
        return PatchOutcome.PRECONDITION_FAILED if existing else PatchOutcome.NOT_FOUND

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

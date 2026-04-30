# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Pydantic schemas for the BYOK credential subsystem.

Three distinct shapes:

- :class:`CredentialCreate` — input for ``POST /v1/credentials``. Holds the
  plaintext ``api_key`` as a Pydantic ``SecretStr`` so it never appears in
  ``repr()``, default ``model_dump()``, or default JSON serialisation. The
  raw value is read once via :py:meth:`SecretStr.get_secret_value` inside
  the route handler and forgotten as soon as it is encrypted.

- :class:`TenantCredential` — full in-memory representation populated by
  :class:`engramia.credentials.resolver.CredentialResolver` after AES-GCM
  decryption. Holds the plaintext ``api_key`` because downstream provider
  constructors need it to make outbound HTTPS calls. ``api_key`` is excluded
  from ``model_dump()`` to prevent accidental serialisation.

- :class:`CredentialPublicView` — output for ``GET /v1/credentials``. Has no
  ``api_key`` field at all — the schema itself is the safety net against
  leak via response.

Provider/purpose/status enums are :py:data:`Literal` types matching the
CHECK constraints in migration 023. Pydantic rejects out-of-vocabulary
values at the API boundary.
"""

from __future__ import annotations

import re
from datetime import datetime  # noqa: TC003 — Pydantic needs runtime type, not just type-checking
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

ProviderType = Literal["openai", "anthropic", "gemini", "ollama", "openai_compat"]
PurposeType = Literal["llm", "embedding", "both"]
StatusType = Literal["active", "revoked", "invalid"]


# Default model for each provider when the credential's ``default_model`` is
# unset. Intentionally not the most expensive model — Sonnet/4o-mini level
# so the first run is cheap unless the tenant explicitly upgrades.
_PROVIDER_DEFAULT_MODELS: Final[dict[ProviderType, str]] = {
    "openai": "gpt-4.1",
    "anthropic": "claude-sonnet-4-6",
    "gemini": "gemini-2.5-flash",
    "ollama": "llama3.3",
    "openai_compat": "gpt-4.1",
}


def default_model_for(provider: ProviderType) -> str:
    """Return the fallback model name for ``provider`` when no override exists."""
    return _PROVIDER_DEFAULT_MODELS[provider]


# ---------------------------------------------------------------------------
# Input schemas (REST API)
# ---------------------------------------------------------------------------


class CredentialCreate(BaseModel):
    """Input shape for ``POST /v1/credentials``.

    The ``api_key`` field is a :class:`SecretStr` so:

    - ``repr(model)`` shows ``SecretStr('**********')`` not the plaintext.
    - ``model.model_dump()`` returns a SecretStr object (str() = '**********').
    - ``model.model_dump(mode='json')`` returns ``'**********'``.

    The route handler reads the plaintext via ``model.api_key.get_secret_value()``
    once, encrypts it, and discards the local variable. No log statement,
    error handler, or validator should ever touch ``get_secret_value()``
    outside the encryption path.
    """

    provider: ProviderType
    purpose: PurposeType = "llm"
    api_key: SecretStr = Field(min_length=8, max_length=512)
    base_url: str | None = Field(default=None, max_length=512)
    default_model: str | None = Field(default=None, max_length=128)
    default_embed_model: str | None = Field(default=None, max_length=128)

    @field_validator("api_key")
    @classmethod
    def _api_key_not_blank(cls, v: SecretStr) -> SecretStr:
        plaintext = v.get_secret_value()
        if not plaintext.strip():
            # Custom error WITHOUT including the value
            raise ValueError("api_key cannot be blank or whitespace-only")
        return v

    @field_validator("base_url")
    @classmethod
    def _base_url_must_be_https(cls, v: str | None) -> str | None:
        # Allow None and Ollama localhost (http://); reject other plain http
        # to prevent a tenant accidentally sending their key over plaintext.
        if v is None:
            return v
        if v.startswith("https://"):
            return v
        if v.startswith("http://localhost") or v.startswith("http://127.0.0.1"):
            return v
        raise ValueError("base_url must use https:// (http:// allowed only for localhost / 127.0.0.1)")


# ---------------------------------------------------------------------------
# Internal representation (used by resolver / providers)
# ---------------------------------------------------------------------------


class TenantCredential(BaseModel):
    """In-memory representation of a decrypted credential row.

    Constructed by :class:`engramia.credentials.resolver.CredentialResolver`
    after a successful AES-GCM decryption. The ``api_key`` field carries the
    plaintext provider key — necessary for outbound HTTPS calls — and is
    explicitly excluded from ``model_dump()`` and ``model_dump_json()``.
    """

    id: str
    tenant_id: str
    provider: ProviderType
    purpose: PurposeType
    api_key: str = Field(exclude=True, repr=False)
    key_fingerprint: str
    base_url: str | None = None
    default_model: str | None = None
    default_embed_model: str | None = None
    role_models: dict[str, str] = Field(default_factory=dict)
    failover_chain: list[str] = Field(default_factory=list)
    role_cost_limits: dict[str, int] = Field(default_factory=dict)
    status: StatusType = "active"
    last_used_at: datetime | None = None
    last_validated_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Pydantic v2: do not allow ``api_key`` to be coerced from arbitrary
    # input. It must come from a controlled decryption call.
    model_config = ConfigDict(
        # api_key is not a SecretStr here because the downstream provider
        # SDKs (openai, anthropic) take a plain str. Wrapping it in SecretStr
        # would force unwrapping at every constructor — high friction with
        # no real benefit since it is already excluded from serialisation.
        str_strip_whitespace=True,
    )

    def model_for_role(self, role: str) -> str:
        """Resolve which model to use for a given logical role.

        Args:
            role: One of ``"default"``, ``"eval"``, ``"coder"``, ``"architect"``,
                ``"evolve"``, or any caller-defined string. Falls back to
                ``default_model`` if the role is not in ``role_models``, then
                to the provider-wide default.

        Returns:
            Concrete model identifier accepted by the provider's SDK.
        """
        if role in self.role_models:
            return self.role_models[role]
        return self.default_model or default_model_for(self.provider)

    def cost_ceiling_for_role(self, role: str) -> int | None:
        """Return the per-month cents cap for ``role``, or ``None`` if uncapped.

        The cap **only applies when the role has an override** in
        ``role_models``. If the role would already resolve to
        ``default_model``, the ceiling is moot — there is no cheaper
        target to fall back to.
        """
        if role not in self.role_models:
            return None
        return self.role_cost_limits.get(role)

    def aad(self) -> bytes:
        """Return the AAD bytes used by the AES-GCM cipher for this row.

        Convention: ``f"{tenant_id}:{provider}:{purpose}".encode()``. The
        resolver passes this to :meth:`AESGCMCipher.decrypt`; if the row was
        swapped between tenants in the DB, the AAD bytes will not match what
        was used at encryption time and the auth tag check fails.
        """
        return f"{self.tenant_id}:{self.provider}:{self.purpose}".encode()


# ---------------------------------------------------------------------------
# Output schemas (REST API responses)
# ---------------------------------------------------------------------------


class CredentialPublicView(BaseModel):
    """Output shape for ``GET /v1/credentials`` and similar.

    Has no ``api_key`` field by construction — even an accidental
    ``model_dump()`` cannot leak the plaintext because it isn't there.
    The ``updated_at`` field is the basis for the ``ETag`` response
    header on the per-role / failover endpoints.
    """

    id: str
    provider: ProviderType
    purpose: PurposeType
    key_fingerprint: str
    base_url: str | None = None
    default_model: str | None = None
    default_embed_model: str | None = None
    role_models: dict[str, str] = Field(default_factory=dict)
    failover_chain: list[str] = Field(default_factory=list)
    role_cost_limits: dict[str, int] = Field(default_factory=dict)
    status: StatusType
    last_used_at: datetime | None = None
    last_validated_at: datetime | None = None
    last_validation_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Validation helpers shared by the role-models / failover-chain schemas
# ---------------------------------------------------------------------------

# Lowercase-only role names (server normalises before lookup). Reason: the
# hot-path lookup is case-sensitive on JSONB key match — if we accept
# ``"Eval"`` we silently fall through to ``default_model`` rather than the
# tenant's intended override. Forcing lowercase at the API boundary makes
# this impossible.
_ROLE_NAME_RE: Final = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_MODEL_NAME_RE: Final = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")
_CRED_ID_RE: Final = re.compile(r"^[A-Za-z0-9-]{1,64}$")  # uuid-ish

_ROLE_MODELS_MAX_ENTRIES: Final = 16
_FAILOVER_CHAIN_MAX_LEN: Final = 2  # excludes the primary credential itself


class CredentialUpdate(BaseModel):
    """Input shape for ``PATCH /v1/credentials/{id}``.

    Cannot change ``api_key`` — to rotate, the caller must POST a fresh
    credential, which UPSERTs on ``(tenant_id, provider, purpose)``. This
    keeps the rotation path explicit (audit-loggable as a CREATE+REPLACE)
    rather than a silent UPDATE.

    Note: ``role_models`` and ``failover_chain`` were removed from this
    schema in Phase 6.6 #2 — they are now edited via dedicated tier-gated
    endpoints (``/role-models``, ``/failover-chain``) so the entitlement
    check happens at the route level rather than inside the handler.
    """

    base_url: str | None = Field(default=None, max_length=512)
    default_model: str | None = Field(default=None, max_length=128)
    default_embed_model: str | None = Field(default=None, max_length=128)


class RoleModelsUpdate(BaseModel):
    """Input shape for ``PATCH /v1/credentials/{id}/role-models``.

    Full-replace semantics: the body is the new map in its entirety.
    Send ``{}`` to clear all role overrides. The dashboard uses the
    standard read-modify-write cycle with ``If-Match`` to avoid losing
    concurrent edits.

    Validation:

    * Keys lowercased and matched against ``^[a-z][a-z0-9_]{0,31}$``.
    * Values matched against ``^[A-Za-z0-9._:/-]{1,128}$`` — wide enough
      for OpenAI/Anthropic/Gemini canonical IDs and openai_compat custom
      identifiers like ``"models/together/llama-3.3-70b"``.
    * Hard cap at 16 entries — the canonical role list is six; sixteen
      gives Enterprise tenants room for custom roles without becoming a
      cardinality risk in the provider cache.
    """

    role_models: dict[str, str] = Field(default_factory=dict)

    @field_validator("role_models", mode="before")
    @classmethod
    def _normalise_and_validate(cls, v: Any) -> dict[str, str]:
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("role_models must be a JSON object")
        if len(v) > _ROLE_MODELS_MAX_ENTRIES:
            raise ValueError(f"role_models supports max {_ROLE_MODELS_MAX_ENTRIES} entries (got {len(v)})")
        out: dict[str, str] = {}
        for raw_role, model in v.items():
            if not isinstance(raw_role, str) or not isinstance(model, str):
                raise ValueError("role_models keys and values must be strings")
            role = raw_role.lower()
            if not _ROLE_NAME_RE.match(role):
                raise ValueError(f"invalid role name: {raw_role!r} (lowercase letters/digits/underscore, 1-32 chars)")
            if not _MODEL_NAME_RE.match(model):
                raise ValueError(f"invalid model name: {model!r}")
            out[role] = model
        return out


_ROLE_COST_LIMIT_MAX_CENTS: Final = 10_000_000  # $100 000 / month / role


class RoleCostLimitsUpdate(BaseModel):
    """Input shape for ``PATCH /v1/credentials/{id}/role-cost-limits``.

    Full-replace semantics: the body is the new map in its entirety.
    Send ``{}`` to clear all ceilings. Mandatory ``If-Match`` header.

    The map is ``{role: max_cents_per_month}``. When the role's
    accumulated spend in the current UTC month reaches the cap,
    Engramia falls back to ``default_model`` for that role until the
    calendar month rolls. There is no 429 — service continuity wins
    over rigid caps.

    Validation:

    * Keys lowercased and matched against the canonical role-name regex
      (same as ``RoleModelsUpdate``).
    * Values must be positive integers in cents. Hard upper bound at
      $100 000 / month / role — anything higher signals an off-by-1 000
      mistake (someone typed dollars instead of cents).
    * Hard cap at 16 entries — same envelope as ``role_models``.

    Empty {} clear is allowed on every tier (downgrade exit). A non-
    empty body triggers the ``byok.role_cost_ceiling`` entitlement
    check.
    """

    role_cost_limits: dict[str, int] = Field(default_factory=dict)

    @field_validator("role_cost_limits", mode="before")
    @classmethod
    def _normalise_and_validate(cls, v: Any) -> dict[str, int]:
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("role_cost_limits must be a JSON object")
        if len(v) > _ROLE_MODELS_MAX_ENTRIES:
            raise ValueError(f"role_cost_limits supports max {_ROLE_MODELS_MAX_ENTRIES} entries (got {len(v)})")
        out: dict[str, int] = {}
        for raw_role, cents in v.items():
            if not isinstance(raw_role, str):
                raise ValueError("role_cost_limits keys must be strings")
            role = raw_role.lower()
            if not _ROLE_NAME_RE.match(role):
                raise ValueError(f"invalid role name: {raw_role!r} (lowercase letters/digits/underscore, 1-32 chars)")
            if not isinstance(cents, int) or isinstance(cents, bool):
                raise ValueError(f"role_cost_limits[{role!r}] must be an integer (cents)")
            if cents <= 0:
                raise ValueError(
                    f"role_cost_limits[{role!r}] must be positive (got {cents}); send {{}} to clear all ceilings"
                )
            if cents > _ROLE_COST_LIMIT_MAX_CENTS:
                raise ValueError(
                    f"role_cost_limits[{role!r}]={cents} exceeds the safety ceiling "
                    f"of {_ROLE_COST_LIMIT_MAX_CENTS} cents — did you mean cents not dollars?"
                )
            out[role] = cents
        return out


class FailoverChainUpdate(BaseModel):
    """Input shape for ``PATCH /v1/credentials/{id}/failover-chain``.

    Full-replace semantics: the body is the new ordered list in its
    entirety. Send ``[]`` to disable failover.

    Each entry must be the id of **another** active credential in the
    same tenant. Self-reference is rejected at the application layer
    (the route handler resolves ``{id}`` from the URL and compares).
    Cross-tenant references are rejected by the store-side WHERE clause.
    """

    failover_chain: list[str] = Field(default_factory=list)

    @field_validator("failover_chain", mode="before")
    @classmethod
    def _validate_chain(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("failover_chain must be a JSON array")
        if len(v) > _FAILOVER_CHAIN_MAX_LEN:
            raise ValueError(
                f"failover_chain supports max {_FAILOVER_CHAIN_MAX_LEN} fallback entries "
                f"(primary + {_FAILOVER_CHAIN_MAX_LEN} = {_FAILOVER_CHAIN_MAX_LEN + 1} total chain length)"
            )
        seen: set[str] = set()
        out: list[str] = []
        for entry in v:
            if not isinstance(entry, str):
                raise ValueError("failover_chain entries must be strings")
            if not _CRED_ID_RE.match(entry):
                raise ValueError(f"invalid credential id format: {entry!r}")
            if entry in seen:
                raise ValueError(f"duplicate credential id in chain: {entry!r}")
            seen.add(entry)
            out.append(entry)
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fingerprint_for(api_key: str) -> str:
    """Compute the public fingerprint shown in UI and audit logs.

    Returns ``"<prefix>...<suffix>"`` where prefix is the first 3 chars
    (e.g. ``sk-`` or ``AIz``) and suffix is the last 4 chars. This matches
    the OpenAI / AWS convention and balances "tenant can identify which
    key is active" against "no useful preimage for an attacker".

    Args:
        api_key: Plaintext credential. The function does not log it.

    Returns:
        Display string, e.g. ``"sk-...abcd"``.

    Raises:
        ValueError: If the key is too short to fingerprint safely.
    """
    if len(api_key) < 8:
        raise ValueError("api_key too short to fingerprint (need >= 8 chars)")
    prefix = api_key[:3]
    suffix = api_key[-4:]
    return f"{prefix}...{suffix}"

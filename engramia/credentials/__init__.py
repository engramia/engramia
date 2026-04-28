# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Per-tenant credential storage for Bring-Your-Own-Key LLM providers.

This package implements the BYOK credential subsystem described in
``docs/architecture/credentials.md``. Tenants supply their own LLM provider
API keys (OpenAI, Anthropic, Gemini, Ollama, OpenAI-compatible); Engramia
encrypts them at rest with AES-256-GCM and resolves them per-request from
the active tenant scope.

Public exports:
    AESGCMCipher        — symmetric encryption helper backed by ``cryptography``
    generate_master_key — operator helper for one-time key bootstrap
    CredentialStore     — DB CRUD layer (raw SQL via SQLAlchemy text)
    CredentialResolver  — per-tenant resolver with LRU + 1h TTL cache
    StoredCredential    — encrypted row representation (store output)
    TenantCredential    — decrypted, request-scoped credential (resolver output)
    CredentialCreate    — POST /v1/credentials input schema
    CredentialUpdate    — PATCH /v1/credentials/{id} input schema
    CredentialPublicView — GET /v1/credentials output schema (no plaintext)
    fingerprint_for     — derive ``sk-...abcd`` display string from a plaintext key
    validate            — validate a credential by pinging the provider's /models endpoint
    ValidationResult    — outcome of a single validation attempt
"""

from engramia.credentials.crypto import AESGCMCipher, generate_master_key
from engramia.credentials.models import (
    CredentialCreate,
    CredentialPublicView,
    CredentialUpdate,
    ProviderType,
    PurposeType,
    StatusType,
    TenantCredential,
    fingerprint_for,
)
from engramia.credentials.resolver import CredentialResolver
from engramia.credentials.store import CredentialStore, StoredCredential
from engramia.credentials.validator import ValidationResult, validate

__all__ = [
    # Crypto
    "AESGCMCipher",
    # Schemas
    "CredentialCreate",
    "CredentialPublicView",
    # Resolver
    "CredentialResolver",
    # Store
    "CredentialStore",
    "CredentialUpdate",
    "ProviderType",
    "PurposeType",
    "StatusType",
    "StoredCredential",
    "TenantCredential",
    "ValidationResult",
    "fingerprint_for",
    "generate_master_key",
    # Validator
    "validate",
]

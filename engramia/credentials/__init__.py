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
"""

from engramia.credentials.crypto import AESGCMCipher, generate_master_key

__all__ = ["AESGCMCipher", "generate_master_key"]

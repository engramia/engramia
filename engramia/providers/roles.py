# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Canonical LLM role registry for per-role model routing (Business+ tier).

Roles are *hints* — providers may use them to route to different models, and
tenants may map them to specific model IDs via ``TenantCredential.role_models``.
Unknown roles are not rejected; they fall back to ``default_model`` and emit a
single INFO log so a typo (``"evel"`` vs. ``"eval"``) surfaces in observability
without breaking the call.

The list is intentionally narrow (six entries). Custom roles are an Enterprise
escape hatch — they "just work" because :meth:`TenantCredential.model_for_role`
accepts any string. Adding a new canonical role requires:

1. Adding the string to :data:`KNOWN_ROLES` here.
2. Adding it to ``Dashboard/src/lib/known-roles.ts`` (UI autocomplete mirror —
   tracked in the cross-repo invariants table in workspace ``CLAUDE.md``).
3. Updating ``docs/byok/per-role-routing.md`` with the role description.

There is intentionally no public ``GET /v1/credentials/roles`` endpoint — the
list is static documentation, not runtime state.
"""

from __future__ import annotations

KNOWN_ROLES: frozenset[str] = frozenset(
    {
        "default",  # Generic fallback — anything not explicitly tagged.
        "eval",  # MultiEvaluator scoring — fastest/cheapest model preferred.
        "architect",  # Decomposition + prompt evolution planning — quality preferred.
        "coder",  # Final code synthesis in the compose pipeline.
        "evolve",  # PromptEvolver candidate generation passes.
        "recall",  # Reserved for future LLM rerank in hybrid recall (currently unused).
    }
)


ROLE_DESCRIPTIONS: dict[str, str] = {
    "default": "Generic fallback for any LLM call without an explicit role hint.",
    "eval": "Quality scoring inside MultiEvaluator — pick a fast, cheap model.",
    "architect": "High-level decomposition + prompt evolution planning — pick a quality model.",
    "coder": "Final code synthesis after decomposition — pick a strong code model.",
    "evolve": "Candidate-generation passes inside PromptEvolver — quality > speed.",
    "recall": "Reserved for future LLM rerank in hybrid recall — currently unused.",
}

# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Provider exception classification helper for failover routing.

Used by :class:`engramia.providers.tenant_scoped.TenantScopedLLMProvider` to
decide whether a provider call failure should fail fast (auth/perm/bad
request) or trigger failover to the next credential in the chain (transient
5xx, timeout, network errors).

Auth-class errors must NEVER trigger failover. Reasons:

1. **Rotation signal** — if a primary key was rotated externally, masking
   that with a successful secondary call hides the need to re-validate.
2. **Security** — silently retrying with a different credential after a
   ``PermissionDeniedError`` could grant access the operator did not
   intend (e.g. one key has the right scopes, another does not).
3. **Cost** — bad-request errors mean the *prompt* is malformed; replaying
   it across every provider in the chain just multiplies the failed cost.

Lazy SDK imports keep the optional extras optional — a tenant with only
the openai extra installed never triggers anthropic SDK loading just
because of a classification check.
"""

from __future__ import annotations


def is_auth_error(exc: BaseException) -> bool:
    """True if *exc* is a permanent auth/permission/bad-request error.

    Caller pattern in :class:`TenantScopedLLMProvider.call`::

        try:
            return provider.call(...)
        except Exception as e:
            if is_auth_error(e):
                raise            # bubble up immediately
            # else: try next provider in the failover chain

    Rate-limit errors are intentionally classified as **transient** here —
    if a tenant's OpenAI key is rate-limited, falling over to Anthropic is
    a real win. (This deviates from each SDK's own retry policy, which
    treats 429 as transient too.)
    """
    # OpenAI / openai_compat / Ollama-as-OpenAI-subclass
    try:
        from openai import AuthenticationError, BadRequestError, PermissionDeniedError

        if isinstance(exc, (AuthenticationError, BadRequestError, PermissionDeniedError)):
            return True
    except ImportError:
        pass

    # Anthropic
    try:
        from anthropic import (
            AuthenticationError as _AnthAuth,
        )
        from anthropic import (
            BadRequestError as _AnthBadReq,
        )
        from anthropic import (
            PermissionDeniedError as _AnthPermDenied,
        )

        if isinstance(exc, (_AnthAuth, _AnthBadReq, _AnthPermDenied)):
            return True
    except ImportError:
        pass

    # Gemini — google-genai SDK uses ClientError for 4xx. We treat the whole
    # 4xx family as auth-class for failover purposes: a 400 on the prompt
    # would just repeat across providers, and a 403/401 signals rotation.
    # NB: google-genai's ClientError also covers 429 — accept the small
    # over-classification cost in v1; refine if a customer reports issues.
    try:
        from google.genai import errors as _gerr

        if isinstance(exc, _gerr.ClientError):
            return True
    except ImportError:
        pass

    return False

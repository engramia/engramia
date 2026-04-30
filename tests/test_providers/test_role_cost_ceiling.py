# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Per-role cost ceiling preflight gate (#2b).

Verifies the design invariants from the design summary:

* Ceiling fires only when the role HAS an override in role_models AND
  the role HAS a limit in role_cost_limits AND the current spend has
  reached the cap.
* When fired, the call routes to ``default_model`` (effective_role
  flips to ``"default"``).
* Default-only paths bypass the gate completely (no DB read on every
  call — the precedence chain in :meth:`TenantCredential.cost_ceiling_for_role`
  short-circuits on the role-models check).
* No RoleMeter -> no enforcement (silent disable, dev/JSON storage path).
* Read failure -> fail-open (one over-budget call rather than blocking).
"""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pytest

from engramia._context import reset_scope, set_scope
from engramia.credentials import (
    AESGCMCipher,
    CredentialResolver,
    CredentialStore,
    StoredCredential,
)
from engramia.providers.tenant_scoped import TenantScopedLLMProvider
from engramia.types import Scope

_TEST_KEY = bytes(range(32))


class _FakeStore(CredentialStore):
    def __init__(self) -> None:  # type: ignore[override]
        self._rows: dict[tuple[str, str], StoredCredential] = {}

    def upsert_row(self, row: StoredCredential) -> None:
        self._rows[(row.tenant_id, row.purpose)] = row

    def get_active_for_purpose(self, tenant_id, purpose):  # type: ignore[override]
        return self._rows.get((tenant_id, purpose))

    def get_by_id(self, tenant_id, credential_id):  # type: ignore[override]
        return None  # not exercised in these tests

    def touch_last_used(self, credential_id: str) -> None:  # type: ignore[override]
        pass

    def mark_invalid(self, credential_id: str, error: str) -> None:  # type: ignore[override]
        pass


def _make_row(
    *,
    cipher: AESGCMCipher,
    tenant_id: str = "t1",
    role_models: dict[str, str] | None = None,
    role_cost_limits: dict[str, int] | None = None,
    default_model: str = "gpt-4.1",
) -> StoredCredential:
    aad = f"{tenant_id}:openai:llm".encode()
    ct, nonce, tag = cipher.encrypt("sk-test", aad)
    return StoredCredential(
        id=f"cred-{tenant_id}",
        tenant_id=tenant_id,
        provider="openai",
        purpose="llm",
        encrypted_key=ct,
        nonce=nonce,
        auth_tag=tag,
        key_version=1,
        key_fingerprint="sk-...test",
        base_url=None,
        default_model=default_model,
        default_embed_model=None,
        role_models=role_models or {},
        status="active",
        last_used_at=None,
        last_validated_at=None,
        last_validation_error=None,
        created_at=datetime.datetime.now(datetime.UTC),
        created_by="test",
        updated_at=datetime.datetime.now(datetime.UTC),
        role_cost_limits=role_cost_limits,
    )


@pytest.fixture
def cipher() -> AESGCMCipher:
    return AESGCMCipher(_TEST_KEY)


@pytest.fixture
def scoped_t1():
    token = set_scope(Scope(tenant_id="t1", project_id="default"))
    yield
    reset_scope(token)


def _resolver_with(cipher: AESGCMCipher, row: StoredCredential) -> CredentialResolver:
    store = _FakeStore()
    store.upsert_row(row)
    return CredentialResolver(store=store, cipher=cipher)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


class TestNoMeterDisablesGate:
    def test_call_uses_role_override_when_no_meter(
        self, cipher, scoped_t1
    ) -> None:
        row = _make_row(
            cipher=cipher,
            role_models={"eval": "gpt-4.1-mini"},
            role_cost_limits={"eval": 500},  # set but no meter
        )
        resolver = _resolver_with(cipher, row)

        seen_roles: list[str] = []
        mock = MagicMock()
        mock.call.return_value = "ok"

        def _spy(cred, role):
            seen_roles.append(role)
            return mock

        wrapper = TenantScopedLLMProvider(resolver, role_meter=None)
        with patch(
            "engramia.providers.tenant_scoped._build_one_llm",
            side_effect=_spy,
        ):
            wrapper.call("hi", role="eval")

        # No meter -> gate is silently disabled, override applies.
        assert seen_roles == ["eval"]


class TestCeilingNotReachedKeepsOverride:
    def test_under_budget_uses_override(self, cipher, scoped_t1) -> None:
        row = _make_row(
            cipher=cipher,
            role_models={"eval": "gpt-4.1-mini"},
            role_cost_limits={"eval": 500},
        )
        resolver = _resolver_with(cipher, row)

        meter = MagicMock()
        meter.get_spend.return_value = 100  # well under cap of 500

        seen_roles: list[str] = []
        mock = MagicMock()
        mock.call.return_value = "ok"

        def _spy(cred, role):
            seen_roles.append(role)
            return mock

        wrapper = TenantScopedLLMProvider(resolver, role_meter=meter)
        with patch(
            "engramia.providers.tenant_scoped._build_one_llm",
            side_effect=_spy,
        ):
            wrapper.call("hi", role="eval")

        assert seen_roles == ["eval"]
        meter.get_spend.assert_called_once()


class TestCeilingReachedFallsBackToDefault:
    def test_at_cap_swaps_to_default(self, cipher, scoped_t1) -> None:
        row = _make_row(
            cipher=cipher,
            role_models={"eval": "gpt-4.1-mini"},
            role_cost_limits={"eval": 500},
        )
        resolver = _resolver_with(cipher, row)

        meter = MagicMock()
        meter.get_spend.return_value = 500  # exactly at cap -> fire

        seen_roles: list[str] = []
        mock = MagicMock()
        mock.call.return_value = "ok"

        def _spy(cred, role):
            seen_roles.append(role)
            return mock

        wrapper = TenantScopedLLMProvider(resolver, role_meter=meter)
        with patch(
            "engramia.providers.tenant_scoped._build_one_llm",
            side_effect=_spy,
        ):
            wrapper.call("hi", role="eval")

        # Effective role swapped to "default" -> chain build called with "default"
        assert seen_roles == ["default"]

    def test_over_cap_swaps_to_default(self, cipher, scoped_t1) -> None:
        row = _make_row(
            cipher=cipher,
            role_models={"eval": "gpt-4.1-mini"},
            role_cost_limits={"eval": 500},
        )
        resolver = _resolver_with(cipher, row)

        meter = MagicMock()
        meter.get_spend.return_value = 999  # already overshot

        mock = MagicMock()
        mock.call.return_value = "ok"
        seen_roles: list[str] = []

        def _spy(cred, role):
            seen_roles.append(role)
            return mock

        wrapper = TenantScopedLLMProvider(resolver, role_meter=meter)
        with patch(
            "engramia.providers.tenant_scoped._build_one_llm",
            side_effect=_spy,
        ):
            wrapper.call("hi", role="eval")

        assert seen_roles == ["default"]


class TestNoOverrideNeverFires:
    def test_role_without_override_skips_gate(self, cipher, scoped_t1) -> None:
        """If the role has no role_models entry, the call would already
        use default_model — no point checking the ceiling. The gate
        skips the meter read entirely (perf invariant)."""
        row = _make_row(
            cipher=cipher,
            role_models={},  # no overrides at all
            role_cost_limits={"eval": 500},  # ceiling set but moot
        )
        resolver = _resolver_with(cipher, row)

        meter = MagicMock()

        mock = MagicMock()
        mock.call.return_value = "ok"

        def _spy(cred, role):
            return mock

        wrapper = TenantScopedLLMProvider(resolver, role_meter=meter)
        with patch(
            "engramia.providers.tenant_scoped._build_one_llm",
            side_effect=_spy,
        ):
            wrapper.call("hi", role="eval")

        # Meter was NOT consulted — the gate short-circuited on the
        # cost_ceiling_for_role precedence check.
        meter.get_spend.assert_not_called()


class TestNoCeilingSetSkipsGate:
    def test_role_with_override_but_no_limit(
        self, cipher, scoped_t1
    ) -> None:
        row = _make_row(
            cipher=cipher,
            role_models={"eval": "gpt-4.1-mini"},
            role_cost_limits={},  # empty
        )
        resolver = _resolver_with(cipher, row)

        meter = MagicMock()
        mock = MagicMock()
        mock.call.return_value = "ok"

        def _spy(cred, role):
            return mock

        wrapper = TenantScopedLLMProvider(resolver, role_meter=meter)
        with patch(
            "engramia.providers.tenant_scoped._build_one_llm",
            side_effect=_spy,
        ):
            wrapper.call("hi", role="eval")

        meter.get_spend.assert_not_called()


class TestFailOpen:
    def test_meter_exception_lets_call_through(
        self, cipher, scoped_t1
    ) -> None:
        row = _make_row(
            cipher=cipher,
            role_models={"eval": "gpt-4.1-mini"},
            role_cost_limits={"eval": 500},
        )
        resolver = _resolver_with(cipher, row)

        meter = MagicMock()
        meter.get_spend.side_effect = RuntimeError("DB blip")

        seen_roles: list[str] = []
        mock = MagicMock()
        mock.call.return_value = "ok"

        def _spy(cred, role):
            seen_roles.append(role)
            return mock

        wrapper = TenantScopedLLMProvider(resolver, role_meter=meter)
        with patch(
            "engramia.providers.tenant_scoped._build_one_llm",
            side_effect=_spy,
        ):
            result = wrapper.call("hi", role="eval")

        assert result == "ok"
        # Fail-open: original role kept, override still used.
        assert seen_roles == ["eval"]

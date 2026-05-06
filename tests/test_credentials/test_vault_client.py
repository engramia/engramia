# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Mock-based tests for ``engramia.credentials.backends.vault_client.VaultClient``.

The 313-LOC HTTP wrapper around ``hvac`` is mocked everywhere else in the
test suite (the ``vault.py`` backend layer above is what gets exercised
by the rest of the credentials tests). This module tests the wrapper
itself: AppRole login lifecycle, encrypt/decrypt round-trip via Transit,
403-triggered re-login, background renewal timer, health probe, close.

Real Vault integration is not tested here — the hvac SDK is replaced
with a ``MagicMock`` injected into ``sys.modules`` before VaultClient
imports it. A regression in the wire format / hvac API surface that
the mock doesn't model would still get past these tests; that's a
known trade-off (proposal B2 in the audit punch list covers running
this suite against a real Vault container).

Audit ref: TEST_AUDIT_REPORT_260505.md §1 untested-critical-modules
table — ``vault_client.py`` listed as Critical risk before this file.
"""

from __future__ import annotations

import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

from engramia.exceptions import VaultBackendError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_hvac(monkeypatch):
    """Inject a fake ``hvac`` module into ``sys.modules`` so VaultClient's
    lazy ``import hvac`` resolves to a configurable MagicMock.

    The fake exposes a ``.Client`` callable and an ``.exceptions`` attr;
    individual tests configure ``Client.return_value`` to control what the
    client returned by ``hvac.Client(**kwargs)`` looks like.
    """
    # Some tests may also need the wrapper's module reference dropped so
    # the lazy import re-runs against the fresh sys.modules entry.
    monkeypatch.delitem(sys.modules, "engramia.credentials.backends.vault_client", raising=False)

    fake = MagicMock(name="hvac")
    fake.exceptions.Forbidden = type("Forbidden", (Exception,), {})
    monkeypatch.setitem(sys.modules, "hvac", fake)
    return fake


def _make_login_response(token: str = "tok-test", ttl: float = 3600.0) -> dict:
    return {
        "auth": {"client_token": token, "lease_duration": ttl},
    }


def _make_client(fake_hvac, *, login_response: dict | None = None) -> MagicMock:
    """Configure fake_hvac.Client(...) so the next VaultClient() construction
    returns the prepared client instance from auth.approle.login."""
    client = MagicMock(name="hvac.Client_instance")
    client.auth.approle.login.return_value = login_response or _make_login_response()
    fake_hvac.Client.return_value = client
    return client


def _construct_vc(addr: str = "https://vault.test:8200", **overrides):
    """Import and construct VaultClient — must be called AFTER fake_hvac
    is in sys.modules so the lazy import inside __init__ picks it up."""
    from engramia.credentials.backends.vault_client import VaultClient

    return VaultClient(
        addr=addr,
        role_id=overrides.get("role_id", "role-uuid"),
        secret_id=overrides.get("secret_id", "secret-uuid"),
        transit_path=overrides.get("transit_path", "transit"),
        transit_key=overrides.get("transit_key", "engramia"),
        namespace=overrides.get("namespace"),
        verify=overrides.get("verify", True),
        request_timeout=overrides.get("request_timeout", 5.0),
    )


# ---------------------------------------------------------------------------
# Constructor / AppRole login lifecycle
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_login_success_sets_token_and_schedules_renewal(self, fake_hvac):
        client = _make_client(fake_hvac, login_response=_make_login_response("tok-xyz", 3600.0))

        with patch.object(threading, "Timer") as MockTimer:
            vc = _construct_vc()

            # AppRole login was called with the right credentials.
            client.auth.approle.login.assert_called_once_with(
                role_id="role-uuid", secret_id="secret-uuid"
            )
            # Token was attached to the hvac.Client instance.
            assert client.token == "tok-xyz"
            # Renewal timer scheduled at ttl/2 = 1800 s.
            assert MockTimer.called
            scheduled_delay = MockTimer.call_args[0][0]
            assert 1700 < scheduled_delay < 1900, (
                f"Expected renewal at TTL/2 (~1800s), got {scheduled_delay}"
            )
        vc.close()

    def test_login_exception_raises_vault_backend_error(self, fake_hvac):
        # auth.approle.login itself raising — typical for misconfig
        # (wrong role_id, network unreachable, etc.).
        client = MagicMock()
        client.auth.approle.login.side_effect = RuntimeError("network unreachable")
        fake_hvac.Client.return_value = client

        with pytest.raises(VaultBackendError, match="AppRole login.*failed"):
            _construct_vc()

    def test_login_response_without_client_token_raises(self, fake_hvac):
        # Vault occasionally returns an empty auth block on misconfigured
        # AppRole policies. Must surface as a hard failure rather than
        # silently constructing a useless VaultClient.
        client = MagicMock()
        client.auth.approle.login.return_value = {"auth": {"client_token": "", "lease_duration": 3600.0}}
        fake_hvac.Client.return_value = client

        with pytest.raises(VaultBackendError, match="no client_token"):
            _construct_vc()

    def test_low_ttl_warns_but_proceeds(self, fake_hvac, caplog):
        # An AppRole configured with token_ttl < 5 min triggers the low-TTL
        # warning. Construction still proceeds — operator just gets a
        # log signal to bump the AppRole config.
        _make_client(fake_hvac, login_response=_make_login_response("tok", 60.0))

        with patch.object(threading, "Timer"):
            with caplog.at_level("WARNING"):
                vc = _construct_vc()

            assert any("ttl=" in rec.message and "below recommended minimum" in rec.message for rec in caplog.records), (
                f"Expected low-TTL warning in logs; got: {[r.message for r in caplog.records]}"
            )
        vc.close()

    def test_namespace_propagates_to_hvac_client(self, fake_hvac):
        _make_client(fake_hvac)

        with patch.object(threading, "Timer"):
            vc = _construct_vc(namespace="acme/prod")

        # First positional kwargs to hvac.Client(**kwargs) must contain
        # the namespace — Vault Enterprise feature.
        kwargs = fake_hvac.Client.call_args.kwargs
        assert kwargs["namespace"] == "acme/prod"
        assert kwargs["url"] == "https://vault.test:8200"
        vc.close()


# ---------------------------------------------------------------------------
# encrypt() / decrypt() Transit operations
# ---------------------------------------------------------------------------


class TestEncryptDecrypt:
    def test_encrypt_b64_encodes_inputs_and_parses_key_version(self, fake_hvac):
        client = _make_client(fake_hvac)
        client.secrets.transit.encrypt_data.return_value = {
            "data": {"ciphertext": "vault:v3:abcdef0123456789"}
        }

        with patch.object(threading, "Timer"):
            vc = _construct_vc()
            ct, key_version = vc.encrypt(plaintext="my-secret-key", context=b"tenant=t1")

        assert ct == "vault:v3:abcdef0123456789"
        assert key_version == 3

        # Verify the call shape — plaintext + context are b64-encoded
        # before being sent to hvac.
        call_kwargs = client.secrets.transit.encrypt_data.call_args.kwargs
        assert call_kwargs["name"] == "engramia"
        assert call_kwargs["mount_point"] == "transit"
        # b64('my-secret-key') = 'bXktc2VjcmV0LWtleQ=='
        assert call_kwargs["plaintext"] == "bXktc2VjcmV0LWtleQ=="
        # b64(b'tenant=t1') = 'dGVuYW50PXQx'
        assert call_kwargs["context"] == "dGVuYW50PXQx"

        vc.close()

    def test_encrypt_failure_raises_vault_backend_error(self, fake_hvac):
        client = _make_client(fake_hvac)
        client.secrets.transit.encrypt_data.side_effect = RuntimeError("HTTP 500")

        with patch.object(threading, "Timer"):
            vc = _construct_vc()
            with pytest.raises(VaultBackendError, match="Vault encrypt failed"):
                vc.encrypt(plaintext="x", context=b"y")
        vc.close()

    def test_decrypt_round_trip_decodes_b64_response(self, fake_hvac):
        client = _make_client(fake_hvac)
        # b64('my-secret-key') = 'bXktc2VjcmV0LWtleQ=='
        client.secrets.transit.decrypt_data.return_value = {
            "data": {"plaintext": "bXktc2VjcmV0LWtleQ=="}
        }

        with patch.object(threading, "Timer"):
            vc = _construct_vc()
            pt = vc.decrypt(ciphertext="vault:v3:cipher", context=b"tenant=t1")

        assert pt == "my-secret-key"

        call_kwargs = client.secrets.transit.decrypt_data.call_args.kwargs
        assert call_kwargs["ciphertext"] == "vault:v3:cipher"
        # b64(b'tenant=t1') = 'dGVuYW50PXQx'
        assert call_kwargs["context"] == "dGVuYW50PXQx"

        vc.close()

    def test_decrypt_failure_raises_vault_backend_error(self, fake_hvac):
        client = _make_client(fake_hvac)
        client.secrets.transit.decrypt_data.side_effect = RuntimeError("Bad context")

        with patch.object(threading, "Timer"):
            vc = _construct_vc()
            with pytest.raises(VaultBackendError, match="Vault decrypt failed"):
                vc.decrypt(ciphertext="vault:v1:x", context=b"y")
        vc.close()


# ---------------------------------------------------------------------------
# _with_token — re-login on 403
# ---------------------------------------------------------------------------


class TestTokenInvalidRetry:
    def test_with_token_success_path_runs_op_once(self, fake_hvac):
        client = _make_client(fake_hvac)
        client.secrets.transit.encrypt_data.return_value = {
            "data": {"ciphertext": "vault:v1:ok"}
        }

        with patch.object(threading, "Timer"):
            vc = _construct_vc()
            vc.encrypt(plaintext="x", context=b"c")

        assert client.secrets.transit.encrypt_data.call_count == 1
        # Login was called only once (at __init__) — no re-login on success.
        assert client.auth.approle.login.call_count == 1
        vc.close()

    def test_with_token_403_triggers_relogin_and_retries(self, fake_hvac):
        client = _make_client(fake_hvac)
        # First call: token rejected. Second call (after re-login): success.
        client.secrets.transit.encrypt_data.side_effect = [
            RuntimeError("permission denied"),
            {"data": {"ciphertext": "vault:v1:ok"}},
        ]

        with patch.object(threading, "Timer"):
            vc = _construct_vc()
            ct, _ = vc.encrypt(plaintext="x", context=b"c")

        assert ct == "vault:v1:ok"
        # encrypt_data called twice: first failed, retry succeeded.
        assert client.secrets.transit.encrypt_data.call_count == 2
        # Login called twice: __init__ + post-403 re-login.
        assert client.auth.approle.login.call_count == 2
        vc.close()

    def test_with_token_non_403_exception_propagates_without_retry(self, fake_hvac):
        # A "Connection reset" or 500 error must NOT trigger re-login —
        # that would mask transient infra failures with auth churn.
        client = _make_client(fake_hvac)
        client.secrets.transit.encrypt_data.side_effect = RuntimeError("Connection reset")

        with patch.object(threading, "Timer"):
            vc = _construct_vc()
            with pytest.raises(VaultBackendError):
                vc.encrypt(plaintext="x", context=b"c")

        # Login NOT retried — only the initial __init__ call.
        assert client.auth.approle.login.call_count == 1
        vc.close()


# ---------------------------------------------------------------------------
# _is_token_invalid heuristic
# ---------------------------------------------------------------------------


class TestIsTokenInvalid:
    @pytest.mark.parametrize(
        "message,expected",
        [
            ("permission denied", True),
            ("Permission Denied", True),  # case-insensitive
            ("missing client token", True),
            ("invalid token", True),
            ("403 forbidden — invalid token", True),
            ("Connection refused", False),
            ("HTTP 500 internal server error", False),
            ("timeout waiting for response", False),
            ("400 bad request: malformed payload", False),
        ],
        ids=lambda v: v if isinstance(v, str) else "_",
    )
    def test_classification(self, message, expected):
        from engramia.credentials.backends.vault_client import _is_token_invalid

        assert _is_token_invalid(RuntimeError(message)) is expected


# ---------------------------------------------------------------------------
# Renewal timer behavior
# ---------------------------------------------------------------------------


class TestRenewalTimer:
    def test_renew_self_success_reschedules_at_new_ttl_div_2(self, fake_hvac):
        client = _make_client(fake_hvac)

        with patch.object(threading, "Timer") as MockTimer:
            vc = _construct_vc()
            # The constructor's _login_locked already scheduled one Timer.
            # Reset call history so we can isolate the renewal-only call.
            MockTimer.reset_mock()

            # Configure renew_self to succeed with a 7200 s lease.
            client.auth.token.renew_self.return_value = {
                "auth": {"lease_duration": 7200.0}
            }
            vc._renew_or_relogin()

            # New timer scheduled at 7200 / 2 = 3600 s.
            assert MockTimer.called
            scheduled_delay = MockTimer.call_args[0][0]
            assert 3500 < scheduled_delay < 3700
        vc.close()

    def test_renew_self_exception_falls_back_to_login(self, fake_hvac):
        client = _make_client(fake_hvac)

        with patch.object(threading, "Timer"):
            vc = _construct_vc()

            # Simulate renew_self raising (e.g. token hit max_ttl).
            client.auth.token.renew_self.side_effect = RuntimeError("token expired")
            # Pre-renewal login count.
            initial_login_count = client.auth.approle.login.call_count

            vc._renew_or_relogin()

            # Re-login was triggered as the fallback path.
            assert client.auth.approle.login.call_count == initial_login_count + 1
        vc.close()


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_initialized_and_unsealed_passes(self, fake_hvac):
        client = _make_client(fake_hvac)
        client.sys.is_initialized.return_value = True
        client.sys.is_sealed.return_value = False

        with patch.object(threading, "Timer"):
            vc = _construct_vc()
            # Must not raise.
            vc.health_check()
        vc.close()

    def test_uninitialized_raises(self, fake_hvac):
        client = _make_client(fake_hvac)
        client.sys.is_initialized.return_value = False
        client.sys.is_sealed.return_value = False

        with patch.object(threading, "Timer"):
            vc = _construct_vc()
            with pytest.raises(VaultBackendError, match="sealed or uninitialised"):
                vc.health_check()
        vc.close()

    def test_sealed_raises(self, fake_hvac):
        client = _make_client(fake_hvac)
        client.sys.is_initialized.return_value = True
        client.sys.is_sealed.return_value = True

        with patch.object(threading, "Timer"):
            vc = _construct_vc()
            with pytest.raises(VaultBackendError, match="sealed or uninitialised"):
                vc.health_check()
        vc.close()

    def test_probe_exception_wraps_as_vault_backend_error(self, fake_hvac):
        client = _make_client(fake_hvac)
        client.sys.is_initialized.side_effect = RuntimeError("connection refused")

        with patch.object(threading, "Timer"):
            vc = _construct_vc()
            with pytest.raises(VaultBackendError, match="health check failed"):
                vc.health_check()
        vc.close()


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_cancels_renewal_timer(self, fake_hvac):
        _make_client(fake_hvac)

        with patch.object(threading, "Timer") as MockTimer:
            timer_instance = MagicMock()
            MockTimer.return_value = timer_instance
            vc = _construct_vc()

            vc.close()

            timer_instance.cancel.assert_called_once()

    def test_close_is_idempotent(self, fake_hvac):
        _make_client(fake_hvac)

        with patch.object(threading, "Timer"):
            vc = _construct_vc()
            vc.close()
            # Calling close() again must not raise — operators may call
            # it from multiple shutdown paths (signal handler + atexit).
            vc.close()

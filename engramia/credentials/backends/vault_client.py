# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Thin hvac wrapper for the Vault Transit backend.

Responsibilities:

- AppRole login at startup (so a misconfigured Vault fails the process
  rather than silently falling through to the first decrypt call).
- Background token renewal at half-TTL so we never let the token expire
  mid-request.
- Auto re-login on 403 (token revoked or hit max-TTL).
- ``encrypt`` / ``decrypt`` against the Transit secrets engine, with
  ``derived: true`` ``context`` for the row-substitution defence (see
  ADR-005 in the Vault arch doc).
- Health probe used by ``/v1/health/deep``.

Thread-safety: all public methods are safe to call from the FastAPI
request thread pool. The renewal timer runs on its own thread; the
shared client object's HTTP layer (requests) is thread-safe per
hvac's design.

This module deliberately stays small and policy-free. Higher-level
backend logic (AAD/context construction, EncryptedBlob assembly) lives
in :mod:`engramia.credentials.backends.vault`.
"""

from __future__ import annotations

import base64
import logging
import threading
import time
from typing import TYPE_CHECKING

from engramia.exceptions import VaultBackendError

if TYPE_CHECKING:
    import hvac

_log = logging.getLogger(__name__)

#: Lower bound on token TTL we'll accept from Vault. If Vault hands out a
#: lease shorter than this (operator misconfig), we log a critical warning
#: but still proceed — we can re-login frequently as a fallback.
_MIN_TOKEN_TTL_SECONDS: float = 300.0  # 5 minutes


class VaultClient:
    """Owns the Vault session: AppRole token + renewal timer + Transit ops.

    Args:
        addr: Vault address, e.g. ``https://vault.internal:8200``.
        role_id: AppRole role_id (UUID).
        secret_id: AppRole secret_id (rotatable).
        transit_path: Transit engine mount path. Default ``transit``.
        transit_key: Transit key name. Default ``engramia``.
        namespace: Optional Vault Enterprise namespace.
        verify: TLS verification — bool or path to CA bundle.
        request_timeout: Per-call timeout in seconds.

    Raises:
        VaultBackendError: AppRole login fails at construction.
    """

    def __init__(
        self,
        *,
        addr: str,
        role_id: str,
        secret_id: str,
        transit_path: str = "transit",
        transit_key: str = "engramia",
        namespace: str | None = None,
        verify: bool | str = True,
        request_timeout: float = 5.0,
    ) -> None:
        # Lazy import: hvac is an optional dep.
        try:
            import hvac
        except ImportError as exc:  # pragma: no cover  — guarded by factory
            raise ImportError(
                "VaultClient requires 'hvac'. Install with: pip install 'engramia[vault]'"
            ) from exc

        self._hvac = hvac
        self._addr = addr
        self._role_id = role_id
        self._secret_id = secret_id
        self._transit_path = transit_path.strip("/")
        self._transit_key = transit_key
        self._namespace = namespace
        self._verify = verify
        self._timeout = request_timeout

        self._lock = threading.Lock()
        self._client: hvac.Client | None = None
        self._token_expires_at: float = 0.0
        self._renewal_timer: threading.Timer | None = None
        self._closed = False

        # Initial login — fails loud rather than at first decrypt.
        self._login_locked()

    # ------------------------------------------------------------------
    # Public API — Transit operations
    # ------------------------------------------------------------------

    def encrypt(self, *, plaintext: str, context: bytes) -> tuple[str, int]:
        """Encrypt *plaintext* with Transit derived-key context.

        Returns:
            ``(ciphertext, key_version)`` where ``ciphertext`` is the
            ``vault:vN:...`` string and ``key_version`` is the integer
            ``N`` (useful for post-rotation auditing).

        Raises:
            VaultBackendError: transport, auth, or 5xx.
        """
        b64_pt = base64.b64encode(plaintext.encode("utf-8")).decode("ascii")
        b64_ctx = base64.b64encode(context).decode("ascii")
        try:
            resp = self._with_token(
                lambda c: c.secrets.transit.encrypt_data(
                    name=self._transit_key,
                    plaintext=b64_pt,
                    context=b64_ctx,
                    mount_point=self._transit_path,
                )
            )
        except Exception as exc:
            raise VaultBackendError(f"Vault encrypt failed: {exc}") from exc
        ct = resp["data"]["ciphertext"]
        # Vault format: "vault:vN:..." where N is the integer key version.
        try:
            key_version = int(ct.split(":", 2)[1].lstrip("v"))
        except (IndexError, ValueError):
            key_version = 1
        return ct, key_version

    def decrypt(self, *, ciphertext: str, context: bytes) -> str:
        """Decrypt *ciphertext* (a ``vault:vN:...`` string) with the same
        ``context`` that was used at encrypt time.

        Raises:
            VaultBackendError: transport, auth, 5xx, or 400 (bad context).
                The caller (:class:`VaultTransitBackend.decrypt`) maps
                this back into either :class:`DecryptionError` (when the
                error indicates context mismatch / tampering) or lets it
                propagate as ``VaultBackendError`` (when Vault is just
                unreachable). The distinction is made by HTTP status if
                hvac surfaces it.
        """
        b64_ctx = base64.b64encode(context).decode("ascii")
        try:
            resp = self._with_token(
                lambda c: c.secrets.transit.decrypt_data(
                    name=self._transit_key,
                    ciphertext=ciphertext,
                    context=b64_ctx,
                    mount_point=self._transit_path,
                )
            )
        except Exception as exc:
            raise VaultBackendError(f"Vault decrypt failed: {exc}") from exc
        b64_pt = resp["data"]["plaintext"]
        return base64.b64decode(b64_pt).decode("utf-8")

    def health_check(self) -> None:
        """Probe Vault liveness. Raises on any failure."""
        try:
            client = self._with_token(lambda c: c)
            sealed = not client.sys.is_initialized() or client.sys.is_sealed()
        except Exception as exc:
            raise VaultBackendError(f"Vault health check failed: {exc}") from exc
        if sealed:
            raise VaultBackendError("Vault is sealed or uninitialised")

    def close(self) -> None:
        """Stop the renewal timer. Safe to call multiple times."""
        with self._lock:
            self._closed = True
            if self._renewal_timer is not None:
                self._renewal_timer.cancel()
                self._renewal_timer = None

    # ------------------------------------------------------------------
    # Internal — token lifecycle
    # ------------------------------------------------------------------

    def _with_token(self, op):  # type: ignore[no-untyped-def]
        """Run *op(client)* with a valid token. Re-logs in on 403."""
        client = self._get_client()
        try:
            return op(client)
        except Exception as exc:
            # hvac raises hvac.exceptions.Forbidden on 403; we catch
            # broadly because the precise class hierarchy varies between
            # hvac versions, and we don't want to brittle-couple here.
            if _is_token_invalid(exc):
                _log.info("VAULT_TOKEN_INVALID — re-logging in via AppRole")
                with self._lock:
                    self._login_locked()
                return op(self._get_client())
            raise

    def _get_client(self):  # type: ignore[no-untyped-def]
        with self._lock:
            if self._client is None:
                # Should not happen post-__init__; defensive re-login.
                self._login_locked()
            return self._client

    def _login_locked(self) -> None:
        """Perform AppRole login. Caller MUST hold ``self._lock`` OR be
        in __init__ (single-threaded at construction).
        """
        client_kwargs: dict[str, object] = {
            "url": self._addr,
            "verify": self._verify,
            "timeout": self._timeout,
        }
        if self._namespace:
            client_kwargs["namespace"] = self._namespace
        try:
            client = self._hvac.Client(**client_kwargs)
            resp = client.auth.approle.login(
                role_id=self._role_id,
                secret_id=self._secret_id,
            )
        except Exception as exc:
            raise VaultBackendError(
                f"AppRole login to Vault at {self._addr} failed: {exc}"
            ) from exc

        auth = resp.get("auth") or {}
        token = auth.get("client_token")
        ttl = float(auth.get("lease_duration") or 0.0)
        if not token:
            raise VaultBackendError("AppRole login returned no client_token")
        if ttl < _MIN_TOKEN_TTL_SECONDS:
            _log.warning(
                "VAULT_LOGIN ttl=%ss is below recommended minimum %ss — "
                "operator should bump token_ttl on the AppRole config",
                ttl,
                _MIN_TOKEN_TTL_SECONDS,
            )
            # Fall through; we'll just renew more often.
            ttl = max(ttl, 60.0)  # never schedule renewal below 1 min

        client.token = token
        self._client = client
        self._token_expires_at = time.time() + ttl
        _log.info(
            "VAULT_LOGIN ok addr=%s ttl=%ss expires_at=%s",
            self._addr,
            int(ttl),
            int(self._token_expires_at),
        )

        # Schedule a renewal at TTL/2 — gives plenty of slack for HTTP
        # round-trip and clock skew. If renewal fails we fall back to
        # full re-login on next 403.
        self._schedule_renewal_locked(ttl / 2.0)

    def _schedule_renewal_locked(self, delay_seconds: float) -> None:
        if self._renewal_timer is not None:
            self._renewal_timer.cancel()
        if self._closed:
            return
        timer = threading.Timer(delay_seconds, self._renew_or_relogin)
        timer.daemon = True  # don't block process exit
        timer.start()
        self._renewal_timer = timer

    def _renew_or_relogin(self) -> None:
        """Background timer callback. Tries renew_self; falls back to
        full AppRole login if renewal is rejected."""
        if self._closed:
            return
        with self._lock:
            try:
                # renew_self extends the current token's TTL, up to
                # max_ttl on the AppRole. After max_ttl Vault returns
                # 403 and we re-login.
                resp = self._client.auth.token.renew_self()  # type: ignore[union-attr]
                ttl = float(resp.get("auth", {}).get("lease_duration") or 0.0)
                if ttl > 0:
                    self._token_expires_at = time.time() + ttl
                    _log.info("VAULT_TOKEN_RENEWED ttl=%ss", int(ttl))
                    self._schedule_renewal_locked(ttl / 2.0)
                    return
                _log.info("VAULT_TOKEN_RENEW lease_duration=0 — falling back to AppRole login")
            except Exception as exc:
                _log.warning("VAULT_TOKEN_RENEW failed: %s — falling back to AppRole", exc)

            # Renewal failed or returned 0 TTL: full re-login.
            try:
                self._login_locked()
            except VaultBackendError as exc:
                # Last-ditch: schedule a retry. Don't raise here — the
                # next request will hit the failed token path and
                # surface a 503 then.
                _log.error("VAULT_RELOGIN failed: %s — retrying in 60s", exc)
                self._schedule_renewal_locked(60.0)


def _is_token_invalid(exc: BaseException) -> bool:
    """Heuristic: does the exception indicate "token rejected"?

    hvac raises ``hvac.exceptions.Forbidden`` (403) for missing perms
    AND for invalid tokens. We can't always distinguish without the HTTP
    body, so we check the message text. Conservative on false positives
    is acceptable: re-logging in on a perms-error just costs one extra
    request before the error re-surfaces.
    """
    msg = str(exc).lower()
    return any(s in msg for s in ("permission denied", "missing client token", "invalid token"))

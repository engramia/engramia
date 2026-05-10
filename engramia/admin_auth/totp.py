# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""TOTP (RFC 6238) helpers for admin 2FA.

Encryption-at-rest for the shared secret reuses
``engramia.credentials.crypto.AESGCMCipher`` — the same primitive that
protects tenant BYOK keys. Per-row AAD is bound to the admin user id so
a row swap between admins fails the GCM tag.

Storage layout (single TEXT column ``admin_users.totp_secret_ciphertext``):
    base64(b"v1" || nonce(12) || ciphertext(N) || auth_tag(16))

The ``v1`` prefix reserves a migration channel for future master-key
rotation without an Alembic schema change.
"""

from __future__ import annotations

import base64
import io
import secrets

import pyotp

from engramia.credentials.crypto import AESGCMCipher
from engramia.exceptions import DecryptionError

_BLOB_VERSION = b"v1"
_NONCE_BYTES = 12
_TAG_BYTES = 16

# 160-bit secret (20 bytes) is the RFC 6238 recommendation and what
# Google Authenticator etc. expect by default.
_SECRET_BYTES = 20

_TOTP_ISSUER_NAME = "Engramia Admin"


def _aad(admin_user_id: int) -> bytes:
    """Bind ciphertext to the row that owns it.

    Mirrors the ``f'{tenant_id}:{provider}:{purpose}'`` convention from
    the BYOK resolver but uses the admin user's primary key instead.
    """
    return f"admin_user:{admin_user_id}:totp".encode()


def generate_totp_secret() -> str:
    """Return a fresh base32-encoded TOTP secret."""
    return pyotp.random_base32(length=32)  # 32 chars = 160 bits of entropy


def provisioning_uri(secret: str, account_email: str) -> str:
    """Build the otpauth:// URI a TOTP app scans during enrollment."""
    return pyotp.TOTP(secret).provisioning_uri(
        name=account_email,
        issuer_name=_TOTP_ISSUER_NAME,
    )


def qr_png_bytes(uri: str) -> bytes:
    """Render the otpauth URI as a PNG QR code (bytes)."""
    # Local import keeps the qrcode/PIL dependency optional — only the
    # bootstrap CLI and the future enrollment endpoint will pull it in.
    import qrcode
    from qrcode.image.pil import PilImage

    img: PilImage = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def verify_totp_code(secret: str, code: str) -> bool:
    """Return True if *code* matches the current 30-second TOTP step.

    A ``valid_window=1`` allowance covers ±30 s of clock drift between the
    server and the user's authenticator app — the standard recommendation.
    """
    if not secret or not code:
        return False
    cleaned = code.strip().replace(" ", "")
    if not cleaned.isdigit() or len(cleaned) != 6:
        return False
    return pyotp.TOTP(secret).verify(cleaned, valid_window=1)


def encrypt_totp_secret(secret: str, admin_user_id: int) -> str:
    """Encrypt *secret* (base32 plaintext) for storage in ``admin_users``.

    Returns a base64 string suitable for a single TEXT column. Decrypt
    with :func:`decrypt_totp_secret` using the same admin_user_id.
    """
    cipher = AESGCMCipher.from_env()
    ct, nonce, tag = cipher.encrypt(secret, _aad(admin_user_id))
    blob = _BLOB_VERSION + nonce + ct + tag
    return base64.b64encode(blob).decode("ascii")


def decrypt_totp_secret(encoded: str, admin_user_id: int) -> str:
    """Decrypt a TOTP secret previously produced by :func:`encrypt_totp_secret`."""
    raw = base64.b64decode(encoded.encode("ascii"))
    if not raw.startswith(_BLOB_VERSION):
        raise DecryptionError("Unsupported TOTP secret blob version")
    body = raw[len(_BLOB_VERSION) :]
    if len(body) < _NONCE_BYTES + _TAG_BYTES + 1:
        raise DecryptionError("TOTP secret blob is truncated")
    nonce = body[:_NONCE_BYTES]
    tag = body[-_TAG_BYTES:]
    ct = body[_NONCE_BYTES:-_TAG_BYTES]
    cipher = AESGCMCipher.from_env()
    return cipher.decrypt(ct, nonce, tag, _aad(admin_user_id))

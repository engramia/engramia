# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for engramia.credentials.crypto.AESGCMCipher.

Coverage targets:
- Round-trip encrypt/decrypt happy path
- AAD mismatch detection (the row-substitution defence)
- Tamper detection on ciphertext, nonce, auth_tag
- Master key length validation
- Master key loading from environment variable
- ``generate_master_key`` output shape and entropy
"""

from __future__ import annotations

import base64
import os

import pytest

from engramia.credentials import AESGCMCipher, generate_master_key
from engramia.exceptions import (
    CredentialsError,
    DecryptionError,
    EngramiaError,
    MasterKeyError,
)

# 32 bytes of test key — deterministic so failures reproduce
_TEST_KEY = bytes(range(32))
_TEST_AAD = b"tenant-abc:openai:llm"
_TEST_PLAINTEXT = "sk-test-1234567890ABCDEF"


@pytest.fixture
def cipher() -> AESGCMCipher:
    """Cipher built from a deterministic 32-byte key."""
    return AESGCMCipher(_TEST_KEY)


# ---------------------------------------------------------------------------
# Happy-path round trips
# ---------------------------------------------------------------------------


def test_round_trip_recovers_plaintext(cipher: AESGCMCipher) -> None:
    ciphertext, nonce, tag = cipher.encrypt(_TEST_PLAINTEXT, _TEST_AAD)
    plaintext = cipher.decrypt(ciphertext, nonce, tag, _TEST_AAD)
    assert plaintext == _TEST_PLAINTEXT


def test_round_trip_unicode_plaintext(cipher: AESGCMCipher) -> None:
    """Plaintexts can include non-ASCII characters (defensive — provider
    keys are ASCII today, but the cipher must not constrain that)."""
    secret = "ďábelský-klíč-🔑-sk-1234"
    ciphertext, nonce, tag = cipher.encrypt(secret, _TEST_AAD)
    assert cipher.decrypt(ciphertext, nonce, tag, _TEST_AAD) == secret


def test_round_trip_long_plaintext(cipher: AESGCMCipher) -> None:
    """Schema allows 512-char keys; ensure the cipher handles full size."""
    secret = "sk-" + "X" * 509  # 512 chars total
    ciphertext, nonce, tag = cipher.encrypt(secret, _TEST_AAD)
    assert cipher.decrypt(ciphertext, nonce, tag, _TEST_AAD) == secret


def test_each_encrypt_uses_fresh_nonce(cipher: AESGCMCipher) -> None:
    """Same plaintext must produce different ciphertexts on repeat calls
    (random nonce per encrypt). Reusing a nonce with the same key in GCM
    is a catastrophic failure — this test prevents an accidental
    deterministic-nonce regression."""
    ct1, nonce1, _ = cipher.encrypt(_TEST_PLAINTEXT, _TEST_AAD)
    ct2, nonce2, _ = cipher.encrypt(_TEST_PLAINTEXT, _TEST_AAD)
    assert nonce1 != nonce2
    assert ct1 != ct2


def test_encrypt_returns_canonical_lengths(cipher: AESGCMCipher) -> None:
    ciphertext, nonce, tag = cipher.encrypt(_TEST_PLAINTEXT, _TEST_AAD)
    assert len(nonce) == 12  # GCM standard
    assert len(tag) == 16  # GCM standard
    assert len(ciphertext) == len(_TEST_PLAINTEXT.encode("utf-8"))


# ---------------------------------------------------------------------------
# Tampering and AAD-mismatch detection
# ---------------------------------------------------------------------------


def test_aad_mismatch_raises_decryption_error(cipher: AESGCMCipher) -> None:
    """The row-substitution defence — encrypting with one AAD and decrypting
    with another (e.g. a row swapped between tenants) MUST fail."""
    ciphertext, nonce, tag = cipher.encrypt(_TEST_PLAINTEXT, _TEST_AAD)
    wrong_aad = b"tenant-DIFFERENT:openai:llm"
    with pytest.raises(DecryptionError):
        cipher.decrypt(ciphertext, nonce, tag, wrong_aad)


def test_tampered_ciphertext_raises_decryption_error(cipher: AESGCMCipher) -> None:
    ciphertext, nonce, tag = cipher.encrypt(_TEST_PLAINTEXT, _TEST_AAD)
    tampered = bytes([ciphertext[0] ^ 0x01]) + ciphertext[1:]
    with pytest.raises(DecryptionError):
        cipher.decrypt(tampered, nonce, tag, _TEST_AAD)


def test_tampered_nonce_raises_decryption_error(cipher: AESGCMCipher) -> None:
    ciphertext, nonce, tag = cipher.encrypt(_TEST_PLAINTEXT, _TEST_AAD)
    tampered_nonce = bytes([nonce[0] ^ 0x01]) + nonce[1:]
    with pytest.raises(DecryptionError):
        cipher.decrypt(ciphertext, tampered_nonce, tag, _TEST_AAD)


def test_tampered_tag_raises_decryption_error(cipher: AESGCMCipher) -> None:
    ciphertext, nonce, tag = cipher.encrypt(_TEST_PLAINTEXT, _TEST_AAD)
    tampered_tag = bytes([tag[0] ^ 0x01]) + tag[1:]
    with pytest.raises(DecryptionError):
        cipher.decrypt(ciphertext, nonce, tampered_tag, _TEST_AAD)


def test_wrong_master_key_raises_decryption_error() -> None:
    """A second cipher with a different master key MUST NOT decrypt
    a payload encrypted by the first."""
    cipher_a = AESGCMCipher(_TEST_KEY)
    cipher_b = AESGCMCipher(bytes(reversed(_TEST_KEY)))
    ciphertext, nonce, tag = cipher_a.encrypt(_TEST_PLAINTEXT, _TEST_AAD)
    with pytest.raises(DecryptionError):
        cipher_b.decrypt(ciphertext, nonce, tag, _TEST_AAD)


def test_decryption_error_message_does_not_leak_aad() -> None:
    """The exception message must not echo the AAD content — log inspectors
    don't need to see which (tenant, provider) tuple failed."""
    cipher = AESGCMCipher(_TEST_KEY)
    ciphertext, nonce, tag = cipher.encrypt(_TEST_PLAINTEXT, _TEST_AAD)
    secret_aad = b"tenant-LEAKED:openai:llm"
    try:
        cipher.decrypt(ciphertext, nonce, tag, secret_aad)
    except DecryptionError as exc:
        assert b"LEAKED" not in str(exc).encode()
        assert b"tenant-LEAKED" not in str(exc).encode()
    else:
        pytest.fail("expected DecryptionError")


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_master_key_wrong_length_raises_master_key_error() -> None:
    with pytest.raises(MasterKeyError, match="32 bytes"):
        AESGCMCipher(b"short")


def test_master_key_must_be_bytes() -> None:
    with pytest.raises(MasterKeyError, match="must be bytes"):
        AESGCMCipher("not-bytes-but-string")  # type: ignore[arg-type]


def test_key_version_must_be_positive() -> None:
    with pytest.raises(MasterKeyError, match="key_version"):
        AESGCMCipher(_TEST_KEY, key_version=0)


def test_encrypt_rejects_empty_plaintext(cipher: AESGCMCipher) -> None:
    with pytest.raises(ValueError, match="plaintext must be non-empty"):
        cipher.encrypt("", _TEST_AAD)


def test_encrypt_rejects_empty_aad(cipher: AESGCMCipher) -> None:
    with pytest.raises(ValueError, match="aad must be non-empty"):
        cipher.encrypt(_TEST_PLAINTEXT, b"")


def test_decrypt_rejects_wrong_nonce_length(cipher: AESGCMCipher) -> None:
    ciphertext, _, tag = cipher.encrypt(_TEST_PLAINTEXT, _TEST_AAD)
    with pytest.raises(ValueError, match="nonce must be 12 bytes"):
        cipher.decrypt(ciphertext, b"too-short", tag, _TEST_AAD)


def test_decrypt_rejects_wrong_tag_length(cipher: AESGCMCipher) -> None:
    ciphertext, nonce, _ = cipher.encrypt(_TEST_PLAINTEXT, _TEST_AAD)
    with pytest.raises(ValueError, match="auth_tag must be 16 bytes"):
        cipher.decrypt(ciphertext, nonce, b"too-short", _TEST_AAD)


def test_decrypt_rejects_empty_aad(cipher: AESGCMCipher) -> None:
    ciphertext, nonce, tag = cipher.encrypt(_TEST_PLAINTEXT, _TEST_AAD)
    with pytest.raises(ValueError, match="aad must be non-empty"):
        cipher.decrypt(ciphertext, nonce, tag, b"")


# ---------------------------------------------------------------------------
# Environment loading
# ---------------------------------------------------------------------------


def test_from_env_loads_valid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    key_b64 = base64.b64encode(_TEST_KEY).decode("ascii")
    monkeypatch.setenv("ENGRAMIA_CREDENTIALS_KEY", key_b64)
    cipher = AESGCMCipher.from_env()
    # Verify it works end-to-end with the loaded key
    ciphertext, nonce, tag = cipher.encrypt(_TEST_PLAINTEXT, _TEST_AAD)
    assert cipher.decrypt(ciphertext, nonce, tag, _TEST_AAD) == _TEST_PLAINTEXT


def test_from_env_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    key_b64 = base64.b64encode(_TEST_KEY).decode("ascii")
    monkeypatch.setenv("ENGRAMIA_CREDENTIALS_KEY", f"  {key_b64}  \n")
    AESGCMCipher.from_env()  # MUST not raise


def test_from_env_missing_raises_master_key_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENGRAMIA_CREDENTIALS_KEY", raising=False)
    with pytest.raises(MasterKeyError, match="ENGRAMIA_CREDENTIALS_KEY is not set"):
        AESGCMCipher.from_env()


def test_from_env_empty_raises_master_key_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGRAMIA_CREDENTIALS_KEY", "   ")
    with pytest.raises(MasterKeyError, match="is not set"):
        AESGCMCipher.from_env()


def test_from_env_invalid_base64_raises_master_key_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGRAMIA_CREDENTIALS_KEY", "not!valid!base64!@#$")
    with pytest.raises(MasterKeyError, match="not valid base64"):
        AESGCMCipher.from_env()


def test_from_env_wrong_length_after_decode_raises_master_key_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    short_key = base64.b64encode(b"only-16-bytes!!!!").decode("ascii")
    monkeypatch.setenv("ENGRAMIA_CREDENTIALS_KEY", short_key)
    with pytest.raises(MasterKeyError, match="32 bytes"):
        AESGCMCipher.from_env()


# ---------------------------------------------------------------------------
# Master key generation helper
# ---------------------------------------------------------------------------


def test_generate_master_key_decodes_to_32_bytes() -> None:
    key_b64 = generate_master_key()
    decoded = base64.b64decode(key_b64)
    assert len(decoded) == 32


def test_generate_master_key_is_unique_per_call() -> None:
    """Cryptographic entropy check — two consecutive calls MUST produce
    different keys, else the underlying RNG is broken."""
    keys = {generate_master_key() for _ in range(20)}
    assert len(keys) == 20


def test_generated_key_is_usable_by_cipher() -> None:
    """Round-trip from generator through env loading."""
    os.environ["ENGRAMIA_CREDENTIALS_KEY"] = generate_master_key()
    try:
        cipher = AESGCMCipher.from_env()
        ct, nonce, tag = cipher.encrypt(_TEST_PLAINTEXT, _TEST_AAD)
        assert cipher.decrypt(ct, nonce, tag, _TEST_AAD) == _TEST_PLAINTEXT
    finally:
        os.environ.pop("ENGRAMIA_CREDENTIALS_KEY", None)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_master_key_error_is_credentials_error() -> None:
    assert issubclass(MasterKeyError, CredentialsError)
    assert issubclass(MasterKeyError, EngramiaError)


def test_decryption_error_is_credentials_error() -> None:
    assert issubclass(DecryptionError, CredentialsError)
    assert issubclass(DecryptionError, EngramiaError)


# ---------------------------------------------------------------------------
# Key versioning
# ---------------------------------------------------------------------------


def test_key_version_default_is_one(cipher: AESGCMCipher) -> None:
    assert cipher.key_version == 1


def test_key_version_can_be_set_for_rotation() -> None:
    cipher = AESGCMCipher(_TEST_KEY, key_version=2)
    assert cipher.key_version == 2
    # The cipher itself does not consult key_version at encrypt/decrypt;
    # the resolver pairs the value with stored rows during rotation sweeps.
    ct, nonce, tag = cipher.encrypt(_TEST_PLAINTEXT, _TEST_AAD)
    assert cipher.decrypt(ct, nonce, tag, _TEST_AAD) == _TEST_PLAINTEXT

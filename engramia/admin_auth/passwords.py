# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Bcrypt password hashing for admin accounts.

Thin wrapper. We use bcrypt (already pinned via the ``cloud-auth`` extra)
rather than introducing argon2-cffi as a second hash family — one less
dependency to audit and rotate, and bcrypt is sufficient for a
single-digit number of admin accounts.
"""

from __future__ import annotations

import bcrypt

# Cost factor 12 is the OWASP-recommended floor for 2024+ hardware. Admin
# logins are rare (single human, occasional sessions) so we accept the
# ~250 ms hash cost in exchange for ~4096× brute-force resistance vs
# the bcrypt default of 10.
_BCRYPT_ROUNDS = 12


def hash_password(plaintext: str) -> str:
    """Return a bcrypt hash of *plaintext* as a UTF-8 string suitable for DB storage."""
    if not plaintext:
        raise ValueError("password must be non-empty")
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(plaintext.encode("utf-8"), salt).decode("utf-8")


def verify_password(plaintext: str, stored_hash: str) -> bool:
    """Return True if *plaintext* matches *stored_hash*. Constant-time."""
    if not plaintext or not stored_hash:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), stored_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash — treat as failure rather than crashing the request.
        return False

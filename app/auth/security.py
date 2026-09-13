"""Password hashing and session tokens.

Stdlib-only (hashlib + secrets): the project has no password-hashing
dependency yet, and PBKDF2-HMAC-SHA256 needs none to be done safely.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_PBKDF2_ALGORITHM = "sha256"
_PBKDF2_ITERATIONS = 600_000  # OWASP 2023 minimum for PBKDF2-HMAC-SHA256.
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Hash a password as `pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGORITHM, password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    """Check a password against a hash produced by `hash_password`."""
    try:
        algorithm, iterations_raw, salt_hex, digest_hex = encoded_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError, AttributeError:
        return False

    candidate = hashlib.pbkdf2_hmac(_PBKDF2_ALGORITHM, password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


def generate_session_token() -> str:
    """An opaque, URL-safe token to hand the browser as the session cookie's value."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """One-way hash of a session token, so the stored value is useless if the table leaks."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

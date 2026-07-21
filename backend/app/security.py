"""Password hashing with the stdlib only (PBKDF2-HMAC-SHA256) — no extra dependency.

Stored format: `pbkdf2_sha256$<iterations>$<salt_hex>$<derived_hex>`.
For a higher-security deployment swap this for argon2/bcrypt via passlib.
"""

import hashlib
import secrets

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, digest = stored.split("$")
        if algo != _ALGO:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return secrets.compare_digest(dk.hex(), digest)
    except (ValueError, AttributeError):
        return False

"""Password hashing with Argon2id and transparent PBKDF2 legacy verification."""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 200_000
_ARGON2 = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def hash_password(password: str) -> str:
    return _ARGON2.hash(password)


def _hash_password_legacy(password: str) -> str:
    """Only for regression tests and verification of rows issued before migration."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if stored.startswith("$argon2"):
        try:
            return _ARGON2.verify(stored, password)
        except (VerifyMismatchError, InvalidHashError):
            return False
    try:
        algo, iterations, salt, digest = stored.split("$")
        if algo != _ALGO:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return secrets.compare_digest(dk.hex(), digest)
    except (ValueError, AttributeError):
        return False


def password_needs_rehash(stored: str) -> bool:
    if not stored.startswith("$argon2"):
        return True
    try:
        return _ARGON2.check_needs_rehash(stored)
    except InvalidHashError:
        return True

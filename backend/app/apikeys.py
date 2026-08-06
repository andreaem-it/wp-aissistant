"""Server-side API key vocabulary and minting.

The scopes and the key format are shared between the management endpoints (which create keys)
and the public `/v1` surface (which checks them), so they live here rather than in either
caller — the two must never disagree on what a scope is called.
"""
import secrets

from .db import ApiKey

# The closed set of scopes a key can be granted. A key is useless outside this list, and an
# unknown scope is rejected at creation rather than silently ignored.
API_SCOPES = (
    "conversations:read",
    "conversations:write",
    "knowledge:write",
    "stats:read",
    "channels:write",
)

API_KEY_PREFIX = "wpa"


def scopes_of(key: ApiKey) -> list[str]:
    return [s for s in (key.scopes or "").split(",") if s]


def generate() -> tuple[str, str]:
    """Returns (full token, public prefix). The full token is shown once and never stored."""
    prefix = f"{API_KEY_PREFIX}_{secrets.token_hex(4)}"
    return f"{prefix}_{secrets.token_urlsafe(32)}", prefix

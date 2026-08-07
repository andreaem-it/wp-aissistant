"""Small format and bounds helpers shared across areas.

Deliberately trivial and domain-free: anything that knows what a conversation, a plan or a
webhook *is* belongs to its own module, not here. This exists so a router does not have to
import `main.py` for a one-line utility.
"""
import re
from datetime import datetime


def iso(value: datetime | None) -> str | None:
    """UTC timestamps go out with an explicit Z: a naive string invites the client to guess."""
    return value.isoformat() + "Z" if value else None


def bounded_limit(value: int, *, default: int = 100, maximum: int = 500) -> int:
    """Clamp a caller-supplied page size, so a missing or absurd value cannot scan a table."""
    return min(max(value or default, 1), maximum)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return s or "campo"

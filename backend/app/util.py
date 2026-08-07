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


def split_origins(raw: str) -> list[str]:
    return [o.strip() for o in (raw or "").split(",") if o.strip()]


def normalize_origins(raw: str) -> str:
    """Reduce each comma-separated entry to a browser Origin (scheme://host[:port]), dropping
    any path/query/fragment. A browser's Origin header never includes a path, so a value like
    'https://site.it/shop' could never match and would silently 403 the widget. Tolerates a
    missing scheme; leaves an unparseable entry as-is."""
    from urllib.parse import urlparse

    out: list[str] = []
    for entry in split_origins(raw):
        parsed = urlparse(entry if "//" in entry else "//" + entry)
        if parsed.scheme and parsed.netloc:
            normalized = f"{parsed.scheme}://{parsed.netloc}"
        elif parsed.netloc:
            normalized = parsed.netloc  # host only (no scheme given)
        else:
            normalized = entry
        if normalized not in out:
            out.append(normalized)
    return ",".join(out)

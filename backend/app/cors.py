"""Dynamic CORS allowlist.

A preflight carries no api_key, so the browser layer cannot be scoped per client. Instead an
Origin is reflected only if it is in a dynamic allowlist — the panel origins plus every client's
configured widget origins. The enforceable key/site binding lives in the chat rate limiter, which
does see the key.

The module keeps the state so `main.py` and the routers that change origins share one allowlist;
read it through the module (`cors.is_allowed(...)`), never by importing the values, or a rebuild
would not be visible to the caller.
"""
import os

from sqlmodel import Session, select

from .db import ClientOrigin

CORS_ALLOW_ALL = os.getenv("CORS_ALLOW_ALL", "true").lower() == "true"
PANEL_ORIGINS = [o.strip() for o in os.getenv("PANEL_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
_ALLOWED_ORIGINS: set[str] = set(PANEL_ORIGINS)


def rebuild_allowed_origins(session: Session) -> None:
    """Recompute the browser-layer allowlist: panel origins + every client's widget origins.

    La sorgente sono le righe `ClientOrigin` confermate (`live`/`staging`), non più la colonna
    di testo `Client.allowed_origins`: quella resta solo come specchio per il pannello admin.
    Le righe `observed` **non** entrano — sono una traccia di traffico, non un permesso.
    """
    origins = set(PANEL_ORIGINS)
    for row in session.exec(
        select(ClientOrigin).where(ClientOrigin.kind.in_(("live", "staging")))
    ).all():
        if row.origin:
            origins.add(row.origin)
    global _ALLOWED_ORIGINS
    _ALLOWED_ORIGINS = origins


def is_allowed(origin: str | None) -> bool:
    return bool(origin) and (CORS_ALLOW_ALL or origin in _ALLOWED_ORIGINS)


def headers(origin: str) -> dict:
    # Every method the app actually routes must be listed, or the browser blocks the request
    # before it is ever sent: the panel updates settings with PUT and removes rows with DELETE,
    # and omitting them made 36 routes unreachable cross-origin while the server looked healthy.
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Conversation-Token, ngrok-skip-browser-warning",
        "Access-Control-Max-Age": "600",
        "Vary": "Origin",
    }

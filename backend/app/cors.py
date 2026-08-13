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
            origins.update(_with_www_variant(row.origin))
    global _ALLOWED_ORIGINS
    _ALLOWED_ORIGINS = origins


def _with_www_variant(origin: str) -> set[str]:
    """L'Origin registrato e la sua forma con o senza `www.`.

    Il controllo della licenza considera già `esempio.it` e `www.esempio.it` **lo stesso sito**:
    `origins.host_of()` toglie il `www.` proprio perché devono costare uno slot solo. Qui invece
    si confrontava la stringa esatta, e le due metà della stessa regola non erano d'accordo.

    L'effetto era invisibile da server e fatale da browser: un cliente registra `esempio.it`, un
    visitatore arriva su `www.esempio.it`, e il preflight della chat riceve `403`. Nessun errore
    nei nostri log che dica «licenza» — il rifiuto arriva dal livello CORS, prima — e il cliente
    vede solo una chat che non risponde su metà del suo traffico. Ce l'avevamo sul nostro sito.

    Solo `www.`, non un sottodominio qualunque: `www` è convenzione universale per «lo stesso
    sito», `app.esempio.it` no, e trattarli allo stesso modo regalerebbe domini a chi ne ha
    pagato uno.
    """
    raw = (origin or "").strip()
    if not raw:
        return set()
    scheme, _, rest = raw.partition("://")
    if not rest:
        return {raw}
    if rest.startswith("www."):
        return {raw, f"{scheme}://{rest[4:]}"}
    return {raw, f"{scheme}://www.{rest}"}


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
        # `X-Panel-Assistant-Token` porta il contesto del tenant loggato quando l'assistente gira
        # dentro il pannello: è un header e non un campo del body perché `/chat` e `/chat/stream`
        # hanno corpi diversi, e perché un header non finisce nella trascrizione del messaggio.
        # Ometterlo qui rende la funzione irraggiungibile dal browser con il server che sta bene.
        "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Conversation-Token, X-Panel-Assistant-Token, ngrok-skip-browser-warning",
        "Access-Control-Max-Age": "600",
        "Vary": "Origin",
    }

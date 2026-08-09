"""Quali siti copre una licenza, e come un `Origin` del browser vi si confronta.

Un dominio **live** per licenza (il piano può concederne di più), un dominio di **staging**, e
un numero qualsiasi di host **locali**, che non consumano mai uno slot.

Le regole stanno qui — non in un router e non nel pannello — perché tre punti diversi devono
essere d'accordo: il percorso che applica il vincolo, l'endpoint che registra un dominio e
l'osservazione che annota quello che vediamo passare. Il vocabolario delle etichette di sviluppo
è **chiuso e validato al salvataggio**, come i vocabolari di `workflows.py`: un dominio che non
rientra viene rifiutato con una spiegazione, mai accettato a metà.

Il vincolo che rende utile lo slot di staging non è la parola chiave: è che il dominio sia
**sotto il dominio live**. `demo.altrosito.it` rispetta la convenzione ed è un secondo sito
commerciale a tutti gli effetti — con la sola parola chiave lo slot sarebbe una licenza in
regalo. La deroga alle piattaforme di sviluppo esiste perché molte agenzie ospitano lo staging
altrove, e senza di essa rifiuteremmo installazioni oneste.
"""
import logging
from datetime import datetime
from urllib.parse import urlparse

from sqlmodel import Session, select

from .db import ClientOrigin
from .metrics import widget_origin_checks_total

logger = logging.getLogger("wpai")

# Etichette DNS che marcano un ambiente non di produzione. Vocabolario chiuso.
STAGING_LABELS = frozenset({
    "staging", "stage", "dev", "develop", "development", "demo", "test", "testing",
    "preprod", "preproduction", "preview", "uat", "qa", "sandbox", "beta",
})

# Host senza valore commerciale: sempre ammessi, mai contati. Negarli non protegge nulla e
# rompe l'ambiente di sviluppo di ogni cliente.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"})
LOCAL_SUFFIXES = (".localhost", ".local", ".test", ".localdomain")

# Suffissi di piattaforme che ospitano ambienti di prova per conto di altri: qui lo staging non
# può essere un sottodominio del live, perché il nome del sito non è sotto il controllo del
# cliente. Lista chiusa e mantenuta da noi: allargarla è una decisione, non un caso.
DEV_PLATFORM_SUFFIXES = (
    ".wpengine.com", ".pantheonsite.io", ".kinsta.cloud", ".wpenginepowered.com",
    ".vercel.app", ".netlify.app", ".pages.dev", ".workers.dev",
    ".ngrok.io", ".ngrok-free.app", ".ddev.site", ".lndo.site", ".myshopify.com",
)


def host_of(origin: str) -> str:
    """L'host confrontabile di un Origin: minuscolo, senza schema, senza porta, senza `www.`.

    La porta cade perché `esempio.it:8080` è lo stesso sito di `esempio.it`, e `www.` perché
    `www.esempio.it` ed `esempio.it` sono lo stesso sito e devono costare **uno** slot solo.
    """
    raw = (origin or "").strip().lower()
    if not raw:
        return ""
    parsed = urlparse(raw if "//" in raw else "//" + raw)
    host = parsed.hostname or parsed.path.split("/")[0]
    host = (host or "").strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def labels(origin: str) -> list[str]:
    host = host_of(origin)
    return host.split(".") if host else []


def is_local(origin: str) -> bool:
    host = host_of(origin)
    if not host:
        return False
    return host in LOCAL_HOSTS or host.endswith(LOCAL_SUFFIXES)


def is_dev_platform(origin: str) -> bool:
    host = host_of(origin)
    return bool(host) and host.endswith(DEV_PLATFORM_SUFFIXES)


def has_staging_label(origin: str) -> bool:
    """Vero se una **etichetta DNS** del nome è nel vocabolario.

    Il confronto è per etichetta e mai per sottostringa: `devoto.it` e `demolizioni.it`
    contengono "dev" e "demo" senza essere ambienti di sviluppo, e una regola scritta con `in`
    regalerebbe lo slot a chiunque abbia un dominio che comincia così — senza che nessuno se ne
    accorga. Vale qualunque etichetta, non solo la prima: `shop.staging.esempio.it` è valido.
    """
    return any(label in STAGING_LABELS for label in labels(origin))


def is_subdomain_of(origin: str, parent: str) -> bool:
    host, root = host_of(origin), host_of(parent)
    return bool(host and root) and host.endswith("." + root)


def same_site(a: str, b: str) -> bool:
    """Due Origin sono lo stesso sito se lo sono i loro host confrontabili.

    Lo schema non entra: `http://esempio.it` e `https://esempio.it` sono un sito solo. In
    produzione si registra comunque `https` — ma un confronto che distinguesse i due schemi
    rifiuterebbe il traffico di un sito che redirige, senza dire perché.
    """
    return bool(host_of(a)) and host_of(a) == host_of(b)


def staging_rejection(origin: str, live_origin: str) -> str | None:
    """Perché questo dominio non può occupare lo slot di staging, o `None` se può.

    Restituisce il motivo invece di un booleano perché il messaggio arriva fino al cliente nel
    configuratore: "non valido" lo lascia a indovinare, e indovinare male costa un ticket.
    """
    host = host_of(origin)
    if not host:
        return "Il dominio di staging non è un indirizzo valido."
    if is_local(origin):
        return (
            "Gli indirizzi locali non vanno registrati: sono sempre ammessi e non occupano lo "
            "slot di staging."
        )
    if live_origin and same_site(origin, live_origin):
        return "Il dominio di staging deve essere diverso dal dominio live."
    if is_dev_platform(origin):
        return None
    if not live_origin:
        return "Registra prima il dominio live: lo staging deve stare sotto di esso."
    if not is_subdomain_of(origin, live_origin):
        return (
            f"Il dominio di staging deve essere un sottodominio di {host_of(live_origin)} "
            f"(per esempio staging.{host_of(live_origin)}) oppure stare su una piattaforma di "
            f"sviluppo riconosciuta."
        )
    if not has_staging_label(origin):
        return (
            "Il sottodominio di staging deve contenere una parola che lo identifichi come "
            "ambiente di prova: " + ", ".join(sorted(STAGING_LABELS)) + "."
        )
    return None


def covered(origin: str, registered: list[str]) -> bool:
    """Se questo Origin è coperto dalla licenza: locale, oppure uno dei domini registrati.

    Non decide **se** applicare il vincolo — quello è del chiamante, e finché siamo in
    osservazione non lo applica nessuno.
    """
    if is_local(origin):
        return True
    return any(same_site(origin, entry) for entry in registered)


# ---- Osservazione ----------------------------------------------------------------------------
#
# Annota da quali domini una licenza viene davvero usata, **senza rifiutare niente**. Serve a
# rendere applicabile il vincolo sapendo chi si romperebbe, invece di scoprirlo dai clienti.
#
# Una nota che vale più dei numeri: in produzione `CORS_ALLOW_ALL` è `false` (verificato con un
# preflight sul backend live, che risponde `403` a un Origin sconosciuto). Quindi il traffico di
# un browser da un dominio non in allowlist **non arriva nemmeno qui**: il preflight lo ferma
# prima. Ciò che osserviamo sono i domini già ammessi, più — ed è la parte che conta — le
# chiamate **senza header Origin**, che nessun browser produce e su cui il binding per-cliente
# oggi non si applica affatto.

_OBSERVE_THROTTLE_SECONDS = 600
_MAX_TRACKED_PAIRS = 5000
_last_observed: dict[tuple[int, str], datetime] = {}


def observe(session: Session, client_id: int, origin: str | None, registered: list[str]) -> None:
    """Registra la copertura di questa chiamata. Non solleva mai: un'osservazione che rompe una
    chat è peggio del buco che sta misurando."""
    try:
        if not origin:
            widget_origin_checks_total.labels(result="missing_origin").inc()
            # Senza Origin non c'è nessun dominio da annotare, e non è un browser. Va nel log
            # strutturato perché è l'unico segnale di uso server-side di una chiave pubblica.
            logger.info("widget call without origin", extra={"client_id": client_id})
            return

        widget_origin_checks_total.labels(
            result="covered" if covered(origin, registered) else "uncovered"
        ).inc()

        host = host_of(origin)
        if not host or is_local(origin):
            return  # i locali non occupano slot e non vanno annotati

        key = (client_id, host)
        now = datetime.utcnow()
        last = _last_observed.get(key)
        if last and (now - last).total_seconds() < _OBSERVE_THROTTLE_SECONDS:
            return
        if len(_last_observed) >= _MAX_TRACKED_PAIRS:
            _last_observed.clear()  # tetto: una pioggia di Origin falsi non deve crescere senza fine
        _last_observed[key] = now

        # In una transazione annidata: un conflitto sull'unicità fra due processi non deve
        # trascinarsi dietro la richiesta di chat dentro cui questa funzione gira.
        with session.begin_nested():
            row = session.exec(
                select(ClientOrigin).where(
                    ClientOrigin.client_id == client_id, ClientOrigin.host == host
                )
            ).first()
            if row:
                row.last_seen_at = now
                session.add(row)
            else:
                session.add(ClientOrigin(
                    client_id=client_id,
                    origin=(origin or "").strip(),
                    host=host,
                    kind="observed",
                    source="traffic",
                    first_seen_at=now,
                    last_seen_at=now,
                ))
    except Exception:  # noqa: BLE001 — vedi docstring
        logger.warning("origin observation failed", exc_info=True)

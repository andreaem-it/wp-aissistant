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
import os
from datetime import datetime, timedelta
from urllib.parse import urlparse

from sqlmodel import Session, select

from .db import Client, ClientOrigin, Plan
from .metrics import widget_origin_checks_total
from .util import normalize_origins as _normalize_origins

logger = logging.getLogger("wpai")

KINDS = ("live", "staging")

# Quanti domini di staging: uno, e non dipende dal piano. Chi ne vuole due ha due siti.
MAX_STAGING_ORIGINS = 1

# Cambiare il dominio live è normale — rebrand, migrazioni, il passaggio da staging a live il
# giorno del lancio — quindi si fa da soli. Il raffreddamento serve a rendere scomodo il solo uso
# che vogliamo scoraggiare, ruotare la stessa licenza fra siti diversi; la cronologia in audit è
# comunque il deterrente vero. Il superadmin non ne è soggetto: deve poter sbloccare un cliente.
LIVE_CHANGE_COOLDOWN = timedelta(days=int(os.getenv("LIVE_ORIGIN_CHANGE_COOLDOWN_DAYS", "7")))

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


# ---- La sorgente di verità -------------------------------------------------------------------
#
# Le decisioni leggono **queste** funzioni, mai `Client.allowed_origins`. Quella colonna
# sopravvive solo come specchio per il pannello admin, scritta da `_mirror()` qui sotto e da
# nessun altro: due sorgenti che si possono contraddire sono il modo in cui un cliente configura
# quella sbagliata e il supporto guarda l'altra.


def registered_rows(session: Session, client_id: int) -> list[ClientOrigin]:
    """I domini che concedono qualcosa: `live` e `staging`. Gli `observed` non sono un permesso."""
    return list(session.exec(
        select(ClientOrigin)
        .where(ClientOrigin.client_id == client_id, ClientOrigin.kind.in_(KINDS))
        .order_by(ClientOrigin.kind, ClientOrigin.id)
    ).all())


def registered(session: Session, client_id: int) -> list[str]:
    return [row.origin for row in registered_rows(session, client_id) if row.origin]


def live_origin(session: Session, client_id: int) -> str:
    rows = [r for r in registered_rows(session, client_id) if r.kind == "live"]
    return rows[0].origin if rows else ""


def _mirror(session: Session, client_id: int) -> None:
    """Riallinea lo specchio `Client.allowed_origins`. Deprecato: si toglie quando il pannello
    admin userà gli endpoint nuovi."""
    client = session.get(Client, client_id)
    if client:
        client.allowed_origins = ",".join(registered(session, client_id))
        session.add(client)


def max_live_origins(session: Session, client: Client) -> int:
    plan = session.get(Plan, client.plan_id) if client.plan_id else None
    return plan.max_live_origins if plan else 1


def slots(session: Session, client: Client) -> dict:
    """Quanti siti concede la licenza e quanti ne restano: è ciò che il pannello mostra accanto
    al campo, perché "slot esauriti" senza un numero non dice al cliente cosa fare."""
    rows = registered_rows(session, client.id)
    limit = max_live_origins(session, client)
    used = len([r for r in rows if r.kind == "live"])
    return {
        "live_used": used,
        "live_limit": limit,  # 0 = illimitato
        "live_available": None if limit == 0 else max(0, limit - used),
        "staging_used": len([r for r in rows if r.kind == "staging"]),
        "staging_limit": MAX_STAGING_ORIGINS,
    }


class OriginError(ValueError):
    """Un dominio rifiutato, con il motivo che arriva fino al cliente."""


def register(session: Session, client: Client, value: str, kind: str, *,
             source: str = "panel", enforce_cooldown: bool = True) -> ClientOrigin:
    """Registra un dominio del tenant. Solleva `OriginError` con il motivo, mai un booleano.

    Non fa commit: chi chiama decide la transazione, così la registrazione e la sua riga di audit
    stanno o cadono insieme.
    """
    if kind not in KINDS:
        raise OriginError("Il tipo di dominio deve essere 'live' o 'staging'.")

    origin = _normalize_origins(str(value or "").strip())
    host = host_of(origin)
    # I locali si riconoscono prima della forma: `localhost` non ha un punto e sarebbe scartato
    # come indirizzo malformato, dicendo la cosa sbagliata a chi sta solo sviluppando.
    if is_local(origin):
        raise OriginError(
            "Gli indirizzi locali funzionano sempre e non vanno registrati: non occupano slot."
        )
    if not host or "." not in host:
        raise OriginError("Inserisci un dominio valido, per esempio https://esempio.it.")

    rows = registered_rows(session, client.id)
    existing = next((r for r in rows if r.host == host), None)
    if existing and existing.kind == kind:
        return existing  # già registrato: idempotente, non un errore

    if kind == "staging":
        reason = staging_rejection(origin, live_origin(session, client.id))
        if reason:
            raise OriginError(reason)
        if len([r for r in rows if r.kind == "staging" and r.host != host]) >= MAX_STAGING_ORIGINS:
            raise OriginError(
                "Hai già un dominio di staging. Rimuovilo prima di registrarne un altro: la "
                "licenza ne prevede uno."
            )
    else:
        current = [r for r in rows if r.kind == "live" and r.host != host]
        limit = max_live_origins(session, client)
        if limit and len(current) >= limit:
            if limit == 1 and enforce_cooldown:
                _check_live_cooldown(current[0])
            elif limit > 1:
                raise OriginError(
                    f"Il tuo piano copre {limit} domini di produzione e li hai già usati tutti. "
                    f"Rimuovine uno o passa a un piano superiore."
                )
            # Un solo slot: il dominio nuovo sostituisce quello vecchio, che sparisce dalla
            # licenza. È il caso normale — rebrand, migrazione, passaggio da staging a live.
            for row in current:
                session.delete(row)

    now = datetime.utcnow()
    if existing:
        existing.kind = kind
        existing.origin = origin
        existing.source = source
        existing.confirmed_at = now
        existing.last_seen_at = now
        session.add(existing)
        row = existing
    else:
        row = ClientOrigin(client_id=client.id, origin=origin, host=host, kind=kind,
                           source=source, first_seen_at=now, last_seen_at=now, confirmed_at=now)
        session.add(row)
    session.flush()
    _mirror(session, client.id)
    return row


def _check_live_cooldown(current: ClientOrigin) -> None:
    since = current.confirmed_at or current.first_seen_at
    if not since or not LIVE_CHANGE_COOLDOWN:
        return
    ready = since + LIVE_CHANGE_COOLDOWN
    if datetime.utcnow() < ready:
        raise OriginError(
            f"Hai cambiato il dominio di produzione da poco. Potrai cambiarlo di nuovo dal "
            f"{ready.strftime('%d/%m/%Y')}. Se serve prima, scrivici."
        )


def assign(session: Session, client: Client, values: list[str], *, source: str) -> list[str]:
    """Registra un elenco di domini scegliendo il tipo da sé: **live finché il piano lo
    consente**, poi staging.

    Sostituisce la convenzione «il primo è live, tutti gli altri sono staging», che descriveva
    bene un piano da un sito solo e mentiva su ogni altro. Il caso che l'ha fatta cadere:
    `wpaissistant.it` e `panel.wpaissistant.it` sono due siti di produzione, non un sito e il suo
    staging — `panel` non è un'etichetta di sviluppo, e la validazione lo rifiutava giustamente.

    Non scavalca la validazione: un dominio che il cliente non potrebbe registrare da sé non deve
    poter entrare da questa porta, o l'assistenza diventerebbe il modo di aggirare la licenza.
    """
    saved: list[str] = []
    for value in values:
        slot = slots(session, client)
        limit = slot["live_limit"]
        kind = "live" if (limit == 0 or slot["live_used"] < limit) else "staging"
        saved.append(register(session, client, value, kind, source=source,
                              enforce_cooldown=False).origin)
    return saved


def remove(session: Session, client_id: int, origin_id: int) -> bool:
    row = session.get(ClientOrigin, origin_id)
    if row is None or row.client_id != client_id:
        return False  # tenant-scoped: la risorsa di un altro tenant non esiste, non è vietata
    session.delete(row)
    session.flush()
    _mirror(session, client_id)
    return True


def covered(origin: str, registered: list[str]) -> bool:
    """Se questo Origin è coperto dalla licenza: locale, oppure uno dei domini registrati."""
    if is_local(origin):
        return True
    return any(same_site(origin, entry) for entry in registered)


def licence_rejection(origin: str | None, registered: list[str]) -> str | None:
    """Perché questa chiamata del widget non è coperta dalla licenza, o `None` se lo è.

    Due rifiuti che prima non c'erano, ed è il senso del blocco:

    - **Nessun dominio registrato → si rifiuta.** Prima l'assenza di configurazione disattivava
      il controllo: una licenza senza domini valeva ovunque. Ora vale da nessuna parte finché il
      cliente non dice dov'è il suo sito.
    - **Nessun header `Origin` → si rifiuta.** Un browser lo manda sempre; una richiesta che non
      ce l'ha non viene da una pagina web, e su di essa il vincolo per-dominio non può applicarsi
      affatto. Era il varco che restava intero, ed è il modo realistico di usare una chiave
      pubblica copiata da un sito. Chi integra da un server ha `/v1` con una `ApiKey` dotata di
      scope, che è la porta giusta.

    Il messaggio è esplicito perché arriva a chi installa, in console e nel pannello. Al
    visitatore non arriva mai: il widget non mostra errori di licenza a chi sta scrivendo.
    """
    if not origin:
        return (
            "Questa chiamata non arriva da un browser: manca l'header Origin. Per un'integrazione "
            "server-to-server usa l'API /v1 con una chiave dedicata."
        )
    if is_local(origin):
        return None
    if not registered:
        return (
            "Nessun dominio registrato per questa licenza: aggiungi il dominio del tuo sito "
            "dalle impostazioni del pannello, poi ricarica la pagina."
        )
    if not covered(origin, registered):
        return (
            f"Il dominio {host_of(origin)} non è registrato per questa licenza. Aggiungilo dalle "
            f"impostazioni del pannello, oppure usa il dominio già configurato."
        )
    return None


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

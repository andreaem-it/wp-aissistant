"""L'assistente dentro il pannello del cliente: firma del contesto e whitelist dei campi.

Qui ci sono **due tenant nella stessa conversazione**, ed è il punto in cui si sbaglia:

- *chi risponde* siamo noi — il widget nel pannello usa la nostra `api_key` pubblica e la nostra
  knowledge base, esattamente come sul nostro sito;
- *di chi si parla* è il cliente loggato, che non è il chiamante ma **il soggetto** della domanda
  («perché il widget non compare sul mio sito?»).

Il secondo non può arrivare dal browser. La `api_key` del widget sta in chiaro dentro ogni pagina
del pannello: se il `client_id` viaggiasse come parametro, chiunque potrebbe chiedere il contesto
di un altro tenant cambiando un numero. Arriva invece dentro un token HMAC di 5 minuti firmato con
un segreto **server-only**, emesso solo dietro una sessione operatore valida — lo stesso schema di
`wpai_user_token` nel plugin, che quel commento spiega per esteso e che è già in produzione.

Due regole che questo modulo esiste per applicare:

1. **Firmare non è cifrare.** Il payload è leggibile: contiene `client_id` e `operator_id`, non
   dati del cliente. La firma dice «questo l'ho emesso io e non è stato modificato», e il
   contenuto vero viene **riletto dal database** al momento dell'uso. Un token non è mai la
   fonte dei fatti che finiscono nel prompt.
2. **Il contesto è una whitelist, non un dump.** Quello che serve per rispondere alle domande per
   cui l'assistente esiste — stato dell'abbonamento, se la knowledge base è popolata, se il sito
   è registrato, quante conversazioni aspettano — e niente altro. Fuori restano i contenuti delle
   conversazioni, i dati dei contatti e ogni chiave. La differenza non è di quantità: un dump
   mette nel prompt di un modello dati che nessuno ha chiesto, e il prompt finisce nei log.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime

from sqlmodel import Session, func, select

from .db import Chunk, Client, ClientOrigin, Conversation, IngestJob, Plan, PluginInstallation

# Durata volutamente corta: il token serve ad aprire una conversazione, non a tenerla aperta. Il
# pannello ne chiede uno nuovo quando serve, che costa una richiesta autenticata e niente altro.
TOKEN_TTL_SECONDS = 300

# Segreto **solo server**. Non è la `api_key` (pubblica per costruzione) e non è `ADMIN_API_KEY`:
# un segreto che firma l'identità di un tenant e uno che autorizza le operazioni di piattaforma
# non devono poter essere confusi né ruotati insieme.
#
# Assente = funzione spenta, non funzione insicura: l'emissione risponde 503 e la verifica fallisce
# sempre. È la differenza fra «l'assistente nel pannello non parte» e «l'assistente nel pannello
# accetta token non firmati», e solo la prima si nota.
SECRET_ENV = "PANEL_ASSISTANT_SECRET"


def secret() -> str:
    return os.getenv(SECRET_ENV, "").strip()


def configured() -> bool:
    return bool(secret())


def _sign(payload_b64: str) -> str:
    return hmac.new(secret().encode(), payload_b64.encode(), hashlib.sha256).hexdigest()


def issue_token(client_id: int, operator_id: int, now: datetime | None = None) -> str:
    """Un token di contesto per questo operatore. Il chiamante ha già dimostrato chi è."""
    moment = now or datetime.utcnow()
    payload = {
        "client_id": int(client_id),
        "operator_id": int(operator_id),
        "exp": int(moment.timestamp()) + TOKEN_TTL_SECONDS,
    }
    payload_b64 = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return f"{payload_b64}.{_sign(payload_b64)}"


def verify_token(token: str | None, now: datetime | None = None) -> dict | None:
    """Il payload se la firma regge ed è ancora valido, altrimenti `None`.

    Nessuna eccezione e nessun messaggio che distingua «firma sbagliata» da «scaduto»: chi manda
    un token non valido non deve imparare niente dalla risposta. Il confronto della firma passa da
    `compare_digest` — un `==` su un HMAC perde in tempo l'informazione che la firma protegge.
    """
    if not configured() or not token:
        return None
    payload_b64, _, signature = str(token).partition(".")
    if not payload_b64 or not signature:
        return None
    if not hmac.compare_digest(_sign(payload_b64), signature):
        return None
    try:
        payload = json.loads(base64.b64decode(payload_b64))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("client_id"), int) or not isinstance(payload.get("operator_id"), int):
        return None
    expires = payload.get("exp")
    if not isinstance(expires, int):
        return None
    moment = now or datetime.utcnow()
    if moment.timestamp() > expires:
        return None
    return payload


# ---- Il contesto: whitelist, non dump -----------------------------------------------------------


def describe_client(session: Session, client_id: int) -> dict | None:
    """I soli campi ammessi nel prompt, letti dal database.

    Ogni voce qui dentro è stata scelta perché risponde a una domanda che un cliente fa davvero
    all'assistenza — non perché era comoda da leggere. Aggiungerne una è una decisione: finisce
    nel prompt di un modello, e da lì nei log.
    """
    client = session.get(Client, client_id)
    if client is None:
        return None
    plan = session.get(Plan, client.plan_id) if client.plan_id else None

    documenti = session.exec(
        select(func.count(func.distinct(Chunk.source_ref))).where(
            Chunk.client_id == client_id, Chunk.source == "document"
        )
    ).one()
    pagine = session.exec(
        select(func.count(func.distinct(Chunk.source_ref))).where(
            Chunk.client_id == client_id, Chunk.source == "site"
        )
    ).one()
    ultimo_ingest = session.exec(
        select(func.max(IngestJob.updated_at)).where(
            IngestJob.client_id == client_id, IngestJob.status == "done"
        )
    ).one()
    # `observed` non concede nulla: un dominio visto passare non è un dominio registrato, e
    # contarlo qui farebbe dire all'assistente «il sito è a posto» proprio a chi ha il problema.
    siti = session.exec(
        select(func.count(ClientOrigin.id)).where(
            ClientOrigin.client_id == client_id, ClientOrigin.kind.in_(("live", "staging"))
        )
    ).one()
    plugin = session.exec(
        select(func.count(PluginInstallation.id)).where(PluginInstallation.client_id == client_id)
    ).one()
    aperte = session.exec(
        select(func.count(Conversation.id)).where(
            Conversation.client_id == client_id, Conversation.status.in_(("open", "escalated"))
        )
    ).one()
    in_attesa = session.exec(
        select(func.count(Conversation.id)).where(
            Conversation.client_id == client_id,
            Conversation.status == "escalated",
            Conversation.first_response_at.is_(None),
        )
    ).one()
    canali = session.exec(
        select(Conversation.channel).where(Conversation.client_id == client_id).distinct()
    ).all()

    return {
        "piano": plan.name if plan else "sconosciuto",
        "stato_abbonamento": client.billing_status,
        "documenti_indicizzati": int(documenti or 0),
        "pagine_sito_indicizzate": int(pagine or 0),
        "ultimo_ingest": ultimo_ingest.strftime("%Y-%m-%d") if ultimo_ingest else None,
        "siti_registrati": int(siti or 0),
        "plugin_verificato": bool(plugin),
        "canali_attivi": sorted(c for c in canali if c),
        "conversazioni_aperte": int(aperte or 0),
        "conversazioni_in_attesa_di_risposta": int(in_attesa or 0),
    }


def _riga(chiave: str, valore) -> str:
    if isinstance(valore, bool):
        valore = "sì" if valore else "no"
    elif isinstance(valore, list):
        valore = ", ".join(valore) if valore else "nessuno"
    elif valore is None:
        valore = "mai"
    return f"- {chiave.replace('_', ' ')}: {valore}"


def context_block(dati: dict) -> str:
    """Il blocco da mettere nel prompt.

    Va tenuto separato dal contesto recuperato dalla knowledge base, e detto esplicitamente al
    modello: la KB è documentazione generale — «per registrare un sito vai in Siti e licenza» — e
    questi sono fatti verificati su *questo* account. Mescolarli produce la risposta peggiore
    possibile, cioè una procedura generica data a chi ha un problema specifico già visibile qui.
    """
    righe = "\n".join(_riga(k, v) for k, v in dati.items())
    return (
        "ACCOUNT DATA — verified facts about the account of the person you are talking to, read "
        "from our database just now. These are NOT part of the documentation context below.\n"
        "- You may state these facts directly: they are true.\n"
        "- Prefer them over a generic procedure. If the data already shows what is wrong, say "
        "that instead of explaining the general case.\n"
        "- Never invent a value that is not listed here, and never guess a value that is "
        "missing.\n\n" + righe
    )

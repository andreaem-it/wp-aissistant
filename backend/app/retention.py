"""Conservazione e cancellazione dei dati dopo la disdetta.

Non esiste una versione gratuita del prodotto: alla fine del periodo pagato l'assistente si
sospende (vedi `billing.service_suspended`) e i dati restano disponibili per un periodo di
grazia, così chi ci ripensa ritrova tutto com'era. Passato quello, vengono eliminati.

Due responsabilità, tenute insieme perché condividono la stessa scadenza:

- avvisare per tempo, a 30/14/7/3 giorni dalla cancellazione;
- eliminare, quando la data arriva.

La cancellazione è definitiva e non è annullabile. Per questo l'unico modo di innescarla è che
`data_deletion_due_at` sia passata: nessuna scorciatoia che elimini "adesso" senza che una data
sia stata scritta prima, e la riattivazione azzera la data invece di metterla in pausa.
"""
import logging
from datetime import datetime, timedelta

from sqlmodel import Session, SQLModel, select, delete

from . import email as email_service
from .billing import DELETION_REMINDER_DAYS, SERVING_STATUSES
from .db import Client, Conversation, Operator
from .logging_config import log

logger = logging.getLogger("wpai.retention")

# Tabelle globali, non appartengono a nessun tenant.
_GLOBAL_TABLES = {"plan", "modelprice", "client"}


def purge_client(session: Session, client_id: int) -> dict:
    """Elimina ogni traccia di un tenant, tabella per tabella. Torna il conteggio per tabella.

    Le tabelle si ricavano dai metadati invece di essere elencate a mano: qui una dimenticanza
    non darebbe errore, lascerebbe silenziosamente dei dati di un cliente cancellato dentro un
    sistema multi-tenant. Aggiungere un modello con `client_id` lo include senza toccare nulla.

    L'ordine è quello di creazione rovesciato — figli prima dei genitori — perché le chiavi
    esterne non hanno cascade. Le quattro tabelle che non portano `client_id` si raggiungono
    dal loro genitore.
    """
    removed: dict[str, int] = {}
    conversation_ids = select(Conversation.id).where(Conversation.client_id == client_id)
    operator_ids = select(Operator.id).where(Operator.client_id == client_id)
    # le quattro tabelle che non portano client_id, raggiunte dal genitore che ce l'ha
    _VIA_PARENT = {
        "message": ("conversation_id", conversation_ids),
        "ticket": ("conversation_id", conversation_ids),
        "authtoken": ("operator_id", operator_ids),
    }

    # Un solo passaggio, in ordine di creazione rovesciato: figli prima dei genitori. Due
    # passaggi separati non funzionano — `airesponselog` ha client_id e punta a `message`, che
    # non ce l'ha: qualunque ordine fra "prima quelle con client_id" e "prima le altre" rompe
    # una delle due direzioni. L'ordine topologico le mette a posto entrambe.
    for table in reversed(SQLModel.metadata.sorted_tables):
        if table.name in _GLOBAL_TABLES:
            continue
        if "client_id" in table.c:
            condition = table.c.client_id == client_id
        elif table.name in _VIA_PARENT:
            column, subquery = _VIA_PARENT[table.name]
            condition = table.c[column].in_(subquery)
        else:
            continue
        result = session.exec(delete(table).where(condition))
        if result.rowcount:
            removed[table.name] = result.rowcount

    # il tenant stesso, per ultimo
    client = session.get(Client, client_id)
    if client:
        session.delete(client)
        removed["client"] = 1
    session.commit()
    log(logger, logging.WARNING, "retention.client_purged", client_id=client_id, removed=removed)
    return removed


def _notify_operators(session: Session, client: Client, send) -> None:
    """Un promemoria a ogni operatore verificato: chi può riattivare potrebbe non essere chi ha
    disdetto, e questa è l'ultima comunicazione prima di una perdita irreversibile."""
    for operator in session.exec(
        select(Operator).where(Operator.client_id == client.id, Operator.email_verified.is_(True))
    ).all():
        if not operator.email:
            continue
        try:
            send(operator.email)
        except Exception:  # noqa: BLE001 — un invio fallito non deve fermare gli altri
            log(logger, logging.WARNING, "retention.reminder_failed", client_id=client.id)


def _due_reminder(days_left: int, already_sent: "int | None") -> "int | None":
    """La soglia da inviare adesso, o None.

    Fra le soglie già raggiunte si prende **la più stretta**: a 10 giorni dalla scadenza sono
    passate sia quella dei 30 sia quella dei 14, e l'avviso da mandare è il secondo. Si manda
    solo se è più stretta dell'ultima già uscita, così un worker che gira ogni ora non ripete
    la stessa email ventiquattro volte, e uno fermo una settimana recupera l'avviso saltato
    invece di perderlo — a 20 giorni parte ancora quello dei 30.
    """
    reached = [d for d in DELETION_REMINDER_DAYS if days_left <= d]
    if not reached:
        return None
    threshold = min(reached)
    if already_sent is not None and threshold >= already_sent:
        return None
    return threshold


def run_due(session: Session, now: "datetime | None" = None) -> dict:
    """Manda i promemoria dovuti ed elimina i tenant scaduti. Torna cosa è stato fatto."""
    now = now or datetime.utcnow()
    reminded, purged = 0, 0

    scheduled = session.exec(
        select(Client).where(Client.data_deletion_due_at.is_not(None))
    ).all()
    for client in scheduled:
        # Una riattivazione che non avesse azzerato la data lascerebbe un cliente pagante in
        # coda di cancellazione: qui si controlla lo stato, non solo la data.
        if client.billing_status in SERVING_STATUSES:
            client.data_deletion_due_at = None
            client.deletion_reminder_sent_days = None
            session.add(client)
            continue

        if client.data_deletion_due_at <= now:
            purge_client(session, client.id)
            purged += 1
            continue

        days_left = max((client.data_deletion_due_at - now).days, 0)
        threshold = _due_reminder(days_left, client.deletion_reminder_sent_days)
        if threshold is None:
            continue
        deletion_at = client.data_deletion_due_at
        _notify_operators(session, client, lambda to, d=days_left, at=deletion_at:
                          email_service.send_deletion_reminder(to, d, at))
        client.deletion_reminder_sent_days = threshold
        session.add(client)
        reminded += 1

    session.commit()
    return {"reminded": reminded, "purged": purged}


# Il worker gira di continuo ma questa roba si muove di giorno in giorno: senza un freno
# interrogherebbe il database a ogni battito per non fare nulla.
_MIN_INTERVAL = timedelta(hours=1)
_last_run: "datetime | None" = None


def run_if_due(session: Session) -> None:
    """Chiamata a ogni giro del worker; lavora al più una volta all'ora."""
    global _last_run
    now = datetime.utcnow()
    if _last_run is not None and now - _last_run < _MIN_INTERVAL:
        return
    _last_run = now
    try:
        run_due(session, now)
    except Exception as exc:  # noqa: BLE001 — non deve fermare il worker di ingest
        session.rollback()
        log(logger, logging.ERROR, "retention.run_failed", error=str(exc)[:500])

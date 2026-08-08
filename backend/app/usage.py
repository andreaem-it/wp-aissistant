"""Rilevazione dei messaggi usciti per conto di un tenant.

Email e messaggi sui canali erano l'ultimo pezzo di costo fuori dal margine: non mancava la
somma, mancava proprio il dato. Qui c'è il punto unico in cui viene scritto.

Sta in un modulo suo perché lo chiamano moduli di basso livello (`email`, `whatsapp`) che non
hanno una sessione in mano: la apre questa funzione. Il prezzo non lo conosce — quello è
`costs.py`; qui si contano soltanto i messaggi.
"""
import logging
from datetime import datetime

from sqlmodel import Session, select

from .db import MessagingUsage, engine
from .logging_config import log

logger = logging.getLogger("wpai")


def record_message(client_id: int | None, channel: str, *, ok: bool = True) -> None:
    """Somma un messaggio al totale del giorno per quel tenant e quel canale.

    `client_id` nullo significa messaggio di piattaforma (verifica indirizzo, reset password,
    avvisi di fatturazione): non appartiene a nessun tenant e non viene registrato.

    Non solleva mai: un errore contabile non deve impedire l'invio di una notifica di supporto.
    Ma **non tace**: `record_embedding` fu spedito con un `NameError` dentro un `except` muto e
    per settimane non registrò nulla mentre tutto sembrava a posto. Qui il fallimento finisce
    nei log con il suo motivo, così esiste un modo di accorgersene che non sia leggere il codice.
    """
    if not client_id or not channel:
        return
    # il giorno è in UTC come in `record_embedding`: due riepiloghi che tagliassero la giornata
    # in momenti diversi non sarebbero sommabili sulla stessa riga di costo
    today = datetime.utcnow().date()
    # Due messaggi contemporanei possono trovare entrambi la riga assente e provare a crearla:
    # il vincolo di unicità ne boccia uno. Qui succede spesso — ogni risposta di un operatore
    # passa di qui — quindi al secondo giro la riga esiste e si somma su quella.
    for attempt in (1, 2):
        try:
            with Session(engine) as session:
                row = session.exec(
                    select(MessagingUsage).where(
                        MessagingUsage.client_id == client_id,
                        MessagingUsage.channel == channel,
                        MessagingUsage.day == today,
                    )
                ).first()
                if row is None:
                    row = MessagingUsage(client_id=client_id, channel=channel, day=today)
                if ok:
                    row.sent += 1
                else:
                    row.failed += 1
                row.updated_at = datetime.utcnow()
                session.add(row)
                session.commit()
            return
        except Exception as exc:  # noqa: BLE001 — vedi docstring: si annota, non si propaga
            if attempt == 1:
                continue
            log(logger, logging.WARNING, "usage.record_message_failed",
                client_id=client_id, channel=channel, error=str(exc))

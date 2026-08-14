"""Best-effort, tenant-scoped Web Push delivery for panel operators."""

import json
import logging
import os

from pywebpush import WebPushException, webpush
from sqlmodel import Session, select

from .db import PushSubscription
from .logging_config import log


logger = logging.getLogger("wpai.push")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").strip()
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:support@wpaissistant.it").strip()
PANEL_PUBLIC_URL = os.getenv("PANEL_PUBLIC_URL", "https://panel.wpaissistant.it").rstrip("/")


def configured() -> bool:
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY and VAPID_SUBJECT)


def send(
    session: Session,
    client_id: int,
    event: str,
    *,
    title: str,
    body: str,
    conversation_id: int | None = None,
    operator_ids: list[int] | None = None,
) -> int:
    if not configured():
        return 0
    query = select(PushSubscription).where(PushSubscription.client_id == client_id)
    if operator_ids is not None:
        if not operator_ids:
            return 0
        query = query.where(PushSubscription.operator_id.in_(operator_ids))
    preference = {
        "escalation": PushSubscription.escalations,
        "assignment": PushSubscription.assignments,
        "mention": PushSubscription.mentions,
        "sla_breach": PushSubscription.sla_breaches,
    }.get(event)
    if preference is not None:
        query = query.where(preference.is_(True))
    subscriptions = session.exec(query).all()
    delivered = 0
    stale = []
    data = json.dumps({
        "title": title,
        "body": body,
        "url": f"{PANEL_PUBLIC_URL}/?conversation={conversation_id}" if conversation_id else PANEL_PUBLIC_URL,
        "tag": f"{event}:{conversation_id or 'general'}",
    })
    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=data,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT},
                ttl=300,
                timeout=5,
            )
            delivered += 1
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status in (404, 410):
                # La sottoscrizione non esiste più dal lato del servizio push: il browser è stato
                # disinstallato, la cache pulita, il permesso revocato.
                stale.append(subscription)
                log(logger, logging.WARNING, "push.delivery_failed", client_id=client_id, status=status)
            elif status in (401, 403):
                # Le nostre credenziali VAPID non valgono per questa sottoscrizione: è stata
                # creata con una chiave pubblica diversa da quella che stiamo usando adesso, cioè
                # **prima di una rotazione**. Nessuna ripetizione la farà funzionare.
                #
                # Prima si potava solo su 404/410, quindi righe come queste restavano in base per
                # sempre e ogni notifica spendeva una richiesta per fallire — e nessuno se ne
                # accorgeva, perché una notifica non consegnata non ha nessuno che la reclami.
                #
                # Eliminarla è sicuro perché non è distruttivo: il pannello ricrea la
                # sottoscrizione da solo alla prima visita, ora che sa riconoscere una chiave
                # cambiata. Il livello è ERROR e non WARNING di proposito: se compare per tutte le
                # sottoscrizioni insieme non è un dispositivo, è la nostra configurazione.
                stale.append(subscription)
                log(logger, logging.ERROR, "push.credentials_rejected", client_id=client_id, status=status)
            else:
                log(logger, logging.WARNING, "push.delivery_failed", client_id=client_id, status=status)
        except Exception as exc:  # noqa: BLE001 - notifications never break the main action
            log(logger, logging.WARNING, "push.delivery_failed", client_id=client_id, error=type(exc).__name__)
    for subscription in stale:
        session.delete(subscription)
    if stale:
        session.commit()
    return delivered

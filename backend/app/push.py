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
                stale.append(subscription)
            log(logger, logging.WARNING, "push.delivery_failed", client_id=client_id, status=status)
        except Exception as exc:  # noqa: BLE001 - notifications never break the main action
            log(logger, logging.WARNING, "push.delivery_failed", client_id=client_id, error=type(exc).__name__)
    for subscription in stale:
        session.delete(subscription)
    if stale:
        session.commit()
    return delivered

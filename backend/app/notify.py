"""Best-effort operator notification via a generic webhook (stdlib only — no extra
dependency, no vendor lock-in). Point OPERATOR_WEBHOOK_URL at Slack's incoming-webhook
URL, a Zapier/n8n/Make hook, or your own endpoint; the payload is plain JSON with
`text` (human-readable, works as-is in Slack/Discord-style webhooks) plus structured
fields for anything smarter.

A notification failure must never break the chat flow it's attached to, so every
error is caught and logged, never raised.
"""

import json
import logging
import os
import urllib.request

from .logging_config import log

logger = logging.getLogger("wpai.notify")

WEBHOOK_URL = os.getenv("OPERATOR_WEBHOOK_URL", "")
TIMEOUT_SECONDS = float(os.getenv("OPERATOR_WEBHOOK_TIMEOUT_SECONDS", "3"))


def _post(payload: dict, **log_context) -> None:
    try:
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 — notification is best-effort, never blocks the caller
        log(logger, logging.WARNING, "notify.webhook_failed", error=str(exc), **log_context)


def notify_new_ticket(client_name: str, conversation_id: int, ticket_id: int, reason: str) -> None:
    if not WEBHOOK_URL:
        return
    _post(
        {
            "text": f"[{client_name}] Nuovo ticket #{ticket_id} (conversazione #{conversation_id}): {reason}",
            "client_name": client_name,
            "conversation_id": conversation_id,
            "ticket_id": ticket_id,
            "reason": reason,
        },
        ticket_id=ticket_id,
    )


TARGET_LABELS = {"first_response": "prima risposta", "resolution": "risoluzione"}


def notify_sla_breach(client_name: str, conversation_id: int, target: str, due_at: str) -> None:
    """Fired once per conversation and SLA target by the background monitor."""
    if not WEBHOOK_URL:
        return
    label = TARGET_LABELS.get(target, target)
    _post(
        {
            "text": f"[{client_name}] SLA {label} violato sulla conversazione #{conversation_id} (scadenza {due_at})",
            "client_name": client_name,
            "conversation_id": conversation_id,
            "event": "sla_breach",
            "target": target,
            "due_at": due_at,
        },
        conversation_id=conversation_id,
    )

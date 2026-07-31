"""Single entry point for conversation events.

An event has two consumers — outbound webhooks and the tenant's automations — and they must
stay in lockstep: a rule and a webhook subscribed to the same trigger have to see the same
thing. Emitting through here is also what carries the recursion depth, so an automation that
closes a conversation (which emits conversation.closed) can't feed itself forever.

Both consumers are best-effort by construction: neither can fail the action it follows.
"""

import logging

from sqlmodel import Session

from . import webhooks, workflows
from .db import Conversation
from .logging_config import log

logger = logging.getLogger("wpai.events")


def emit(
    session: Session,
    client_id: int,
    event: str,
    data: dict,
    conv: Conversation | None = None,
    depth: int = 0,
) -> None:
    """Fan the event out to the webhook queue and the automations."""
    if event in webhooks.EVENTS:
        webhooks.emit(session, client_id, event, data)
    try:
        workflows.run_for_event(session, client_id, event, data, conv=conv, depth=depth)
    except Exception as exc:  # noqa: BLE001 — run_for_event already swallows, this is the belt
        log(logger, logging.WARNING, "events.workflows_failed", event=event, error=str(exc)[:200])

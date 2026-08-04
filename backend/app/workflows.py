"""No-code automations: when an event fires, if the conditions match, apply the actions.

Design constraints that shape this module:

- **Closed vocabulary.** Triggers, condition fields, operators and action types are fixed lists.
  A rule that can't be understood is rejected when it is saved, so nothing half-applies later.
- **Never break the action it follows.** Running automations is a side effect of a conversation
  event; a failing rule is logged on its WorkflowRun and the caller carries on.
- **Auditable.** Every evaluation is recorded, matching or not: "why didn't my automation fire?"
  is the first question asked, and it needs an answer that isn't a guess.
- **No runaway loops.** Actions can emit new events (closing a conversation emits
  conversation.closed); events carry a depth and stop cascading past MAX_EVENT_DEPTH.
"""

import json
import logging
from datetime import datetime, timedelta

from sqlmodel import Session, select

from . import email as email_service
from . import tagging
from .db import Client, Conversation, ConversationRating, Department, Message, Operator, Workflow, WorkflowRun, WorkflowScheduledAction
from .logging_config import log

logger = logging.getLogger("wpai.workflows")

# Triggers: the conversation events an automation can react to (same vocabulary as webhooks,
# plus the classification, which is where "route by intent" rules belong).
TRIGGERS = (
    "conversation.created",
    "conversation.escalated",
    "conversation.replied",
    "conversation.closed",
    "conversation.rated",
    "conversation.classified",
    "sla.breached",
)

CONDITION_FIELDS = (
    "status",        # open | escalated | closed
    "priority",      # low | normal | high | urgent
    "department_id",
    "assigned",      # bool: has an assignee
    "intent",        # AI classification
    "urgency",       # AI classification
    "tag",           # list of tag names (use with contains)
    "rating_score",  # 1..5, on conversation.rated
    "sla_target",    # first_response | resolution, on sla.breached
    "visitor_email", # bool: the visitor left an address
)

CONDITION_OPS = ("eq", "neq", "in", "contains", "gt", "lt", "is_set", "is_empty")

ACTION_TYPES = (
    "set_priority",
    "set_department",
    "assign_operator",
    "assign_round_robin",
    "add_tag",
    "close_conversation",
    "escalate",
    "send_email",
    "send_webhook",
    "wait",
)

MAX_CONDITIONS = 10
MAX_ACTIONS = 10
# an action can emit an event that triggers another workflow; stop the cascade well before it
# can become a loop (close → conversation.closed → close → …)
MAX_EVENT_DEPTH = 2
RUN_LOG_KEEP = 200  # per workflow


class WorkflowConfigError(ValueError):
    """The rule is not expressible in the closed vocabulary."""


# ---- validation ---------------------------------------------------------------------------


def validate_conditions(raw) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise WorkflowConfigError("le condizioni devono essere una lista")
    if len(raw) > MAX_CONDITIONS:
        raise WorkflowConfigError(f"massimo {MAX_CONDITIONS} condizioni")
    clean = []
    for item in raw:
        if not isinstance(item, dict):
            raise WorkflowConfigError("ogni condizione deve essere un oggetto")
        field, op = item.get("field"), item.get("op")
        if field not in CONDITION_FIELDS:
            raise WorkflowConfigError(f"campo non valido: {field}")
        if op not in CONDITION_OPS:
            raise WorkflowConfigError(f"operatore non valido: {op}")
        value = item.get("value")
        if op == "in" and not isinstance(value, list):
            raise WorkflowConfigError("l'operatore 'in' richiede una lista di valori")
        if op in ("gt", "lt"):
            try:
                float(value)
            except (TypeError, ValueError) as exc:
                raise WorkflowConfigError("gli operatori 'gt' e 'lt' richiedono un numero") from exc
        clean.append({"field": field, "op": op, "value": value})
    return clean


def validate_actions(session: Session, client_id: int, raw) -> list[dict]:
    """Also checks that every referenced entity belongs to the tenant, so a rule can never be
    saved pointing at another tenant's operator, department or webhook."""
    from .db import WebhookEndpoint  # local import: only needed to validate send_webhook

    if not isinstance(raw, list) or not raw:
        raise WorkflowConfigError("serve almeno un'azione")
    if len(raw) > MAX_ACTIONS:
        raise WorkflowConfigError(f"massimo {MAX_ACTIONS} azioni")
    clean = []
    wait_seen = False
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise WorkflowConfigError("ogni azione deve essere un oggetto")
        kind = item.get("type")
        if kind not in ACTION_TYPES:
            raise WorkflowConfigError(f"azione non valida: {kind}")
        action = {"type": kind}
        if kind == "wait":
            if wait_seen or index == len(raw) - 1:
                raise WorkflowConfigError("l'attesa può comparire una sola volta e deve precedere un'azione")
            try:
                minutes = int(item.get("minutes"))
            except (TypeError, ValueError) as exc:
                raise WorkflowConfigError("durata dell'attesa non valida") from exc
            if not 1 <= minutes <= 43200:
                raise WorkflowConfigError("l'attesa deve essere tra 1 minuto e 30 giorni")
            action.update(minutes=minutes, cancel_on_reply=bool(item.get("cancel_on_reply", True)))
            wait_seen = True
        if kind == "set_priority":
            if item.get("value") not in ("low", "normal", "high", "urgent"):
                raise WorkflowConfigError("priorità non valida")
            action["value"] = item["value"]
        elif kind == "set_department":
            department = session.get(Department, int(item.get("department_id") or 0))
            if not department or department.client_id != client_id:
                raise WorkflowConfigError("reparto non trovato")
            action["department_id"] = department.id
        elif kind == "assign_operator":
            operator = session.get(Operator, int(item.get("operator_id") or 0))
            if not operator or operator.client_id != client_id:
                raise WorkflowConfigError("operatore non trovato")
            action["operator_id"] = operator.id
        elif kind == "add_tag":
            name = tagging.clean_tag_name(item.get("name", ""))
            if not name:
                raise WorkflowConfigError("nome del tag mancante")
            action["name"] = name
        elif kind == "send_email":
            to = (item.get("to") or "").strip()
            if "@" not in to or len(to) > 320:
                raise WorkflowConfigError("indirizzo email non valido")
            action["to"] = to
            action["subject"] = (item.get("subject") or "Notifica automazione").strip()[:150]
        elif kind == "send_webhook":
            endpoint = session.get(WebhookEndpoint, int(item.get("endpoint_id") or 0))
            if not endpoint or endpoint.client_id != client_id:
                raise WorkflowConfigError("webhook non trovato")
            action["endpoint_id"] = endpoint.id
        clean.append(action)
    return clean


def _schedule(session: Session, workflow: Workflow, conv: Conversation, event: str, data: dict,
              action: dict, remaining: list[dict]) -> str:
    latest = session.exec(
        select(Message.id).where(Message.conversation_id == conv.id).order_by(Message.id.desc()).limit(1)
    ).first() or 0
    row = WorkflowScheduledAction(
        client_id=workflow.client_id, workflow_id=workflow.id, conversation_id=conv.id,
        event=event, actions=json.dumps(remaining), data=json.dumps(data),
        run_at=datetime.utcnow() + timedelta(minutes=action["minutes"]),
        cancel_on_reply=action.get("cancel_on_reply", True), baseline_message_id=latest,
    )
    session.add(row)
    session.commit()
    return f"in attesa per {action['minutes']} min"


# ---- evaluation ---------------------------------------------------------------------------


def build_context(session: Session, conv: Conversation | None, event: str, data: dict) -> dict:
    """The values a condition can look at, gathered once per event."""
    if conv is None:
        return {"status": "", "priority": "", "department_id": None, "assigned": False,
                "intent": "", "urgency": "", "tag": [], "rating_score": None,
                "sla_target": data.get("target", ""), "visitor_email": False}
    tags = tagging.conversation_tags(session, [conv.id], conv.client_id).get(conv.id, [])
    rating = session.exec(
        select(ConversationRating).where(ConversationRating.conversation_id == conv.id)
    ).first()
    return {
        "status": conv.status,
        "priority": conv.priority,
        "department_id": conv.department_id,
        "assigned": conv.assigned_operator_id is not None,
        "intent": conv.ai_intent,
        "urgency": conv.ai_urgency,
        "tag": [t["name"] for t in tags],
        "rating_score": data.get("score", rating.score if rating else None),
        "sla_target": data.get("target", ""),
        "visitor_email": bool(conv.visitor_email),
    }


def _matches(condition: dict, context: dict) -> bool:
    actual = context.get(condition["field"])
    op, expected = condition["op"], condition.get("value")
    if op == "is_set":
        return bool(actual)
    if op == "is_empty":
        return not actual
    if actual is None:
        return False
    if op == "contains":
        values = actual if isinstance(actual, list) else [actual]
        return str(expected).lower() in [str(v).lower() for v in values]
    if op == "in":
        return str(actual).lower() in [str(v).lower() for v in (expected or [])]
    if op in ("gt", "lt"):
        try:
            left, right = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
        return left > right if op == "gt" else left < right
    same = str(actual).lower() == str(expected).lower()
    return same if op == "eq" else not same


def evaluate(workflow: Workflow, context: dict) -> bool:
    """All conditions must hold (AND). No conditions = always matches."""
    try:
        conditions = json.loads(workflow.conditions or "[]")
    except ValueError:
        return False
    return all(_matches(condition, context) for condition in conditions)


# ---- actions ------------------------------------------------------------------------------


def _apply_action(session: Session, conv: Conversation | None, action: dict, event: str, data: dict, depth: int) -> str:
    """Apply one action and return a short human-readable description of what it did.
    Raises on failure — the caller records the error on the run."""
    # Imported here, not at module import time: main imports this module, so a top-level import
    # would be circular. By the time an action runs, main is fully loaded.
    from . import main
    from .db import WebhookEndpoint

    kind = action["type"]
    if conv is None and kind not in ("send_email", "send_webhook"):
        return f"{kind}: nessuna conversazione, azione saltata"

    if kind == "set_priority":
        conv.priority = action["value"]
        main._apply_sla(session, conv)
        session.add(conv)
        session.commit()
        return f"priorità → {action['value']}"

    if kind == "set_department":
        conv.department_id = action["department_id"]
        main._apply_sla(session, conv)
        session.add(conv)
        session.commit()
        return f"reparto → {action['department_id']}"

    if kind == "assign_operator":
        conv.assigned_operator_id = action["operator_id"]
        session.add(conv)
        session.commit()
        return f"assegnata a operatore {action['operator_id']}"

    if kind == "assign_round_robin":
        assignee = main._auto_assign(session, conv)
        session.add(conv)
        session.commit()
        return f"assegnata a {assignee.id}" if assignee else "nessun operatore disponibile"

    if kind == "add_tag":
        tag = tagging.get_or_create_tag(session, conv.client_id, action["name"], source="manual")
        if tag is None:
            raise RuntimeError("limite tag raggiunto")
        tagging.attach_tag(session, conv, tag, source="manual")
        return f"tag «{tag.name}»"

    if kind == "close_conversation":
        if conv.status == "closed":
            return "già chiusa"
        now = datetime.utcnow()
        conv.status = "closed"
        conv.closed_at = now
        conv.updated_at = now
        session.add(conv)
        session.commit()
        from . import events

        events.emit(session, conv.client_id, "conversation.closed", {"conversation_id": conv.id},
                    conv=conv, depth=depth + 1)
        return "conversazione chiusa"

    if kind == "escalate":
        if conv.status == "escalated":
            return "già in escalation"
        client = session.get(Client, conv.client_id)
        main._escalate(
            session, conv.client_id, client.name if client else "—", conv,
            "regola di automazione", outcome="escalated_model", trigger="workflow",
            depth=depth + 1,
        )
        return "passata a un operatore"

    if kind == "send_email":
        body = (
            f"Evento: {event}\n"
            f"Conversazione: {conv.id if conv else '—'}\n"
            f"Dettagli: {json.dumps(data, ensure_ascii=False)}\n"
        )
        email_service.send_email(action["to"], action["subject"], body)
        return f"email a {action['to']}"

    if kind == "send_webhook":
        endpoint = session.get(WebhookEndpoint, action["endpoint_id"])
        if endpoint is None or endpoint.client_id != (conv.client_id if conv else endpoint.client_id):
            raise RuntimeError("webhook non disponibile")
        from . import webhooks
        from .db import WebhookDelivery

        now = datetime.utcnow()
        delivery = WebhookDelivery(
            client_id=endpoint.client_id,
            endpoint_id=endpoint.id,
            event=event if event in webhooks.EVENTS else "conversation.created",
            payload=json.dumps({
                "event": event,
                "created_at": now.isoformat() + "Z",
                "source": "workflow",
                "data": {**data, "conversation_id": conv.id if conv else None},
            }),
            max_attempts=webhooks.MAX_ATTEMPTS,
            next_attempt_at=now,
        )
        session.add(delivery)
        session.commit()
        return f"webhook {endpoint.id} accodato"

    raise RuntimeError(f"azione sconosciuta: {kind}")


def _trim_runs(session: Session, workflow_id: int) -> None:
    rows = session.exec(
        select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id).order_by(WorkflowRun.id.desc())
    ).all()
    for row in rows[RUN_LOG_KEEP:]:
        session.delete(row)
    if len(rows) > RUN_LOG_KEEP:
        session.commit()


def run_for_event(
    session: Session,
    client_id: int,
    event: str,
    data: dict,
    conv: Conversation | None = None,
    depth: int = 0,
) -> list[dict]:
    """Evaluate every active workflow bound to this trigger. Returns a summary per workflow.
    Never raises: an automation failure is recorded, not propagated."""
    if event not in TRIGGERS:
        return []
    if depth > MAX_EVENT_DEPTH:
        log(logger, logging.WARNING, "workflow.depth_exceeded", event=event, client_id=client_id)
        return []
    try:
        workflows = session.exec(
            select(Workflow)
            .where(Workflow.client_id == client_id, Workflow.trigger == event, Workflow.active.is_(True))
            .order_by(Workflow.position, Workflow.id)
        ).all()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        log(logger, logging.WARNING, "workflow.lookup_failed", error=str(exc)[:200])
        return []
    if not workflows:
        return []

    summaries = []
    for workflow in workflows:
        applied: list[str] = []
        error = ""
        context = build_context(session, conv, event, data)
        matched = evaluate(workflow, context)
        if matched:
            try:
                configured = json.loads(workflow.actions or "[]")
                for index, action in enumerate(configured):
                    if action["type"] == "wait":
                        if conv is None:
                            applied.append("attesa saltata: nessuna conversazione")
                        else:
                            applied.append(_schedule(session, workflow, conv, event, data, action, configured[index + 1:]))
                        break
                    applied.append(_apply_action(session, conv, action, event, data, depth))
            except Exception as exc:  # noqa: BLE001 — one bad action must not break the request
                session.rollback()
                error = str(exc)[:300]
                log(
                    logger, logging.WARNING, "workflow.action_failed",
                    workflow_id=workflow.id, client_id=client_id, error=error,
                )
        try:
            if matched:
                workflow.run_count += 1
                workflow.last_run_at = datetime.utcnow()
                session.add(workflow)
            session.add(WorkflowRun(
                client_id=client_id,
                workflow_id=workflow.id,
                conversation_id=conv.id if conv else None,
                event=event,
                matched=matched,
                applied=json.dumps(applied, ensure_ascii=False),
                error=error,
            ))
            session.commit()
            _trim_runs(session, workflow.id)
        except Exception as exc:  # noqa: BLE001 — logging the run must not break anything either
            session.rollback()
            log(logger, logging.WARNING, "workflow.run_log_failed", error=str(exc)[:200])
        summaries.append({
            "workflow_id": workflow.id, "name": workflow.name,
            "matched": matched, "applied": applied, "error": error,
        })
    return summaries


def dispatch_scheduled(session: Session, now: datetime | None = None) -> int:
    """Claim and execute due continuations. Row locking makes concurrent workers safe."""
    now = now or datetime.utcnow()
    rows = session.exec(
        select(WorkflowScheduledAction)
        .where(WorkflowScheduledAction.status == "pending", WorkflowScheduledAction.run_at <= now)
        .order_by(WorkflowScheduledAction.id).with_for_update(skip_locked=True).limit(20)
    ).all()
    processed = 0
    for row in rows:
        row.status = "running"
        row.attempts += 1
        row.updated_at = now
        session.add(row)
        session.commit()
        try:
            conv = session.get(Conversation, row.conversation_id)
            workflow = session.get(Workflow, row.workflow_id)
            if not conv or conv.client_id != row.client_id or not workflow or not workflow.active:
                row.status, row.last_error = "cancelled", "workflow o conversazione non disponibile"
            elif row.cancel_on_reply and session.exec(
                select(Message.id).where(
                    Message.conversation_id == conv.id, Message.id > row.baseline_message_id,
                    Message.role.in_(("user", "operator")),
                ).limit(1)
            ).first():
                row.status, row.last_error = "cancelled", "nuova risposta ricevuta"
            else:
                applied = [_apply_action(session, conv, action, row.event, json.loads(row.data), 0)
                           for action in json.loads(row.actions)]
                row.status = "completed"
                session.add(WorkflowRun(
                    client_id=row.client_id, workflow_id=row.workflow_id,
                    conversation_id=row.conversation_id, event=f"{row.event}.delayed",
                    matched=True, applied=json.dumps(applied, ensure_ascii=False),
                ))
            if row.status in ("completed", "cancelled"):
                row.completed_at = datetime.utcnow()
            row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()
            processed += 1
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            row = session.get(WorkflowScheduledAction, row.id)
            row.last_error = str(exc)[:300]
            row.status = "failed" if row.attempts >= row.max_attempts else "pending"
            if row.status == "pending":
                row.run_at = datetime.utcnow() + timedelta(minutes=2 ** row.attempts)
            else:
                row.completed_at = datetime.utcnow()
            row.updated_at = datetime.utcnow()
            session.add(row)
            session.commit()
    return processed


def preview(session: Session, workflow: Workflow, conv: Conversation, event: str | None = None) -> dict:
    """Dry run: says whether the rule would match this conversation and which actions it would
    apply, without touching anything."""
    context = build_context(session, conv, event or workflow.trigger, {})
    return {
        "matched": evaluate(workflow, context),
        "context": context,
        "actions": json.loads(workflow.actions or "[]"),
    }

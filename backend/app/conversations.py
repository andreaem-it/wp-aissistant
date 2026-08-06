"""Conversation-level operations shared across areas.

Three things every area needs to do with a conversation without owning it: reach it safely
within its tenant, know whether its channel still accepts a free-form message, and deliver an
operator reply back to the visitor on whichever channel they arrived from.

They live here rather than in `main.py` so a router can use them without importing it.
"""
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlmodel import Session, select

from . import email as email_service
from . import meta_messaging as meta_messaging_service
from . import whatsapp as whatsapp_service
from .db import Client, Contact, Conversation, ConversationRating, Message, WhatsAppConsent
from .util import iso as _iso

# the closed vocabulary of SLA states, shared by the inbox filters and every conversation view
SLA_STATES = ("ok", "in_scadenza", "violato")


def require_conversation(session: Session, client_id: int, conversation_id: int) -> Conversation:
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != client_id:
        raise HTTPException(404, "conversation not found")
    return conv


def whatsapp_channel_status(session: Session, conv: Conversation) -> dict:
    last_inbound = session.exec(
        select(Message)
        .where(Message.conversation_id == conv.id, Message.role == "user")
        .order_by(Message.created_at.desc())
        .limit(1)
    ).first()
    window_expires_at = last_inbound.created_at + timedelta(hours=24) if last_inbound else None
    consent = session.exec(
        select(WhatsAppConsent).where(
            WhatsAppConsent.client_id == conv.client_id,
            WhatsAppConsent.contact_id == conv.contact_id,
        )
    ).first() if conv.contact_id else None
    return {
        "window_open": bool(window_expires_at and window_expires_at > datetime.utcnow()),
        "window_expires_at": _iso(window_expires_at),
        "consent_granted": bool(consent and consent.granted),
        "consent_source": consent.source if consent and consent.granted else "",
    }


def notify_visitor_reply(session, client_id, conv):
    """Best-effort visitor email notification on an operator reply (never blocks the reply)."""
    if conv.channel == "whatsapp" and conv.contact_id:
        contact = session.get(Contact, conv.contact_id)
        last_inbound = session.exec(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.role == "user")
            .order_by(Message.created_at.desc())
            .limit(1)
        ).first()
        if not contact or not last_inbound or last_inbound.created_at < datetime.utcnow() - timedelta(hours=24):
            return False
        latest_operator = session.exec(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.role == "operator")
            .order_by(Message.id.desc())
            .limit(1)
        ).first()
        return bool(latest_operator) and whatsapp_service.send_message(
            client_id=client_id,
            to=contact.external_id,
            body=latest_operator.content,
            reply_to_message_id=last_inbound.external_id or "",
        )
    if conv.channel in {"messenger", "instagram"} and conv.contact_id:
        contact = session.get(Contact, conv.contact_id)
        last_inbound = session.exec(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.role == "user")
            .order_by(Message.created_at.desc())
            .limit(1)
        ).first()
        latest_operator = session.exec(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.role == "operator")
            .order_by(Message.id.desc())
            .limit(1)
        ).first()
        return bool(contact and latest_operator) and meta_messaging_service.send_message(
            client_id=client_id,
            platform=conv.channel,
            recipient_id=contact.external_id,
            body=latest_operator.content,
            reply_to_message_id=last_inbound.external_id if last_inbound else "",
        )
    if conv.visitor_email:
        client = session.get(Client, client_id)
        client_name = client.name if client else "il supporto"
        if conv.channel == "email":
            messages = session.exec(
                select(Message)
                .where(Message.conversation_id == conv.id, Message.role == "operator")
                .order_by(Message.id.desc())
                .limit(1)
            ).all()
            if messages:
                return email_service.send_channel_reply(
                    conv.visitor_email,
                    client_name,
                    conv.channel_subject,
                    messages[0].content,
                    conv.external_thread_id,
                )
        else:
            return email_service.send_visitor_reply(conv.visitor_email, client_name, conv.visitor_url)
    return True


def target_state(due_at, warn_at, met_at, now) -> str | None:
    """ok | in_scadenza | violato for one SLA target, or None when the target isn't set."""
    if due_at is None:
        return None
    if met_at is not None:
        return "violato" if met_at > due_at else "ok"
    if now > due_at:
        return "violato"
    if warn_at is not None and now >= warn_at:
        return "in_scadenza"
    return "ok"


def _worst_sla_state(*states: str | None) -> str | None:
    for level in SLA_STATES[::-1]:  # violato, in_scadenza, ok
        if level in states:
            return level
    return None


def sla_view(conv: Conversation, now: datetime | None = None) -> dict | None:
    """Serializable SLA summary for the inbox: per-target deadline, when it was met and the
    state, plus the worst of the two. None when no SLA is running on this conversation."""
    if conv.sla_started_at is None:
        return None
    if conv.first_response_due_at is None and conv.resolution_due_at is None:
        return None
    now = now or datetime.utcnow()
    first = target_state(conv.first_response_due_at, conv.first_response_warn_at, conv.first_response_at, now)
    resolution = target_state(conv.resolution_due_at, conv.resolution_warn_at, conv.closed_at, now)
    return {
        "started_at": _iso(conv.sla_started_at),
        "policy_id": conv.sla_policy_id,
        "state": _worst_sla_state(first, resolution),
        "first_response": {
            "due_at": _iso(conv.first_response_due_at),
            "met_at": _iso(conv.first_response_at),
            "state": first,
        },
        "resolution": {
            "due_at": _iso(conv.resolution_due_at),
            "met_at": _iso(conv.closed_at),
            "state": resolution,
        },
    }


def rating_payload(rating: ConversationRating | None) -> dict | None:
    if rating is None:
        return None
    return {
        "score": rating.score,
        "comment": rating.comment,
        "resolved_by": rating.resolved_by,
        "created_at": _iso(rating.created_at),
    }

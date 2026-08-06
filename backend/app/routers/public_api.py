"""Public API `/v1`: the versioned surface a tenant's own software talks to.

Authenticated with a scoped server-side key, never the widget key, and rate limited per key so
one integration cannot starve the others. Payload shapes here are a published contract: adding
a field is fine, changing or removing one is a breaking change for somebody's integration.

Third area extracted from main.py — see `docs/handoff.md` for the pattern.
"""
import logging
import os
from datetime import datetime

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlmodel import Session, select

from .. import events, tagging
from ..analytics import build_stats as _build_stats
from ..apikeys import scopes_of as _api_key_scopes
from ..conversations import (
    PRIORITIES,
    notify_visitor_reply as _notify_visitor_reply,
    rating_payload as _rating_payload,
    require_conversation as _require_conversation,
    sla_view as _sla_view,
    whatsapp_channel_status as _whatsapp_channel_status,
)
from ..db import (
    ApiKey, Conversation, ConversationRating, ConversationTag, Message, Tag, Ticket, get_session,
)
from ..deps import audit as _audit, hash_api_key as _hash_api_key
from ..limits import MAX_CHAT_MESSAGE_CHARS, MAX_INGEST_TEXT_CHARS
from ..ratelimit import make_limiter
from ..util import bounded_limit as _bounded_limit, iso as _iso
from ..worker import enqueue as _enqueue

logger = logging.getLogger("wpai")

# per-key budget: one tenant's integration must not be able to starve the others
api_limiter = make_limiter(int(os.getenv("PUBLIC_API_RATE_LIMIT", "120")), 60)
# don't write last_used_at on every call: one update per minute per key is enough to answer
# "is this key still in use?" without a write on the hot path
API_KEY_TOUCH_SECONDS = 60

router = APIRouter()


def _resolve_api_key(session: Session, token: str) -> ApiKey | None:
    key = session.exec(select(ApiKey).where(ApiKey.token_hash == _hash_api_key(token))).first()
    if key is None or key.revoked_at is not None:
        return None
    return key


def require_api_scope(scope: str):
    """Dependency factory for the /v1 endpoints: validates the bearer key, checks the scope and
    applies the public-API rate limit. Returns the ApiKey (which carries the tenant)."""

    def dependency(
        authorization: str = Header(None),
        session: Session = Depends(get_session),
    ) -> ApiKey:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "missing bearer token")
        key = _resolve_api_key(session, authorization[7:].strip())
        if key is None:
            raise HTTPException(401, "invalid api key")
        if scope not in _api_key_scopes(key):
            raise HTTPException(403, f"scope richiesto: {scope}")
        api_limiter.check(f"api:{key.id}")
        now = datetime.utcnow()
        if key.last_used_at is None or (now - key.last_used_at).total_seconds() > API_KEY_TOUCH_SECONDS:
            key.last_used_at = now
            session.add(key)
            session.commit()
        return key

    return dependency


def _v1_conversation(session: Session, conv: Conversation, now: datetime) -> dict:
    tags = tagging.conversation_tags(session, [conv.id], conv.client_id).get(conv.id, [])
    rating = session.exec(
        select(ConversationRating).where(ConversationRating.conversation_id == conv.id)
    ).first()
    return {
        "id": conv.id,
        "visitor_id": conv.visitor_id,
        "channel": conv.channel,
        "contact_id": conv.contact_id,
        "external_thread_id": conv.external_thread_id,
        "status": conv.status,
        "priority": conv.priority,
        "department_id": conv.department_id,
        "assigned_operator_id": conv.assigned_operator_id,
        "created_at": _iso(conv.created_at),
        "updated_at": _iso(conv.updated_at),
        "closed_at": _iso(conv.closed_at),
        "tags": [t["name"] for t in tags],
        "classification": tagging.classification_payload(conv),
        "sla": _sla_view(conv, now),
        "rating": _rating_payload(rating),
    }


@router.get("/v1/conversations")
def v1_list_conversations(
    status: str | None = None,
    priority: str | None = None,
    tag_id: int | None = None,
    before_id: int | None = None,
    limit: int = 50,
    key: ApiKey = Depends(require_api_scope("conversations:read")),
    session: Session = Depends(get_session),
):
    query = select(Conversation).where(Conversation.client_id == key.client_id)
    if status:
        if status not in ("open", "escalated", "closed"):
            raise HTTPException(400, "invalid status")
        query = query.where(Conversation.status == status)
    if priority:
        if priority not in PRIORITIES:
            raise HTTPException(400, "invalid priority")
        query = query.where(Conversation.priority == priority)
    if tag_id is not None:
        tag = session.get(Tag, tag_id)
        if not tag or tag.client_id != key.client_id:
            raise HTTPException(404, "tag not found")
        query = query.where(
            Conversation.id.in_(
                select(ConversationTag.conversation_id).where(ConversationTag.tag_id == tag_id)
            )
        )
    if before_id:
        query = query.where(Conversation.id < before_id)
    convs = session.exec(
        query.order_by(Conversation.id.desc()).limit(_bounded_limit(limit, default=50, maximum=200))
    ).all()
    now = datetime.utcnow()
    return {
        "data": [_v1_conversation(session, conv, now) for conv in convs],
        "next_before_id": convs[-1].id if convs else None,
    }


@router.get("/v1/conversations/{conversation_id}")
def v1_get_conversation(
    conversation_id: int,
    key: ApiKey = Depends(require_api_scope("conversations:read")),
    session: Session = Depends(get_session),
):
    conv = _require_conversation(session, key.client_id, conversation_id)
    messages = session.exec(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)
    ).all()
    payload = _v1_conversation(session, conv, datetime.utcnow())
    # internal notes are deliberately absent: they are not part of the public contract
    payload["messages"] = [
        {"id": m.id, "role": m.role, "content": m.content, "created_at": _iso(m.created_at)}
        for m in messages
    ]
    return payload


@router.post("/v1/conversations/{conversation_id}/reply")
def v1_reply(
    conversation_id: int,
    reply: str = Body(..., embed=True),
    key: ApiKey = Depends(require_api_scope("conversations:write")),
    session: Session = Depends(get_session),
):
    """Reply as the team from an external system (CRM, automation). Behaves like an operator
    reply: reopens the conversation, closes open tickets, stops the first-response SLA and
    notifies the visitor by email if they left one."""
    conv = _require_conversation(session, key.client_id, conversation_id)
    if conv.channel == "whatsapp" and not _whatsapp_channel_status(session, conv)["window_open"]:
        raise HTTPException(409, "WhatsApp 24-hour window expired; use an approved template")
    text = (reply or "").strip()
    if not text:
        raise HTTPException(400, "reply required")
    now = datetime.utcnow()
    session.add(Message(conversation_id=conv.id, role="operator", content=text[:MAX_CHAT_MESSAGE_CHARS]))
    if conv.first_response_at is None:
        conv.first_response_at = now
    conv.status = "open"
    conv.updated_at = now
    session.add(conv)
    for ticket in session.exec(
        select(Ticket).where(Ticket.conversation_id == conv.id, Ticket.status == "open")
    ).all():
        ticket.status = "answered"
        ticket.updated_at = now
        session.add(ticket)
    session.commit()
    _audit(
        session, "api", key.prefix, "conversation.reply",
        target=f"conversation:{conversation_id}", client_id=key.client_id,
    )
    _notify_visitor_reply(session, key.client_id, conv)
    events.emit(session, key.client_id, "conversation.replied", {"conversation_id": conv.id, "via": "api"}, conv=conv)
    return {"ok": True}


@router.post("/v1/conversations/{conversation_id}/status")
def v1_set_status(
    conversation_id: int,
    status: str = Body(..., embed=True),
    key: ApiKey = Depends(require_api_scope("conversations:write")),
    session: Session = Depends(get_session),
):
    if status not in ("open", "closed"):
        raise HTTPException(400, "status must be 'open' or 'closed'")
    conv = _require_conversation(session, key.client_id, conversation_id)
    now = datetime.utcnow()
    conv.status = status
    conv.updated_at = now
    conv.closed_at = now if status == "closed" else None
    session.add(conv)
    session.commit()
    _audit(
        session, "api", key.prefix, f"conversation.{status}",
        target=f"conversation:{conversation_id}", client_id=key.client_id,
    )
    if status == "closed":
        events.emit(session, key.client_id, "conversation.closed", {"conversation_id": conv.id}, conv=conv)
    return {"ok": True, "status": status}


@router.post("/v1/conversations/{conversation_id}/tags")
def v1_tag(
    conversation_id: int,
    name: str = Body(..., embed=True),
    key: ApiKey = Depends(require_api_scope("conversations:write")),
    session: Session = Depends(get_session),
):
    conv = _require_conversation(session, key.client_id, conversation_id)
    tag = tagging.get_or_create_tag(session, key.client_id, name, source="manual")
    if tag is None:
        raise HTTPException(400, "nome tag non valido o limite raggiunto")
    tagging.attach_tag(session, conv, tag, source="manual")
    return {"id": tag.id, "name": tag.name}


@router.get("/v1/stats")
def v1_stats(
    key: ApiKey = Depends(require_api_scope("stats:read")),
    session: Session = Depends(get_session),
):
    return _build_stats(session, key.client_id)


@router.post("/v1/knowledge/documents")
def v1_ingest_document(
    title: str = Body(...),
    text: str = Body(...),
    key: ApiKey = Depends(require_api_scope("knowledge:write")),
    session: Session = Depends(get_session),
):
    """Queue a text document into the knowledge base. Returns the job id to poll on
    /ingest/jobs/{id} with the same key."""
    clean_title = (title or "").strip()[:200]
    body = (text or "").strip()
    if not clean_title or not body:
        raise HTTPException(400, "title and text required")
    if len(body) > MAX_INGEST_TEXT_CHARS:
        raise HTTPException(413, "text too large")
    job = _enqueue(session, key.client_id, "document", {"source_ref": clean_title, "text": body})
    _audit(
        session, "api", key.prefix, "knowledge.ingest",
        target=f"job:{job.id}", client_id=key.client_id, detail={"title": clean_title},
    )
    return {"job_id": job.id, "status": job.status}

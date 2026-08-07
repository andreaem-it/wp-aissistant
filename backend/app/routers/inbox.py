"""Operator inbox: the conversations themselves.

Listing and filtering, replies, status, tickets, tags, internal notes and mentions, presence and
typing, saved views, and the GDPR export/erase a tenant runs on its own data.

Internal notes and mentions are never returned by a visitor-facing endpoint; presence and typing
are in-process state with a TTL, deliberately not persisted — they describe this moment, not history.

Eighth area extracted from main.py — see `docs/handoff.md` for the pattern.
"""
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy import case, func, or_
from sqlmodel import Session, select

from .. import events, language, push as push_service, tagging
from ..deps import get_client
from ..llm import INTENTS as llm_intents, URGENCIES as llm_urgencies
from ..conversations import (
    PRIORITIES, SLA_STATES,
    erase_conversation as _erase_conversation,
    notify_visitor_reply as _notify_visitor_reply,
    operator_name as _operator_name,
    rating_payload as _rating_payload,
    require_conversation as _require_conversation,
    require_conversation_token as _require_conversation_token,
    sla_view as _sla_view,
    whatsapp_channel_status as _whatsapp_channel_status,
)
from ..analytics import sla_breached_clause as _sla_breached_clause, sla_warning_clause as _sla_warning_clause
from ..db import (
    Attachment, AuditLog, Conversation, ConversationRating, ConversationTag, Department,
    HelpdeskConnection, HelpdeskExport, InternalNote, Message, NoteMention, Operator, SavedView,
    Tag, Ticket, get_session,
)
from ..deps import (
    audit as _audit, bearer_token as _bearer_token, get_operator_session as _get_operator_session,
    require_operator,
)
from ..helpdesk import export_payload as _helpdesk_export_payload
from ..routing import apply_sla as _apply_sla, require_department as _require_department
from ..util import bounded_limit as _bounded_limit, iso as _iso, slugify as _slugify

logger = logging.getLogger("wpai")

# in-process presence/typing state: describes this moment, not history, so it is not persisted
_operator_typing: dict[int, tuple[str, float]] = {}
_conversation_presence: dict[int, dict[int, tuple[str, float, bool]]] = {}

router = APIRouter()


TYPING_TTL = float(os.getenv("TYPING_TTL_SECONDS", "8"))


def _filter_by_sla_state(query, state: str, now: datetime):
    running = Conversation.sla_started_at.is_not(None)
    breached = _sla_breached_clause(now)
    warning = _sla_warning_clause(now)
    if state == "violato":
        return query.where(running, breached)
    if state == "in_scadenza":
        return query.where(running, ~breached, warning)
    return query.where(running, ~breached, ~warning)  # ok


@router.get("/tags")
def list_tags(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(Tag).where(Tag.client_id == operator.client_id).order_by(Tag.name)
    ).all()
    return [{"id": t.id, "name": t.name, "color": t.color, "source": t.source} for t in rows]


@router.post("/tags")
def create_tag(
    name: str = Body(...),
    color: str = Body(""),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    clean = tagging.clean_tag_name(name)
    if not clean:
        raise HTTPException(400, "name required")
    if tagging.find_tag(session, operator.client_id, clean):
        raise HTTPException(409, "tag already exists")
    tag = tagging.get_or_create_tag(session, operator.client_id, clean, source="manual")
    if tag is None:
        raise HTTPException(400, "tag limit reached")
    if color:
        tag.color = color.strip()[:16]
        session.add(tag)
        session.commit()
    _audit(
        session, "operator", operator.email, "tag.create",
        target=f"tag:{tag.id}", client_id=operator.client_id, detail={"name": tag.name},
    )
    return {"id": tag.id, "name": tag.name, "color": tag.color, "source": tag.source}


@router.delete("/tags/{tag_id}")
def delete_tag(
    tag_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    tag = session.get(Tag, tag_id)
    if not tag or tag.client_id != operator.client_id:
        raise HTTPException(404, "tag not found")
    for link in session.exec(select(ConversationTag).where(ConversationTag.tag_id == tag.id)).all():
        session.delete(link)
    session.flush()
    session.delete(tag)
    session.commit()
    _audit(
        session, "operator", operator.email, "tag.delete",
        target=f"tag:{tag_id}", client_id=operator.client_id,
    )
    return {"ok": True}


@router.post("/conversations/{conversation_id}/tags")
def tag_conversation(
    conversation_id: int,
    tag_id: int | None = Body(None),
    name: str = Body(""),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Attach an existing tag (`tag_id`) or create-and-attach one by name."""
    conv = _require_conversation(session, operator.client_id, conversation_id)
    if tag_id is not None:
        tag = session.get(Tag, tag_id)
        if not tag or tag.client_id != operator.client_id:
            raise HTTPException(404, "tag not found")
    else:
        clean = tagging.clean_tag_name(name)
        if not clean:
            raise HTTPException(400, "tag_id or name required")
        tag = tagging.get_or_create_tag(session, operator.client_id, clean, source="manual")
        if tag is None:
            raise HTTPException(400, "tag limit reached")
    tagging.attach_tag(session, conv, tag, source="manual")
    _audit(
        session, "operator", operator.email, "conversation.tag_add",
        target=f"conversation:{conversation_id}", client_id=operator.client_id,
        detail={"tag_id": tag.id, "name": tag.name},
    )
    return {"id": tag.id, "name": tag.name, "color": tag.color, "source": "manual"}


@router.delete("/conversations/{conversation_id}/tags/{tag_id}")
def untag_conversation(
    conversation_id: int,
    tag_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    _require_conversation(session, operator.client_id, conversation_id)
    link = session.exec(
        select(ConversationTag).where(
            ConversationTag.client_id == operator.client_id,
            ConversationTag.conversation_id == conversation_id,
            ConversationTag.tag_id == tag_id,
        )
    ).first()
    if not link:
        raise HTTPException(404, "tag not attached")
    session.delete(link)
    session.commit()
    _audit(
        session, "operator", operator.email, "conversation.tag_remove",
        target=f"conversation:{conversation_id}", client_id=operator.client_id,
        detail={"tag_id": tag_id},
    )
    return {"ok": True}


@router.post("/conversations/{conversation_id}/classify")
def classify_conversation_now(
    conversation_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Classify on demand from the panel. Returns 503 when the classification could not be
    produced: the conversation is left untouched, never labelled with a guess."""
    conv = _require_conversation(session, operator.client_id, conversation_id)
    result = tagging.classify_conversation(session, conv)
    if result is None:
        raise HTTPException(503, "classificazione non disponibile")
    _audit(
        session, "operator", operator.email, "conversation.classify",
        target=f"conversation:{conversation_id}", client_id=operator.client_id, detail=result,
    )
    return {"classification": tagging.classification_payload(conv)}


MAX_NOTE_CHARS = int(os.getenv("MAX_NOTE_CHARS", "4000"))


PRESENCE_TTL = float(os.getenv("PRESENCE_TTL_SECONDS", "20"))


PRESENCE_MAX_CONVERSATIONS = 500


def _live_presence(entries: dict, now: float) -> dict:
    return {op_id: entry for op_id, entry in entries.items() if now - entry[1] < PRESENCE_TTL}


def _prune_presence(conversation_id: int) -> dict[int, tuple[str, float, bool]]:
    now = time.monotonic()
    live = _live_presence(_conversation_presence.get(conversation_id, {}), now)
    if live:
        _conversation_presence[conversation_id] = live
    else:
        _conversation_presence.pop(conversation_id, None)
    if len(_conversation_presence) > PRESENCE_MAX_CONVERSATIONS:
        for other_id in list(_conversation_presence):
            remaining = _live_presence(_conversation_presence[other_id], now)
            if remaining:
                _conversation_presence[other_id] = remaining
            else:
                del _conversation_presence[other_id]
    return live


def _mention_tokens(body: str) -> set[str]:
    return {token.lower() for token in re.findall(r"@([\w.\-+]+)", body or "")}


def _resolve_mentions(session: Session, client_id: int, body: str, explicit_ids: list[int]) -> list[Operator]:
    """Operators tagged in a note: the ids the panel sends plus any `@token` in the text that
    matches an operator's name or email local-part. Ids outside the tenant are ignored, never
    an error, so a note is never lost because of a stale autocomplete entry."""
    team = session.exec(select(Operator).where(Operator.client_id == client_id)).all()
    tokens = _mention_tokens(body)
    wanted = set(explicit_ids or [])
    resolved: dict[int, Operator] = {}
    for member in team:
        local_part = member.email.split("@")[0].lower()
        name_slug = _slugify(member.name).lower() if member.name else ""
        if member.id in wanted or local_part in tokens or (name_slug and name_slug in tokens):
            resolved[member.id] = member
    return list(resolved.values())


def _note_payload(note: InternalNote, names: dict, mentions: list[dict]) -> dict:
    return {
        "id": note.id,
        "body": note.body,
        "created_at": _iso(note.created_at),
        "operator_id": note.operator_id,
        "author": names.get(note.operator_id, "—"),
        "mentions": mentions,
    }


@router.get("/conversations/{conversation_id}/notes")
def list_notes(
    conversation_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Operator-only. Opening the notes marks the reader's own mentions on this conversation
    as read."""
    _require_conversation(session, operator.client_id, conversation_id)
    notes = session.exec(
        select(InternalNote)
        .where(InternalNote.client_id == operator.client_id, InternalNote.conversation_id == conversation_id)
        .order_by(InternalNote.id)
    ).all()
    names = {
        row.id: _operator_name(row)
        for row in session.exec(select(Operator).where(Operator.client_id == operator.client_id)).all()
    }
    mention_rows = session.exec(
        select(NoteMention).where(
            NoteMention.client_id == operator.client_id,
            NoteMention.conversation_id == conversation_id,
        )
    ).all()
    by_note: dict[int, list[dict]] = {}
    now = datetime.utcnow()
    dirty = False
    for row in mention_rows:
        by_note.setdefault(row.note_id, []).append(
            {"operator_id": row.operator_id, "name": names.get(row.operator_id, "—")}
        )
        if row.operator_id == operator.id and row.read_at is None:
            row.read_at = now
            session.add(row)
            dirty = True
    if dirty:
        session.commit()
    return [_note_payload(note, names, by_note.get(note.id, [])) for note in notes]


@router.post("/conversations/{conversation_id}/notes")
def create_note(
    conversation_id: int,
    body: str = Body(...),
    mentions: list[int] = Body([]),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    _require_conversation(session, operator.client_id, conversation_id)
    text = (body or "").strip()[:MAX_NOTE_CHARS]
    if not text:
        raise HTTPException(400, "body required")
    note = InternalNote(
        client_id=operator.client_id,
        conversation_id=conversation_id,
        operator_id=operator.id,
        body=text,
    )
    session.add(note)
    session.commit()
    session.refresh(note)
    mentioned = [m for m in _resolve_mentions(session, operator.client_id, text, mentions) if m.id != operator.id]
    for member in mentioned:
        session.add(
            NoteMention(
                client_id=operator.client_id,
                note_id=note.id,
                conversation_id=conversation_id,
                operator_id=member.id,
            )
        )
    if mentioned:
        session.commit()
        push_service.send(
            session, operator.client_id, "mention",
            title=f"{_operator_name(operator)} ti ha menzionato",
            body=text[:180], conversation_id=conversation_id,
            operator_ids=[member.id for member in mentioned],
        )
    _audit(
        session, "operator", operator.email, "note.create",
        target=f"conversation:{conversation_id}", client_id=operator.client_id,
        detail={"note_id": note.id, "mentions": [m.id for m in mentioned]},
    )
    names = {operator.id: _operator_name(operator), **{m.id: _operator_name(m) for m in mentioned}}
    return _note_payload(
        note, names, [{"operator_id": m.id, "name": _operator_name(m)} for m in mentioned]
    )


@router.delete("/conversations/{conversation_id}/notes/{note_id}")
def delete_note(
    conversation_id: int,
    note_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Only the author can remove their note; the deletion stays in the audit log."""
    _require_conversation(session, operator.client_id, conversation_id)
    note = session.get(InternalNote, note_id)
    if not note or note.client_id != operator.client_id or note.conversation_id != conversation_id:
        raise HTTPException(404, "note not found")
    if note.operator_id != operator.id:
        raise HTTPException(403, "not the author of this note")
    for mention in session.exec(select(NoteMention).where(NoteMention.note_id == note.id)).all():
        session.delete(mention)
    session.flush()
    session.delete(note)
    session.commit()
    _audit(
        session, "operator", operator.email, "note.delete",
        target=f"conversation:{conversation_id}", client_id=operator.client_id,
        detail={"note_id": note_id},
    )
    return {"ok": True}


@router.get("/mentions")
def list_my_mentions(
    unread_only: bool = True,
    limit: int = 50,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """The operator's own mentions, newest first — the panel's «ti hanno citato» list."""
    query = select(NoteMention, InternalNote).join(
        InternalNote, NoteMention.note_id == InternalNote.id
    ).where(
        NoteMention.client_id == operator.client_id,
        NoteMention.operator_id == operator.id,
    )
    if unread_only:
        query = query.where(NoteMention.read_at.is_(None))
    rows = session.exec(query.order_by(NoteMention.id.desc()).limit(_bounded_limit(limit, default=50))).all()
    names = {
        row.id: _operator_name(row)
        for row in session.exec(select(Operator).where(Operator.client_id == operator.client_id)).all()
    }
    return [
        {
            "id": mention.id,
            "conversation_id": mention.conversation_id,
            "note_id": note.id,
            "body": note.body,
            "author": names.get(note.operator_id, "—"),
            "created_at": _iso(note.created_at),
            "read_at": _iso(mention.read_at),
        }
        for mention, note in rows
    ]


@router.post("/mentions/read")
def mark_mentions_read(
    mention_ids: list[int] = Body([], embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Mark the given mentions (or all of them, when the list is empty) as read."""
    query = select(NoteMention).where(
        NoteMention.client_id == operator.client_id,
        NoteMention.operator_id == operator.id,
        NoteMention.read_at.is_(None),
    )
    if mention_ids:
        query = query.where(NoteMention.id.in_(mention_ids))
    now = datetime.utcnow()
    rows = session.exec(query).all()
    for row in rows:
        row.read_at = now
        session.add(row)
    session.commit()
    return {"ok": True, "updated": len(rows)}


@router.post("/conversations/{conversation_id}/presence")
def conversation_presence(
    conversation_id: int,
    composing: bool = Body(False, embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Heartbeat sent while an operator has the conversation open. Returns the other operators
    currently on it, so the panel can warn before two people answer the same visitor."""
    _require_conversation(session, operator.client_id, conversation_id)
    entries = _conversation_presence.setdefault(conversation_id, {})
    entries[operator.id] = (_operator_name(operator), time.monotonic(), bool(composing))
    live = _prune_presence(conversation_id)
    others = [
        {"operator_id": op_id, "name": name, "composing": is_composing}
        for op_id, (name, _seen, is_composing) in live.items()
        if op_id != operator.id
    ]
    return {"others": others, "conflict": any(o["composing"] for o in others)}


@router.get("/conversations/{conversation_id}/activity")
def conversation_activity(
    conversation_id: int,
    limit: int = 50,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Audit trail of this conversation for its own tenant: who replied, re-routed, closed,
    annotated or deleted what, and when. Never exposed to the visitor."""
    _require_conversation(session, operator.client_id, conversation_id)
    rows = session.exec(
        select(AuditLog)
        .where(AuditLog.client_id == operator.client_id, AuditLog.target == f"conversation:{conversation_id}")
        .order_by(AuditLog.id.desc())
        .limit(_bounded_limit(limit, default=50))
    ).all()
    return [
        {
            "id": row.id,
            "action": row.action,
            "actor_type": row.actor_type,
            "actor": row.actor_id,
            "created_at": _iso(row.created_at),
            "detail": json.loads(row.detail) if row.detail else {},
        }
        for row in rows
    ]


SORT_MODES = ("recent", "oldest", "priority", "sla")


_PRIORITY_RANK = {"urgent": 3, "high": 2, "normal": 1, "low": 0}


def _inbox_order(sort: str) -> list:
    """ORDER BY clauses for one inbox ordering. Every mode ends on the conversation id so the
    result is stable when the leading key ties."""
    if sort == "oldest":
        return [Conversation.id.asc()]
    if sort == "priority":
        rank = case(_PRIORITY_RANK, value=Conversation.priority, else_=1)
        return [rank.desc(), Conversation.id.desc()]
    if sort == "sla":
        # nearest deadline first; conversations without an SLA go last
        deadline = func.least(Conversation.first_response_due_at, Conversation.resolution_due_at)
        return [deadline.asc().nullslast(), Conversation.id.desc()]
    return [Conversation.id.desc()]


INBOX_FILTER_KEYS = (
    "status", "priority", "department_id", "assigned_operator_id", "unassigned", "sla_state",
    "tag_id", "intent", "urgency", "conversation_language", "channel",
)


def _clean_inbox_filters(session: Session, client_id: int, raw: dict) -> dict:
    """Validate the filters of a saved view exactly like the query params of /conversations,
    including the tenant ownership of the referenced department/operator, so a view can never
    be stored (or shared) pointing at another tenant's data."""
    if not isinstance(raw, dict):
        raise HTTPException(400, "filters must be an object")
    unknown = set(raw) - set(INBOX_FILTER_KEYS)
    if unknown:
        raise HTTPException(400, f"unknown filter: {sorted(unknown)[0]}")
    clean: dict = {}
    status = raw.get("status")
    if status:
        if status not in ("open", "escalated", "closed"):
            raise HTTPException(400, "invalid status")
        clean["status"] = status
    priority = raw.get("priority")
    if priority:
        if priority not in PRIORITIES:
            raise HTTPException(400, "invalid priority")
        clean["priority"] = priority
    sla_state = raw.get("sla_state")
    if sla_state:
        if sla_state not in SLA_STATES:
            raise HTTPException(400, "invalid sla_state")
        clean["sla_state"] = sla_state
    department_id = raw.get("department_id")
    if department_id not in (None, ""):
        _require_department(session, client_id, int(department_id))
        clean["department_id"] = int(department_id)
    assigned_operator_id = raw.get("assigned_operator_id")
    if assigned_operator_id not in (None, ""):
        assignee = session.get(Operator, int(assigned_operator_id))
        if not assignee or assignee.client_id != client_id:
            raise HTTPException(404, "operator not found")
        clean["assigned_operator_id"] = int(assigned_operator_id)
    tag_id = raw.get("tag_id")
    if tag_id not in (None, ""):
        tag = session.get(Tag, int(tag_id))
        if not tag or tag.client_id != client_id:
            raise HTTPException(404, "tag not found")
        clean["tag_id"] = int(tag_id)
    intent = raw.get("intent")
    if intent:
        if intent not in llm_intents:
            raise HTTPException(400, "invalid intent")
        clean["intent"] = intent
    urgency = raw.get("urgency")
    if urgency:
        if urgency not in llm_urgencies:
            raise HTTPException(400, "invalid urgency")
        clean["urgency"] = urgency
    conversation_language = raw.get("conversation_language")
    if conversation_language:
        if conversation_language not in language.SUPPORTED:
            raise HTTPException(400, "invalid language")
        clean["conversation_language"] = conversation_language
    channel = raw.get("channel")
    if channel:
        if channel not in ("web", "email", "whatsapp", "messenger", "instagram"):
            raise HTTPException(400, "invalid channel")
        clean["channel"] = channel
    if raw.get("unassigned"):
        clean["unassigned"] = True
    return clean


def _saved_view_payload(view: SavedView, operator_names: dict, viewer_id: int | None = None) -> dict:
    return {
        "id": view.id,
        "name": view.name,
        "shared": view.shared,
        "filters": json.loads(view.filters) if view.filters else {},
        "sort": view.sort,
        "position": view.position,
        "operator_id": view.operator_id,
        "owner_name": operator_names.get(view.operator_id, ""),
        # only the owner can rename, share or delete it (see _own_saved_view)
        "mine": view.operator_id == viewer_id,
    }


@router.get("/saved-views")
def list_saved_views(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """Own views plus the ones shared inside the tenant."""
    views = session.exec(
        select(SavedView)
        .where(
            SavedView.client_id == operator.client_id,
            or_(SavedView.operator_id == operator.id, SavedView.shared.is_(True)),
        )
        .order_by(SavedView.position, SavedView.id)
    ).all()
    names = {
        row.id: _operator_name(row)
        for row in session.exec(select(Operator).where(Operator.client_id == operator.client_id)).all()
    }
    return [_saved_view_payload(view, names, operator.id) for view in views]


@router.post("/saved-views")
def create_saved_view(
    name: str = Body(...),
    filters: dict = Body({}),
    sort: str = Body("recent"),
    shared: bool = Body(False),
    position: int = Body(0),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    clean_name = name.strip()[:60]
    if not clean_name:
        raise HTTPException(400, "name required")
    if sort not in SORT_MODES:
        raise HTTPException(400, "invalid sort")
    clean_filters = _clean_inbox_filters(session, operator.client_id, filters or {})
    view = SavedView(
        client_id=operator.client_id,
        operator_id=operator.id,
        name=clean_name,
        shared=shared,
        filters=json.dumps(clean_filters),
        sort=sort,
        position=position,
    )
    session.add(view)
    session.commit()
    session.refresh(view)
    return _saved_view_payload(view, {operator.id: _operator_name(operator)}, operator.id)


def _own_saved_view(session: Session, operator: Operator, view_id: int) -> SavedView:
    """Only the owner may change or delete a view, even when it is shared with the tenant."""
    view = session.get(SavedView, view_id)
    if not view or view.client_id != operator.client_id:
        raise HTTPException(404, "saved view not found")
    if view.operator_id != operator.id:
        raise HTTPException(403, "not the owner of this view")
    return view


@router.patch("/saved-views/{view_id}")
def update_saved_view(
    view_id: int,
    name: str | None = Body(None),
    filters: dict | None = Body(None),
    sort: str | None = Body(None),
    shared: bool | None = Body(None),
    position: int | None = Body(None),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    view = _own_saved_view(session, operator, view_id)
    if name is not None:
        clean_name = name.strip()[:60]
        if not clean_name:
            raise HTTPException(400, "name required")
        view.name = clean_name
    if sort is not None:
        if sort not in SORT_MODES:
            raise HTTPException(400, "invalid sort")
        view.sort = sort
    if filters is not None:
        view.filters = json.dumps(_clean_inbox_filters(session, operator.client_id, filters))
    if shared is not None:
        view.shared = shared
    if position is not None:
        view.position = position
    view.updated_at = datetime.utcnow()
    session.add(view)
    session.commit()
    return _saved_view_payload(view, {operator.id: _operator_name(operator)}, operator.id)


@router.delete("/saved-views/{view_id}")
def delete_saved_view(
    view_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    view = _own_saved_view(session, operator, view_id)
    session.delete(view)
    session.commit()
    return {"ok": True}


@router.post("/conversations/{conversation_id}/typing")
def operator_typing(conversation_id: int, operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """Panel pings this while the operator is typing; the widget's poll shows '<name> sta scrivendo'."""
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id:
        raise HTTPException(404, "conversation not found")
    _operator_typing[conversation_id] = (_operator_name(operator), time.monotonic())
    return {"ok": True}


@router.get("/conversations/{conversation_id}/messages")
def conversation_messages(
    conversation_id: int,
    after_id: int = 0,
    limit: int = 200,
    conversation_token: str | None = Header(None, alias="X-Conversation-Token"),
    authorization: str = Header(None),
    session: Session = Depends(get_session),
):
    """Polled by the chat widget (client api_key) and read by the panel (operator token)."""
    bearer = _bearer_token(authorization)
    op_session = _get_operator_session(session, bearer)
    client_id = op_session.client_id if op_session else get_client(bearer, session).id
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != client_id:
        raise HTTPException(404, "conversation not found")
    if not op_session:
        _require_conversation_token(conv, conversation_token)
    messages = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.id > after_id)
        .order_by(Message.id)
        .limit(_bounded_limit(limit, default=200))
    ).all()
    message_ids = [message.id for message in messages if message.id is not None]
    attachment_rows = session.exec(
        select(Attachment).where(Attachment.message_id.in_(message_ids)).order_by(Attachment.id)
    ).all() if message_ids else []
    attachments_by_message: dict[int, list[dict]] = {}
    for attachment in attachment_rows:
        attachments_by_message.setdefault(attachment.message_id, []).append({
            "id": attachment.id,
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "size_bytes": attachment.size_bytes,
        })
    typing = _operator_typing.get(conversation_id)
    operator_typing_name = typing[0] if typing and (time.monotonic() - typing[1]) < TYPING_TTL else None
    rated = session.exec(
        select(ConversationRating).where(ConversationRating.conversation_id == conversation_id)
    ).first() is not None
    return {
        "status": conv.status,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "attachments": attachments_by_message.get(m.id, []),
            }
            for m in messages
        ],
        "operator_typing": operator_typing_name,
        # lets the widget ask for a CSAT rating only once (no internal data exposed)
        "rated": rated,
    }


@router.get("/conversations")
def list_conversations(
    before_id: int | None = None,
    limit: int = 100,
    status: str | None = None,
    priority: str | None = None,
    department_id: int | None = None,
    assigned_operator_id: int | None = None,
    unassigned: bool = False,
    sla_state: str | None = None,
    tag_id: int | None = None,
    intent: str | None = None,
    urgency: str | None = None,
    conversation_language: str | None = None,
    channel: str | None = None,
    sort: str = "recent",
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """The operator inbox. `before_id` paginates the id-ordered modes (recent/oldest); the
    priority and sla orderings are meant for the first page of a working queue."""
    if sort not in SORT_MODES:
        raise HTTPException(400, "invalid sort")
    now = datetime.utcnow()
    query = select(Conversation).where(Conversation.client_id == operator.client_id)
    if channel:
        if channel not in ("web", "email", "whatsapp", "messenger", "instagram"):
            raise HTTPException(400, "invalid channel")
        query = query.where(Conversation.channel == channel)
    if status:
        if status not in ("open", "escalated", "closed"):
            raise HTTPException(400, "invalid status")
        query = query.where(Conversation.status == status)
    if priority:
        if priority not in ("low", "normal", "high", "urgent"):
            raise HTTPException(400, "invalid priority")
        query = query.where(Conversation.priority == priority)
    if department_id is not None:
        department = session.get(Department, department_id)
        if not department or department.client_id != operator.client_id:
            raise HTTPException(404, "department not found")
        query = query.where(Conversation.department_id == department_id)
    if assigned_operator_id is not None:
        assignee = session.get(Operator, assigned_operator_id)
        if not assignee or assignee.client_id != operator.client_id:
            raise HTTPException(404, "operator not found")
        query = query.where(Conversation.assigned_operator_id == assigned_operator_id)
    if unassigned:
        query = query.where(Conversation.assigned_operator_id.is_(None))
    if sla_state:
        if sla_state not in SLA_STATES:
            raise HTTPException(400, "invalid sla_state")
        query = _filter_by_sla_state(query, sla_state, now)
    if tag_id is not None:
        tag = session.get(Tag, tag_id)
        if not tag or tag.client_id != operator.client_id:
            raise HTTPException(404, "tag not found")
        query = query.where(
            Conversation.id.in_(
                select(ConversationTag.conversation_id).where(ConversationTag.tag_id == tag_id)
            )
        )
    if intent:
        if intent not in llm_intents:
            raise HTTPException(400, "invalid intent")
        query = query.where(Conversation.ai_intent == intent)
    if urgency:
        if urgency not in llm_urgencies:
            raise HTTPException(400, "invalid urgency")
        query = query.where(Conversation.ai_urgency == urgency)
    if conversation_language:
        if conversation_language not in language.SUPPORTED:
            raise HTTPException(400, "invalid language")
        query = query.where(Conversation.language == conversation_language)
    if before_id:
        query = query.where(Conversation.id < before_id)
    convs = session.exec(
        query.order_by(*_inbox_order(sort)).limit(_bounded_limit(limit))
    ).all()
    tags_by_conversation = tagging.conversation_tags(session, [c.id for c in convs], operator.client_id)
    ratings_by_conversation = {
        r.conversation_id: r
        for r in session.exec(
            select(ConversationRating).where(
                ConversationRating.client_id == operator.client_id,
                ConversationRating.conversation_id.in_([c.id for c in convs] or [0]),
            )
        ).all()
    }
    result = []
    for c in convs:
        last = session.exec(
            select(Message).where(Message.conversation_id == c.id).order_by(Message.id.desc())
        ).first()
        assignee = session.get(Operator, c.assigned_operator_id) if c.assigned_operator_id else None
        department = session.get(Department, c.department_id) if c.department_id else None
        result.append({
            "conversation": c,
            "last_message": last.content if last else None,
            "assignee": {"id": assignee.id, "name": _operator_name(assignee)} if assignee else None,
            "department": {"id": department.id, "name": department.name} if department else None,
            "sla": _sla_view(c, now),
            "tags": tags_by_conversation.get(c.id, []),
            "classification": tagging.classification_payload(c),
            "rating": _rating_payload(ratings_by_conversation.get(c.id)),
        })
    return result


@router.patch("/conversations/{conversation_id}/routing")
def update_conversation_routing(
    conversation_id: int,
    priority: str | None = Body(None),
    assigned_operator_id: int | None = Body(None),
    department_id: int | None = Body(None),
    clear_assignee: bool = Body(False),
    clear_department: bool = Body(False),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id:
        raise HTTPException(404, "conversation not found")
    previous_assignee_id = conv.assigned_operator_id
    if priority is not None:
        if priority not in ("low", "normal", "high", "urgent"):
            raise HTTPException(400, "invalid priority")
        conv.priority = priority
    if clear_assignee:
        conv.assigned_operator_id = None
    elif assigned_operator_id is not None:
        assignee = session.get(Operator, assigned_operator_id)
        if not assignee or assignee.client_id != operator.client_id:
            raise HTTPException(404, "operator not found")
        conv.assigned_operator_id = assignee.id
    if clear_department:
        conv.department_id = None
    elif department_id is not None:
        department = session.get(Department, department_id)
        if not department or department.client_id != operator.client_id:
            raise HTTPException(404, "department not found")
        conv.department_id = department.id
    # a running SLA follows the new priority/department: re-match the policy and move the
    # deadlines, still measured from the moment the conversation needed a human
    _apply_sla(session, conv)
    conv.updated_at = datetime.utcnow()
    session.add(conv)
    session.commit()
    if conv.assigned_operator_id and conv.assigned_operator_id != previous_assignee_id:
        push_service.send(
            session, operator.client_id, "assignment",
            title="Conversazione assegnata",
            body=f"La conversazione #{conv.id} è stata assegnata a te.",
            conversation_id=conv.id, operator_ids=[conv.assigned_operator_id],
        )
    _audit(
        session, "operator", operator.email, "conversation.routing",
        target=f"conversation:{conversation_id}", client_id=operator.client_id,
        detail={
            "priority": conv.priority,
            "assigned_operator_id": conv.assigned_operator_id,
            "department_id": conv.department_id,
            "sla_policy_id": conv.sla_policy_id,
        },
    )
    return {"ok": True, "sla": _sla_view(conv)}


@router.get("/tickets")
def list_tickets(
    status: str = "open",
    before_id: int | None = None,
    limit: int = 100,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    query = (
        select(Ticket, Conversation)
        .join(Conversation, Ticket.conversation_id == Conversation.id)
        .where(Conversation.client_id == operator.client_id, Ticket.status == status)
    )
    if before_id:
        query = query.where(Ticket.id < before_id)
    tickets = session.exec(
        query.order_by(Ticket.id.desc()).limit(_bounded_limit(limit))
    ).all()
    ticket_ids = [t.id for t, _ in tickets]
    exports = session.exec(
        select(HelpdeskExport, HelpdeskConnection)
        .join(HelpdeskConnection, HelpdeskExport.connection_id == HelpdeskConnection.id)
        .where(
            HelpdeskExport.client_id == operator.client_id,
            HelpdeskExport.ticket_id.in_(ticket_ids),
        )
    ).all() if ticket_ids else []
    exports_by_ticket: dict[int, dict] = {}
    for export, connection in exports:
        exports_by_ticket.setdefault(export.ticket_id, {})[connection.provider] = _helpdesk_export_payload(export)
    return [
        {"ticket": t, "conversation": c, "helpdesk_exports": exports_by_ticket.get(t.id, {})}
        for t, c in tickets
    ]


@router.post("/tickets/{ticket_id}/reply")
def reply_ticket(ticket_id: int, reply: str, operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    ticket = session.get(Ticket, ticket_id)
    conv = session.get(Conversation, ticket.conversation_id) if ticket else None
    # verify the ticket belongs to this operator's client before replying as the operator
    if not ticket or not conv or conv.client_id != operator.client_id:
        raise HTTPException(404, "ticket not found")
    if conv.channel == "whatsapp" and not _whatsapp_channel_status(session, conv)["window_open"]:
        raise HTTPException(409, "WhatsApp 24-hour window expired; use an approved template")
    session.add(Message(conversation_id=ticket.conversation_id, role="operator", content=reply))
    now = datetime.utcnow()
    if conv.assigned_operator_id is None:
        conv.assigned_operator_id = operator.id
    if conv.first_response_at is None:
        conv.first_response_at = now  # stops the SLA first-response target
    ticket.status = "answered"
    ticket.updated_at = now
    conv.status = "open"
    conv.updated_at = now
    session.add(ticket)
    session.add(conv)
    session.commit()
    _audit(session, "operator", operator.email, "ticket.reply", target=f"ticket:{ticket_id}", client_id=operator.client_id)
    delivered = _notify_visitor_reply(session, operator.client_id, conv)
    return {"ok": True, "delivered": delivered}


@router.post("/conversations/{conversation_id}/reply")
def reply_conversation(
    conversation_id: int,
    reply: str = Body(..., embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Operator replies directly from the Conversations view (works for any conversation, not
    just ticketed ones). Adds the operator message, reopens the conversation, closes any open
    ticket on it, and notifies the visitor by email if they left one."""
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id:
        raise HTTPException(404, "conversation not found")
    if conv.channel == "whatsapp" and not _whatsapp_channel_status(session, conv)["window_open"]:
        raise HTTPException(409, "WhatsApp 24-hour window expired; use an approved template")
    session.add(Message(conversation_id=conversation_id, role="operator", content=reply))
    now = datetime.utcnow()
    if conv.assigned_operator_id is None:
        conv.assigned_operator_id = operator.id
    if conv.first_response_at is None:
        conv.first_response_at = now  # stops the SLA first-response target
    conv.status = "open"
    conv.updated_at = now
    session.add(conv)
    for t in session.exec(
        select(Ticket).where(Ticket.conversation_id == conversation_id, Ticket.status == "open")
    ).all():
        t.status = "answered"
        t.updated_at = now
        session.add(t)
    session.commit()
    _audit(session, "operator", operator.email, "conversation.reply", target=f"conversation:{conversation_id}", client_id=operator.client_id)
    delivered = _notify_visitor_reply(session, operator.client_id, conv)
    events.emit(session, operator.client_id, "conversation.replied", {
        "conversation_id": conv.id, "via": "panel", "operator": _operator_name(operator),
    }, conv=conv)
    return {"ok": True, "delivered": delivered}


@router.post("/conversations/{conversation_id}/status")
def set_conversation_status(
    conversation_id: int,
    status: str = Body(..., embed=True),  # "closed" | "open"
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Operator marks a conversation as closed (resolved/archived) or reopens it. A new visitor
    message auto-reopens a closed conversation."""
    if status not in ("open", "closed"):
        raise HTTPException(400, "status must be 'open' or 'closed'")
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id:
        raise HTTPException(404, "conversation not found")
    now = datetime.utcnow()
    conv.status = status
    conv.updated_at = now
    conv.closed_at = now if status == "closed" else None
    session.add(conv)
    session.commit()
    _audit(session, "operator", operator.email, f"conversation.{status}", target=f"conversation:{conversation_id}", client_id=operator.client_id)
    if status == "closed":
        events.emit(session, operator.client_id, "conversation.closed", {"conversation_id": conv.id}, conv=conv)
    return {"ok": True, "status": status}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """GDPR erasure: permanently delete a conversation and its messages/tickets/AI logs."""
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id:
        raise HTTPException(404, "conversation not found")
    _erase_conversation(session, conv)
    session.commit()
    _audit(session, "operator", operator.email, "conversation.delete", target=f"conversation:{conversation_id}", client_id=operator.client_id)
    return {"ok": True}


@router.post("/gdpr/erase")
def gdpr_erase(email: str = Body(..., embed=True), operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """GDPR right-to-be-forgotten: delete every conversation of this client that a visitor
    left under the given email (visitor_email captured on escalation)."""
    convs = session.exec(
        select(Conversation).where(Conversation.client_id == operator.client_id, Conversation.visitor_email == email)
    ).all()
    for conv in convs:
        _erase_conversation(session, conv)
    session.commit()
    _audit(session, "operator", operator.email, "gdpr.erase", target=email, client_id=operator.client_id, detail={"deleted": len(convs)})
    return {"ok": True, "deleted": len(convs)}


@router.post("/gdpr/export")
def gdpr_export(email: str = Body(..., embed=True), operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """GDPR data portability: export visitor data known under an email, tenant-scoped.

    Internal model diagnostics and secrets are intentionally excluded; the export contains
    the visitor profile data, conversation metadata, messages and related support tickets.
    """
    normalized_email = email.strip().lower()
    if not normalized_email or len(normalized_email) > 320 or "@" not in normalized_email:
        raise HTTPException(400, "valid email required")
    convs = session.exec(
        select(Conversation)
        .where(
            Conversation.client_id == operator.client_id,
            func.lower(Conversation.visitor_email) == normalized_email,
        )
        .order_by(Conversation.created_at)
    ).all()
    exported = []
    for conv in convs:
        messages = session.exec(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at, Message.id)
        ).all()
        tickets = session.exec(
            select(Ticket).where(Ticket.conversation_id == conv.id).order_by(Ticket.created_at, Ticket.id)
        ).all()
        exported.append({
            "conversation": {
                "id": conv.id,
                "visitor_id": conv.visitor_id,
                "visitor_email": conv.visitor_email,
                "visitor_url": conv.visitor_url,
                "status": conv.status,
                "info": json.loads(conv.info) if conv.info else {},
                "created_at": _iso(conv.created_at),
                "updated_at": _iso(conv.updated_at),
                "closed_at": _iso(conv.closed_at),
            },
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                    "created_at": _iso(message.created_at),
                    "feedback": message.feedback,
                }
                for message in messages
            ],
            "tickets": [
                {
                    "reason": ticket.reason,
                    "status": ticket.status,
                    "created_at": _iso(ticket.created_at),
                    "updated_at": _iso(ticket.updated_at),
                }
                for ticket in tickets
            ],
            # the visitor's own CSAT rating is their data too; internal notes are not
            "rating": _rating_payload(
                session.exec(
                    select(ConversationRating).where(ConversationRating.conversation_id == conv.id)
                ).first()
            ),
        })
    _audit(
        session,
        "operator",
        operator.email,
        "gdpr.export",
        target=normalized_email,
        client_id=operator.client_id,
        detail={"conversations": len(exported)},
    )
    return {
        "exported_at": _iso(datetime.utcnow()),
        "email": normalized_email,
        "conversations": exported,
    }

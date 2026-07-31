"""Tags and AI classification of conversations.

Shared by the API (manual tagging + "classifica ora") and the background worker (automatic
classification after an escalation), so both paths behave identically.

The classification is **advisory**: nothing in routing, SLA or billing reads it. Every failure
mode — provider down, unparseable answer, unknown category — leaves the conversation exactly as
it was, because a wrong label is worse than no label.
"""

import logging
import os

from sqlmodel import Session, select

from .db import Conversation, ConversationTag, Message, Tag
from .llm import LLMUnavailableError, classify
from .logging_config import log

logger = logging.getLogger("wpai.tagging")

AI_CLASSIFY_ENABLED = os.getenv("AI_CLASSIFY_ENABLED", "true").lower() == "true"
MAX_TAG_CHARS = 40
# upper bound on how many distinct tags one tenant can accumulate; the AI classifier reuses
# existing tags, this only stops a pathological loop from filling the table
MAX_TAGS_PER_CLIENT = int(os.getenv("MAX_TAGS_PER_CLIENT", "200"))
# how much of the conversation is sent to the classifier
CLASSIFY_MAX_MESSAGES = int(os.getenv("CLASSIFY_MAX_MESSAGES", "12"))
CLASSIFY_MAX_CHARS = int(os.getenv("CLASSIFY_MAX_CHARS", "4000"))


def clean_tag_name(name: str) -> str:
    return " ".join((name or "").split())[:MAX_TAG_CHARS]


def find_tag(session: Session, client_id: int, name: str) -> Tag | None:
    """Case-insensitive lookup inside the tenant."""
    wanted = clean_tag_name(name).lower()
    if not wanted:
        return None
    for tag in session.exec(select(Tag).where(Tag.client_id == client_id)).all():
        if tag.name.lower() == wanted:
            return tag
    return None


def get_or_create_tag(session: Session, client_id: int, name: str, source: str = "manual") -> Tag | None:
    """Return the tenant's tag with this name, creating it if needed. None when the name is
    empty or the tenant hit the tag ceiling."""
    clean = clean_tag_name(name)
    if not clean:
        return None
    existing = find_tag(session, client_id, clean)
    if existing:
        return existing
    total = len(session.exec(select(Tag).where(Tag.client_id == client_id)).all())
    if total >= MAX_TAGS_PER_CLIENT:
        log(logger, logging.WARNING, "tag.limit_reached", client_id=client_id, limit=MAX_TAGS_PER_CLIENT)
        return None
    tag = Tag(client_id=client_id, name=clean, source=source)
    session.add(tag)
    session.commit()
    session.refresh(tag)
    return tag


def attach_tag(session: Session, conv: Conversation, tag: Tag, source: str = "manual") -> ConversationTag:
    """Idempotent: attaching a tag twice keeps the first association."""
    existing = session.exec(
        select(ConversationTag).where(
            ConversationTag.conversation_id == conv.id, ConversationTag.tag_id == tag.id
        )
    ).first()
    if existing:
        return existing
    link = ConversationTag(
        client_id=conv.client_id, conversation_id=conv.id, tag_id=tag.id, source=source
    )
    session.add(link)
    session.commit()
    session.refresh(link)
    return link


def conversation_tags(session: Session, conversation_ids: list[int], client_id: int) -> dict[int, list[dict]]:
    """Tags of several conversations at once, for the inbox list."""
    if not conversation_ids:
        return {}
    links = session.exec(
        select(ConversationTag, Tag)
        .join(Tag, ConversationTag.tag_id == Tag.id)
        .where(
            ConversationTag.client_id == client_id,
            ConversationTag.conversation_id.in_(conversation_ids),
        )
        .order_by(ConversationTag.id)
    ).all()
    out: dict[int, list[dict]] = {}
    for link, tag in links:
        out.setdefault(link.conversation_id, []).append(
            {"id": tag.id, "name": tag.name, "color": tag.color, "source": link.source}
        )
    return out


def build_transcript(session: Session, conv: Conversation) -> str:
    """The last messages of the conversation, roles included, bounded in size."""
    messages = session.exec(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.id.desc())
        .limit(CLASSIFY_MAX_MESSAGES)
    ).all()
    lines = [f"{m.role}: {m.content}" for m in reversed(messages)]
    return "\n".join(lines)[:CLASSIFY_MAX_CHARS]


def classify_conversation(session: Session, conv: Conversation) -> dict | None:
    """Classify one conversation and store the result (plus a topic tag). Returns the applied
    classification, or None when nothing usable came back. Never raises: a classification
    failure must not affect the conversation."""
    transcript = build_transcript(session, conv)
    if not transcript.strip():
        return None
    try:
        result = classify(transcript)
    except LLMUnavailableError as exc:
        log(
            logger, logging.WARNING, "classify.unavailable",
            client_id=conv.client_id, conversation_id=conv.id, error=str(exc)[:200],
        )
        return None
    except Exception as exc:  # noqa: BLE001 — classification is best-effort
        log(
            logger, logging.WARNING, "classify.failed",
            client_id=conv.client_id, conversation_id=conv.id, error=str(exc)[:200],
        )
        return None
    if not result:
        log(logger, logging.INFO, "classify.unusable_answer", client_id=conv.client_id, conversation_id=conv.id)
        return None
    from datetime import datetime  # local import: keeps the module's public surface small

    conv.ai_intent = result.get("intent", "")
    conv.ai_topic = result.get("topic", "")
    conv.ai_urgency = result.get("urgency", "")
    conv.ai_classified_at = datetime.utcnow()
    session.add(conv)
    session.commit()
    if conv.ai_topic:
        tag = get_or_create_tag(session, conv.client_id, conv.ai_topic, source="ai")
        if tag:
            attach_tag(session, conv, tag, source="ai")
    log(
        logger, logging.INFO, "classify.applied",
        client_id=conv.client_id, conversation_id=conv.id,
        intent=conv.ai_intent, urgency=conv.ai_urgency,
    )
    # local import: events → workflows → tagging would be a cycle at module level
    from . import events

    events.emit(session, conv.client_id, "conversation.classified", {
        "conversation_id": conv.id, "intent": conv.ai_intent,
        "topic": conv.ai_topic, "urgency": conv.ai_urgency,
    }, conv=conv)
    return {
        "intent": conv.ai_intent,
        "topic": conv.ai_topic,
        "urgency": conv.ai_urgency,
        "model": result.get("model", ""),
    }


def classification_payload(conv: Conversation) -> dict | None:
    if not conv.ai_classified_at:
        return None
    return {
        "intent": conv.ai_intent,
        "topic": conv.ai_topic,
        "urgency": conv.ai_urgency,
        "classified_at": conv.ai_classified_at.isoformat() + "Z",
    }

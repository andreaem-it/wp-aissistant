"""Advanced analytics: outcome metrics over a period, and knowledge-base gap detection.

Two ideas shape this module:

- **Conversation-level, not turn-level.** `/stats` already counts AI turns. What a customer
  actually asks is "how many conversations did the assistant handle without me?" — that is
  deflection, and it can only be answered per conversation.
- **Derive, don't store.** A knowledge gap is a question that the retrieval couldn't serve
  *given the knowledge base at the time we look*. Recomputing it from the AI logs means the
  list shrinks by itself as content is added; only the operator's decision is persisted
  (see KnowledgeGapReview).
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_
from sqlmodel import Session, select

from .db import (
    AiResponseLog,
    Conversation,
    ConversationRating,
    KnowledgeGapReview,
    Message,
)
from .logging_config import log

logger = logging.getLogger("wpai.analytics")

# A retrieval this far from the question carried no usable context. Same default as the chat
# scope guard, so "the AI had nothing to work with" means the same thing in both places.
GAP_MAX_DISTANCE = float(os.getenv("SCOPE_MAX_DISTANCE", "0.62"))
# The AI itself decided it couldn't answer. Deliberately narrow: a keyword escalation
# (rimborso, reclamo) is intentional routing, and escalated_llm_down is a provider outage —
# neither says anything about the knowledge base.
GAP_OUTCOMES = ("escalated_model",)
MAX_QUESTION_CHARS = 300


def normalize_question(text: str) -> str:
    """Same question modulo spacing, case and trailing punctuation."""
    clean = re.sub(r"\s+", " ", (text or "").strip().lower())
    return clean.rstrip("?!. ")


def question_hash(text: str) -> str:
    return hashlib.sha256(normalize_question(text).encode()).hexdigest()[:32]


def _period(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=max(1, min(days, 365)))


# ---- outcome metrics ----------------------------------------------------------------------


def _conversation_ids_with_operator(session: Session, client_id: int, since: datetime) -> set[int]:
    rows = session.exec(
        select(Message.conversation_id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.client_id == client_id,
            Conversation.created_at >= since,
            Message.role == "operator",
        )
        .distinct()
    ).all()
    return {row for row in rows}


def overview(session: Session, client_id: int, days: int = 30) -> dict:
    """Deflection, resolution and response times over the period."""
    since = _period(days)
    conversations = session.exec(
        select(Conversation).where(
            Conversation.client_id == client_id, Conversation.created_at >= since
        )
    ).all()
    total = len(conversations)
    with_operator = _conversation_ids_with_operator(session, client_id, since)
    handled_by_ai = [c for c in conversations if c.id not in with_operator]
    escalated = [c for c in conversations if c.status == "escalated" or c.id in with_operator]
    closed = [c for c in conversations if c.closed_at is not None]

    def _seconds(pairs) -> dict:
        """Average and median of a list of (start, end) datetimes, in minutes."""
        deltas = sorted((end - start).total_seconds() for start, end in pairs if start and end)
        if not deltas:
            return {"average_minutes": None, "median_minutes": None, "count": 0}
        middle = len(deltas) // 2
        median = deltas[middle] if len(deltas) % 2 else (deltas[middle - 1] + deltas[middle]) / 2
        return {
            "average_minutes": round(sum(deltas) / len(deltas) / 60, 1),
            "median_minutes": round(median / 60, 1),
            "count": len(deltas),
        }

    first_response = _seconds([(c.sla_started_at, c.first_response_at) for c in conversations])
    resolution = _seconds([(c.created_at, c.closed_at) for c in conversations])

    rating_rows = session.exec(
        select(func.avg(ConversationRating.score), func.count()).where(
            ConversationRating.client_id == client_id, ConversationRating.created_at >= since
        )
    ).one()
    average_rating, rating_count = rating_rows

    return {
        "period_days": days,
        "conversations": total,
        # share of conversations that never needed a human — the number that justifies the tool
        "deflection_rate": round(len(handled_by_ai) / total, 3) if total else None,
        "handled_by_ai": len(handled_by_ai),
        "escalated": len(escalated),
        "closed": len(closed),
        "first_response": first_response,
        "resolution": resolution,
        "csat": {
            "average": round(float(average_rating), 2) if average_rating is not None else None,
            "responses": int(rating_count or 0),
        },
    }


def trend(session: Session, client_id: int, days: int = 30) -> list[dict]:
    """Daily series: conversations, escalations and AI answers."""
    since = _period(days)
    day = func.date(Conversation.created_at)
    conversation_rows = session.exec(
        select(day, func.count())
        .where(Conversation.client_id == client_id, Conversation.created_at >= since)
        .group_by(day)
        .order_by(day)
    ).all()
    escalated_rows = session.exec(
        select(day, func.count())
        .where(
            Conversation.client_id == client_id,
            Conversation.created_at >= since,
            Conversation.sla_started_at.is_not(None),
        )
        .group_by(day)
        .order_by(day)
    ).all()
    log_day = func.date(AiResponseLog.created_at)
    answered_rows = session.exec(
        select(log_day, func.count())
        .where(
            AiResponseLog.client_id == client_id,
            AiResponseLog.created_at >= since,
            AiResponseLog.outcome == "answered",
        )
        .group_by(log_day)
        .order_by(log_day)
    ).all()
    escalated_by_day = {str(d): int(n) for d, n in escalated_rows}
    answered_by_day = {str(d): int(n) for d, n in answered_rows}
    return [
        {
            "date": str(d),
            "conversations": int(n),
            "escalated": escalated_by_day.get(str(d), 0),
            "ai_answers": answered_by_day.get(str(d), 0),
        }
        for d, n in conversation_rows
    ]


# ---- knowledge gaps -----------------------------------------------------------------------


def _best_distance(retrieved_json: str) -> float | None:
    try:
        retrieved = json.loads(retrieved_json or "[]")
    except ValueError:
        return None
    distances = [r.get("distance") for r in retrieved if isinstance(r, dict) and r.get("distance") is not None]
    return min(distances) if distances else None


def _question_for(session: Session, log_row: AiResponseLog) -> str:
    """The visitor message this AI turn was answering: the last user message written no later
    than the log entry."""
    message = session.exec(
        select(Message)
        .where(
            Message.conversation_id == log_row.conversation_id,
            Message.role == "user",
            Message.created_at <= log_row.created_at,
        )
        .order_by(Message.id.desc())
    ).first()
    return (message.content if message else "").strip()[:MAX_QUESTION_CHARS]


def knowledge_gaps(
    session: Session,
    client_id: int,
    days: int = 30,
    limit: int = 20,
    include_reviewed: bool = False,
) -> dict:
    """Questions the knowledge base could not serve, grouped by normalised question.

    A turn counts as a gap when the AI escalated for lack of context, or answered with nothing
    close enough in the knowledge base, or the visitor marked the answer as unhelpful.
    """
    since = _period(days)
    logs = session.exec(
        select(AiResponseLog)
        .where(AiResponseLog.client_id == client_id, AiResponseLog.created_at >= since)
        .order_by(AiResponseLog.id.desc())
        .limit(2000)  # bounded scan: the newest turns are the ones worth acting on
    ).all()

    negative_message_ids = {
        row for row in session.exec(
            select(Message.id)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Conversation.client_id == client_id,
                Message.feedback == -1,
                Message.created_at >= since,
            )
        ).all()
    }
    reviewed = {
        row.question_hash
        for row in session.exec(
            select(KnowledgeGapReview).where(KnowledgeGapReview.client_id == client_id)
        ).all()
    }

    groups: dict[str, dict] = {}
    for row in logs:
        distance = _best_distance(row.retrieved)
        thumbs_down = row.message_id is not None and row.message_id in negative_message_ids
        no_context = distance is None or distance > GAP_MAX_DISTANCE
        # An answered turn with no close context is usually small talk, which the scope guard
        # allows on purpose — only a thumbs-down makes it a gap.
        if not (thumbs_down or (row.outcome in GAP_OUTCOMES and no_context)):
            continue
        question = _question_for(session, row)
        if not question:
            continue
        digest = question_hash(question)
        if not include_reviewed and digest in reviewed:
            continue
        group = groups.setdefault(digest, {
            "question_hash": digest,
            "question": question,
            "occurrences": 0,
            "conversation_ids": [],
            "last_seen": None,
            "best_distance": None,
            "negative_feedback": 0,
            "reviewed": digest in reviewed,
        })
        group["occurrences"] += 1
        if len(group["conversation_ids"]) < 5:
            group["conversation_ids"].append(row.conversation_id)
        stamp = row.created_at.isoformat() + "Z"
        if group["last_seen"] is None or stamp > group["last_seen"]:
            group["last_seen"] = stamp
        if distance is not None and (group["best_distance"] is None or distance < group["best_distance"]):
            group["best_distance"] = round(distance, 3)
        if thumbs_down:
            group["negative_feedback"] += 1

    ranked = sorted(groups.values(), key=lambda g: (-g["occurrences"], g["last_seen"] or ""))
    topics = session.exec(
        select(Conversation.ai_topic, func.count())
        .where(
            Conversation.client_id == client_id,
            Conversation.created_at >= since,
            Conversation.ai_topic != "",
            or_(
                Conversation.status == "escalated",
                and_(Conversation.ai_urgency == "alta", Conversation.closed_at.is_(None)),
            ),
        )
        .group_by(Conversation.ai_topic)
        .order_by(func.count().desc())
        .limit(10)
    ).all()
    return {
        "period_days": days,
        "gaps": ranked[:limit],
        "total": len(ranked),
        "by_topic": [{"topic": topic, "conversations": int(n)} for topic, n in topics],
    }


def review_gap(
    session: Session, client_id: int, question: str, status: str, operator_email: str = ""
) -> KnowledgeGapReview:
    """Record that a gap was handled (taught) or dismissed (ignored). Idempotent per question."""
    digest = question_hash(question)
    existing = session.exec(
        select(KnowledgeGapReview).where(
            KnowledgeGapReview.client_id == client_id,
            KnowledgeGapReview.question_hash == digest,
        )
    ).first()
    if existing:
        existing.status = status
        existing.operator_email = operator_email
        session.add(existing)
        session.commit()
        return existing
    review = KnowledgeGapReview(
        client_id=client_id,
        question_hash=digest,
        question=(question or "").strip()[:MAX_QUESTION_CHARS],
        status=status,
        operator_email=operator_email,
    )
    session.add(review)
    session.commit()
    session.refresh(review)
    log(logger, logging.INFO, "analytics.gap_reviewed", client_id=client_id, status=status)
    return review

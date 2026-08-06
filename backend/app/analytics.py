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
import unicodedata
from datetime import datetime, timedelta

from sqlalchemy import and_, column, func, or_
from sqlmodel import Session, select

from .db import (
    AiResponseLog,
    Conversation,
    ConversationRating,
    ConversationTag,
    KnowledgeGapReview,
    Message,
    Tag,
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
GAP_CLUSTER_SIMILARITY = float(os.getenv("GAP_CLUSTER_SIMILARITY", "0.5"))

# Privacy-first semantic concepts. Clustering runs locally and never sends visitor questions
# to another provider. Prefixes intentionally cover common Italian inflections.
GAP_CONCEPTS = {
    "shipping": ("sped", "consegn", "ricev", "recapit", "ordine"),
    "international": ("ester", "svizzer", "fuori", "italia", "internazional"),
    "returns": ("reso", "restitu", "rimbor"),
    "payments": ("pag", "carta", "paypal", "bonifico"),
    "installments": ("rata", "rateal", "dilazion"),
    "availability": ("disponib", "magazz", "stock"),
    "warranty": ("garanzia", "guasto", "ripar"),
}


def normalize_question(text: str) -> str:
    """Same question modulo spacing, case and trailing punctuation."""
    clean = re.sub(r"\s+", " ", (text or "").strip().lower())
    return clean.rstrip("?!. ")


def question_hash(text: str) -> str:
    return hashlib.sha256(normalize_question(text).encode()).hexdigest()[:32]


def semantic_terms(text: str) -> set[str]:
    """Compact local representation: normalized words plus domain concepts."""
    plain = unicodedata.normalize("NFKD", normalize_question(text)).encode("ascii", "ignore").decode()
    words = {word for word in re.findall(r"[a-z0-9]+", plain) if len(word) >= 4}
    concepts = {
        f"concept:{concept}"
        for concept, prefixes in GAP_CONCEPTS.items()
        if any(word.startswith(prefix) for word in words for prefix in prefixes)
    }
    return words | concepts


def semantic_similarity(left: str, right: str) -> float:
    a, b = semantic_terms(left), semantic_terms(right)
    if not a or not b:
        return 0.0
    concept_overlap = {term for term in a & b if term.startswith("concept:")}
    if len(concept_overlap) >= 2:
        return 1.0
    return len(a & b) / len(a | b)


def cluster_gap_groups(groups: dict[str, dict]) -> list[dict]:
    """Merge paraphrases locally; the most frequent wording represents the cluster."""
    ordered = sorted(groups.values(), key=lambda g: (-g["occurrences"], g["last_seen"] or ""))
    clusters: list[dict] = []
    for group in ordered:
        target = next((cluster for cluster in clusters if
                       semantic_similarity(group["question"], cluster["question"]) >= GAP_CLUSTER_SIMILARITY), None)
        if target is None:
            clusters.append({
                **group,
                "questions": [group["question"]],
                "question_hashes": [group["question_hash"]],
            })
            continue
        target["occurrences"] += group["occurrences"]
        target["negative_feedback"] += group["negative_feedback"]
        target["questions"].append(group["question"])
        target["question_hashes"].append(group["question_hash"])
        target["conversation_ids"] = list(dict.fromkeys(target["conversation_ids"] + group["conversation_ids"]))[:5]
        if group["last_seen"] and (not target["last_seen"] or group["last_seen"] > target["last_seen"]):
            target["last_seen"] = group["last_seen"]
        if group["best_distance"] is not None and (target["best_distance"] is None or group["best_distance"] < target["best_distance"]):
            target["best_distance"] = group["best_distance"]
    for cluster in clusters:
        cluster["cluster_size"] = len(cluster["questions"])
    return sorted(clusters, key=lambda g: (-g["occurrences"], g["last_seen"] or ""))


def article_draft(cluster: dict) -> dict:
    """Build a privacy-first local scaffold; facts remain explicitly human supplied."""
    question = (cluster.get("question") or "Domanda frequente").strip().rstrip("?!. ")
    variants = [q.strip() for q in cluster.get("questions", []) if q.strip()][:20]
    related = "\n".join(f"- {item}" for item in variants)
    return {
        "title": question[:150],
        "content": (
            "## Risposta breve\n\n[DA COMPLETARE: inserisci qui la risposta verificata.]\n\n"
            "## Dettagli utili\n\n[DA COMPLETARE: condizioni, limiti, tempi ed eventuali eccezioni.]\n\n"
            f"## Domande dei clienti coperte\n\n{related}"
        )[:12000],
    }


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

    ranked = cluster_gap_groups(groups)
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


def gap_occurrences_since(
    session: Session, client_id: int, questions: list[str], since: datetime | None,
) -> int:
    """Count unresolved recurrences after an article was published."""
    if since is None:
        return 0
    hashes = {question_hash(item) for item in questions}
    logs = session.exec(select(AiResponseLog).where(
        AiResponseLog.client_id == client_id, AiResponseLog.created_at > since,
    ).order_by(AiResponseLog.id.desc()).limit(2000)).all()
    negative_ids = {row for row in session.exec(
        select(Message.id).join(Conversation, Message.conversation_id == Conversation.id).where(
            Conversation.client_id == client_id, Message.feedback == -1, Message.created_at > since,
        )
    ).all()}
    count = 0
    for row in logs:
        thumbs_down = row.message_id is not None and row.message_id in negative_ids
        distance = _best_distance(row.retrieved)
        no_context = distance is None or distance > GAP_MAX_DISTANCE
        if (thumbs_down or (row.outcome in GAP_OUTCOMES and no_context)) and question_hash(_question_for(session, row)) in hashes:
            count += 1
    return count


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


# ---- Aggregated statistics -------------------------------------------------------------------
#
# One client (operator view) or the whole system (client_id=None, admin view). Moved here from
# main.py: the numbers are analytics, and both the panel and the public API ask for them.


def _status_counts(session: Session, client_id: int | None) -> dict:
    q = select(Conversation.status, func.count()).group_by(Conversation.status)
    if client_id is not None:
        q = q.where(Conversation.client_id == client_id)
    return {status: int(n) for status, n in session.exec(q).all()}


def _ai_outcomes(session: Session, client_id: int | None) -> dict:
    q = select(AiResponseLog.outcome, func.count()).group_by(AiResponseLog.outcome)
    if client_id is not None:
        q = q.where(AiResponseLog.client_id == client_id)
    return {outcome: int(n) for outcome, n in session.exec(q).all()}


def _avg_latency_ms(session: Session, client_id: int | None) -> int:
    q = select(func.avg(AiResponseLog.latency_ms)).where(
        AiResponseLog.outcome == "answered", AiResponseLog.latency_ms > 0
    )
    if client_id is not None:
        q = q.where(AiResponseLog.client_id == client_id)
    val = session.exec(q).one()
    return int(val) if val is not None else 0


def _feedback_counts(session: Session, client_id: int | None) -> dict:
    q = select(Message.feedback, func.count()).where(Message.feedback.is_not(None))
    if client_id is not None:
        q = q.join(Conversation, Message.conversation_id == Conversation.id).where(
            Conversation.client_id == client_id
        )
    rows = session.exec(q.group_by(Message.feedback)).all()
    counts = {int(val): int(n) for val, n in rows}
    return {"positive": counts.get(1, 0), "negative": counts.get(-1, 0)}


def _daily_volume(session: Session, client_id: int | None, days: int = 14) -> list[dict]:
    since = datetime.utcnow() - timedelta(days=days)
    day = func.date(Conversation.created_at)
    q = select(day, func.count()).where(Conversation.created_at >= since)
    if client_id is not None:
        q = q.where(Conversation.client_id == client_id)
    rows = session.exec(q.group_by(day).order_by(day)).all()
    return [{"date": str(d), "conversations": int(n)} for d, n in rows]


def sla_warning_clause(now: datetime):
    """SQL predicate: at least one target is still pending and inside its warning window."""
    first = and_(
        Conversation.first_response_at.is_(None),
        Conversation.first_response_warn_at.is_not(None),
        Conversation.first_response_warn_at <= now,
        Conversation.first_response_due_at >= now,
    )
    resolution = and_(
        Conversation.closed_at.is_(None),
        Conversation.resolution_warn_at.is_not(None),
        Conversation.resolution_warn_at <= now,
        Conversation.resolution_due_at >= now,
    )
    return or_(first, resolution)


def sla_breached_clause(now: datetime):
    """SQL predicate: at least one target is past its deadline (missed, or met late)."""
    first = and_(
        Conversation.first_response_due_at.is_not(None),
        or_(
            and_(Conversation.first_response_at.is_(None), Conversation.first_response_due_at < now),
            and_(
                Conversation.first_response_at.is_not(None),
                Conversation.first_response_at > Conversation.first_response_due_at,
            ),
        ),
    )
    resolution = and_(
        Conversation.resolution_due_at.is_not(None),
        or_(
            and_(Conversation.closed_at.is_(None), Conversation.resolution_due_at < now),
            and_(Conversation.closed_at.is_not(None), Conversation.closed_at > Conversation.resolution_due_at),
        ),
    )
    return or_(first, resolution)


def _sla_stats(session: Session, client_id: int | None) -> dict:
    """SLA health: how many conversations are running an SLA, how many are at risk or already
    breached, how many met their targets, and the average first-response delay in minutes."""
    now = datetime.utcnow()

    def _count(*clauses) -> int:
        q = select(func.count()).select_from(Conversation).where(Conversation.sla_started_at.is_not(None), *clauses)
        if client_id is not None:
            q = q.where(Conversation.client_id == client_id)
        return int(session.exec(q).one())

    tracked = _count()
    breached = _count(sla_breached_clause(now))
    at_risk = _count(~sla_breached_clause(now), sla_warning_clause(now))
    avg_q = select(
        func.avg(
            func.extract("epoch", Conversation.first_response_at - Conversation.sla_started_at) / 60.0
        )
    ).where(Conversation.sla_started_at.is_not(None), Conversation.first_response_at.is_not(None))
    if client_id is not None:
        avg_q = avg_q.where(Conversation.client_id == client_id)
    avg_first_response = session.exec(avg_q).one()
    return {
        "tracked": tracked,
        "at_risk": at_risk,
        "breached": breached,
        "met": max(tracked - breached - at_risk, 0),
        # share of tracked conversations still within their targets (null with no data yet)
        "compliance_rate": round((tracked - breached) / tracked, 3) if tracked else None,
        "avg_first_response_minutes": round(float(avg_first_response), 1) if avg_first_response is not None else None,
    }


def _tag_stats(session: Session, client_id: int | None, limit: int = 8) -> list[dict]:
    """Most used tags, manual and AI together — the entry point for "di cosa ci scrivono"."""
    q = (
        select(Tag.name, ConversationTag.source, func.count())
        .join(ConversationTag, ConversationTag.tag_id == Tag.id)
        .group_by(Tag.name, ConversationTag.source)
        .order_by(func.count().desc())
        .limit(limit)
    )
    if client_id is not None:
        q = q.where(ConversationTag.client_id == client_id)
    return [{"name": name, "source": source, "conversations": int(n)} for name, source, n in session.exec(q).all()]


def _classification_stats(session: Session, client_id: int | None) -> dict:
    """Split of the AI classification by intent and urgency (classified conversations only)."""

    def _grouped(column) -> dict:
        q = select(column, func.count()).where(column != "", Conversation.ai_classified_at.is_not(None))
        if client_id is not None:
            q = q.where(Conversation.client_id == client_id)
        return {value: int(n) for value, n in session.exec(q.group_by(column)).all()}

    return {"by_intent": _grouped(Conversation.ai_intent), "by_urgency": _grouped(Conversation.ai_urgency)}


def _language_stats(session: Session, client_id: int | None) -> dict:
    """How many conversations in each language — the signal that says whether translating the
    knowledge base is worth it."""
    q = select(Conversation.language, func.count()).group_by(Conversation.language)
    if client_id is not None:
        q = q.where(Conversation.client_id == client_id)
    return {code: int(n) for code, n in session.exec(q).all() if code}


def csat_summary(session: Session, client_id: int | None, since: datetime | None = None) -> dict:
    """CSAT headline numbers: how many visitors answered, the average score and the share of
    ratings at 4–5 (the usual "satisfied" cut)."""
    q = select(func.count(), func.avg(ConversationRating.score))
    if client_id is not None:
        q = q.where(ConversationRating.client_id == client_id)
    if since is not None:
        q = q.where(ConversationRating.created_at >= since)
    responses, average = session.exec(q).one()
    responses = int(responses or 0)
    positive_q = select(func.count()).select_from(ConversationRating).where(ConversationRating.score >= 4)
    if client_id is not None:
        positive_q = positive_q.where(ConversationRating.client_id == client_id)
    if since is not None:
        positive_q = positive_q.where(ConversationRating.created_at >= since)
    positive = int(session.exec(positive_q).one() or 0)
    distribution_q = select(ConversationRating.score, func.count()).group_by(ConversationRating.score)
    if client_id is not None:
        distribution_q = distribution_q.where(ConversationRating.client_id == client_id)
    if since is not None:
        distribution_q = distribution_q.where(ConversationRating.created_at >= since)
    distribution = {str(score): int(n) for score, n in session.exec(distribution_q).all()}
    return {
        "responses": responses,
        "average": round(float(average), 2) if average is not None else None,
        "satisfied_rate": round(positive / responses, 3) if responses else None,
        "distribution": {str(k): distribution.get(str(k), 0) for k in range(1, 6)},
    }


def build_stats(session: Session, client_id: int | None) -> dict:
    """Aggregated analytics for one client (operator view) or the whole system (client_id=None,
    admin view): conversation status split, AI resolution vs escalation, escalation triggers,
    average answer latency, and a 14-day conversation-volume series."""
    status = _status_counts(session, client_id)
    outcomes = _ai_outcomes(session, client_id)
    answered = outcomes.get("answered", 0)
    esc_kw = outcomes.get("escalated_keyword", 0)
    esc_model = outcomes.get("escalated_model", 0)
    esc_down = outcomes.get("escalated_llm_down", 0)
    ai_escalated = esc_kw + esc_model + esc_down
    total_ai = answered + ai_escalated
    return {
        "conversations": {
            "total": sum(status.values()),
            "open": status.get("open", 0),
            "escalated": status.get("escalated", 0),
            "closed": status.get("closed", 0),
        },
        "ai": {
            "answered": answered,
            "escalated": ai_escalated,
            # share of AI turns resolved without a human (null when there's no data yet)
            "resolution_rate": round(answered / total_ai, 3) if total_ai else None,
            "avg_latency_ms": _avg_latency_ms(session, client_id),
        },
        "escalations_by_trigger": {"keyword": esc_kw, "model": esc_model, "llm_down": esc_down},
        "feedback": _feedback_counts(session, client_id),
        "sla": _sla_stats(session, client_id),
        "tags": _tag_stats(session, client_id),
        "classification": _classification_stats(session, client_id),
        "csat": csat_summary(session, client_id),
        "languages": _language_stats(session, client_id),
        "volume_daily": _daily_volume(session, client_id),
    }

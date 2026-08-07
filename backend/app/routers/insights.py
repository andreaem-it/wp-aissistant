"""Insights: statistics, CSAT and the knowledge-base gaps.

What the tenant learns from its own conversations — outcome and SLA numbers, satisfaction, and
the questions the assistant could not answer, clustered into candidate articles.

The gaps are **derived** at every request from the answer logs rather than stored, so the list
shortens by itself once the missing content is published; only the operator's decision persists.

Fifth area extracted from main.py — see `docs/handoff.md` for the pattern.
"""
import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import column, func
from sqlmodel import Session, select

from .. import analytics
from ..analytics import build_stats as _build_stats, csat_summary as _csat_summary
from ..conversations import operator_name as _operator_name
from ..db import ConversationRating, Department, KnowledgeDraft, Operator, get_session
from ..deps import audit as _audit, require_operator
from ..limits import MAX_INGEST_TEXT_CHARS
from ..util import bounded_limit as _bounded_limit, iso as _iso
from ..worker import enqueue as _enqueue

logger = logging.getLogger("wpai")

router = APIRouter()


@router.get("/stats")
def stats(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    data = _build_stats(session, operator.client_id)
    # keep the original flat keys so older panel builds keep working
    data["total_conversations"] = data["conversations"]["total"]
    data["escalated"] = data["conversations"]["escalated"]
    data["closed"] = data["conversations"]["closed"]
    return data


@router.get("/csat")
def csat_report(
    days: int = 30,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """CSAT report over a period: overall numbers plus the split by who handled the
    conversation (AI or operator), by operator and by department, with the latest comments."""
    window = min(max(days, 1), 365)
    since = datetime.utcnow() - timedelta(days=window)
    client_id = operator.client_id

    def _grouped(column):
        q = (
            select(column, func.count(), func.avg(ConversationRating.score))
            .where(ConversationRating.client_id == client_id, ConversationRating.created_at >= since)
            .group_by(column)
        )
        return session.exec(q).all()

    names = {
        row.id: _operator_name(row)
        for row in session.exec(select(Operator).where(Operator.client_id == client_id)).all()
    }
    departments = {
        row.id: row.name
        for row in session.exec(select(Department).where(Department.client_id == client_id)).all()
    }
    comments = session.exec(
        select(ConversationRating)
        .where(
            ConversationRating.client_id == client_id,
            ConversationRating.created_at >= since,
            ConversationRating.comment != "",
        )
        .order_by(ConversationRating.id.desc())
        .limit(20)
    ).all()
    return {
        "period_days": window,
        "summary": _csat_summary(session, client_id, since),
        "by_resolution": [
            {"resolved_by": value, "responses": int(n), "average": round(float(avg), 2)}
            for value, n, avg in _grouped(ConversationRating.resolved_by)
        ],
        "by_operator": [
            {
                "operator_id": value,
                "name": names.get(value, "Non assegnata"),
                "responses": int(n),
                "average": round(float(avg), 2),
            }
            for value, n, avg in _grouped(ConversationRating.operator_id)
        ],
        "by_department": [
            {
                "department_id": value,
                "name": departments.get(value, "Nessun reparto"),
                "responses": int(n),
                "average": round(float(avg), 2),
            }
            for value, n, avg in _grouped(ConversationRating.department_id)
        ],
        "comments": [
            {
                "conversation_id": row.conversation_id,
                "score": row.score,
                "comment": row.comment,
                "created_at": _iso(row.created_at),
            }
            for row in comments
        ],
    }


@router.get("/analytics/overview")
def analytics_overview(
    days: int = 30,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Outcome metrics over a period: deflection, escalations, response and resolution times."""
    return {
        **analytics.overview(session, operator.client_id, days),
        "trend": analytics.trend(session, operator.client_id, days),
    }


@router.get("/analytics/knowledge-gaps")
def analytics_knowledge_gaps(
    days: int = 30,
    limit: int = 20,
    include_reviewed: bool = False,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Questions the knowledge base couldn't serve, most frequent first."""
    return analytics.knowledge_gaps(
        session, operator.client_id, days=days,
        limit=_bounded_limit(limit, default=20, maximum=100),
        include_reviewed=include_reviewed,
    )


@router.post("/analytics/knowledge-gaps/review")
def review_knowledge_gap(
    question: str = Body(...),
    questions: list[str] = Body([]),
    status: str = Body("taught"),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Mark a gap as handled or dismissed so it stops coming back in the list."""
    if status not in ("taught", "ignored"):
        raise HTTPException(400, "status must be 'taught' or 'ignored'")
    if not (question or "").strip():
        raise HTTPException(400, "question required")
    variants = list(dict.fromkeys([question, *questions]))[:50]
    reviews = [analytics.review_gap(session, operator.client_id, item, status, operator.email) for item in variants if item.strip()]
    review = reviews[0]
    _audit(
        session, "operator", operator.email, "knowledge_gap.review",
        client_id=operator.client_id, detail={"status": status, "questions": len(reviews)},
    )
    return {"ok": True, "question_hash": review.question_hash, "status": review.status}


def _knowledge_draft_payload(row: KnowledgeDraft, session: Session) -> dict:
    questions = json.loads(row.questions or "[]")
    return {
        "id": row.id, "question_hash": row.question_hash,
        "questions": questions, "title": row.title,
        "content": row.content, "status": row.status,
        "baseline_occurrences": row.baseline_occurrences,
        "occurrences_after_publish": analytics.gap_occurrences_since(
            session, row.client_id, questions, row.published_at
        ),
        "ingest_job_id": row.ingest_job_id, "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at), "published_at": _iso(row.published_at),
    }


@router.get("/analytics/knowledge-drafts")
def list_knowledge_drafts(
    operator: Operator = Depends(require_operator), session: Session = Depends(get_session),
):
    rows = session.exec(
        select(KnowledgeDraft).where(KnowledgeDraft.client_id == operator.client_id)
        .order_by(KnowledgeDraft.id.desc()).limit(100)
    ).all()
    return [_knowledge_draft_payload(row, session) for row in rows]


@router.post("/analytics/knowledge-gaps/draft")
def create_knowledge_draft(
    question: str = Body(...),
    questions: list[str] = Body([]),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    variants = list(dict.fromkeys(q.strip()[:300] for q in [question, *questions] if q.strip()))[:20]
    if not variants:
        raise HTTPException(400, "question required")
    current = analytics.knowledge_gaps(session, operator.client_id, days=365, limit=100)["gaps"]
    requested = {analytics.question_hash(item) for item in variants}
    cluster = next((gap for gap in current if requested & set(gap["question_hashes"])), None)
    if cluster is None:
        raise HTTPException(404, "knowledge gap not found")
    proposed = analytics.article_draft(cluster)
    row = session.exec(select(KnowledgeDraft).where(
        KnowledgeDraft.client_id == operator.client_id,
        KnowledgeDraft.question_hash == cluster["question_hash"],
    )).first()
    if row is None:
        row = KnowledgeDraft(
            client_id=operator.client_id, question_hash=cluster["question_hash"],
            created_by=operator.email,
        )
    row.questions = json.dumps(cluster["questions"], ensure_ascii=False)
    row.title, row.content, row.status = proposed["title"], proposed["content"], "draft"
    row.baseline_occurrences, row.updated_at = cluster["occurrences"], datetime.utcnow()
    row.ingest_job_id, row.published_at = None, None
    session.add(row)
    session.commit()
    session.refresh(row)
    _audit(session, "operator", operator.email, "knowledge_draft.generate",
           target=f"knowledge-draft:{row.id}", client_id=operator.client_id,
           detail={"questions": len(cluster["questions"]), "occurrences": cluster["occurrences"]})
    return _knowledge_draft_payload(row, session)


@router.post("/analytics/knowledge-drafts/{draft_id}/publish")
def publish_knowledge_draft(
    draft_id: int,
    title: str = Body(...),
    content: str = Body(...),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    row = session.get(KnowledgeDraft, draft_id)
    if not row or row.client_id != operator.client_id:
        raise HTTPException(404, "knowledge draft not found")
    clean_title, clean_content = title.strip()[:150], content.strip()
    if not clean_title or not clean_content:
        raise HTTPException(400, "title and content required")
    if "[DA COMPLETARE" in clean_content.upper():
        raise HTTPException(400, "complete the draft before publishing")
    if len(clean_content) > MAX_INGEST_TEXT_CHARS:
        raise HTTPException(413, "content too large")
    job = _enqueue(session, operator.client_id, "document", {
        "source_ref": f"kb-bozza: {clean_title}", "text": f"{clean_title}\n\n{clean_content}",
    })
    row.title, row.content, row.status = clean_title, clean_content, "published"
    row.ingest_job_id, row.published_at, row.updated_at = job.id, datetime.utcnow(), datetime.utcnow()
    for variant in json.loads(row.questions or "[]"):
        analytics.review_gap(session, operator.client_id, variant, "taught", operator.email)
    session.add(row)
    session.commit()
    _audit(session, "operator", operator.email, "knowledge_draft.publish",
           target=f"knowledge-draft:{row.id}", client_id=operator.client_id,
           detail={"job_id": job.id})
    return {**_knowledge_draft_payload(row, session), "job_status": job.status}

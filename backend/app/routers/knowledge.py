"""Knowledge base: what the assistant is allowed to answer from.

Content arrives from the WordPress plugin (pages, posts, products) or is uploaded by an operator,
and is queued rather than embedded inline: the endpoint returns as soon as the job is accepted,
and a worker does the chunking and the embeddings.

Final phase of the main.py split — see `docs/handoff.md`.
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, UploadFile
from sqlalchemy import func
from sqlmodel import Session, select

from .. import events
from ..db import Chunk, Client, IngestJob, Operator, Product, get_session
from ..deps import (
    audit as _audit, rate_limit_ingest, require_client, require_operator, resolve_client_id,
)
from ..limits import MAX_INGEST_TEXT_CHARS, MAX_UPLOAD_BYTES
from ..rag import extract_text
from ..util import bounded_limit as _bounded_limit, iso as _iso
from ..worker import enqueue as _enqueue

logger = logging.getLogger("wpai")

router = APIRouter()


@router.post("/ingest/document")
async def ingest_document(file: UploadFile, operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file too large (max {MAX_UPLOAD_BYTES} bytes)")
    text = extract_text(file.filename, data)
    if len(text) > MAX_INGEST_TEXT_CHARS:
        raise HTTPException(413, "extracted text too large")
    job = _enqueue(session, operator.client_id, "document", {"source_ref": file.filename, "text": text})
    return {"ok": True, "job_id": job.id, "status": job.status, "chars": len(text)}


@router.post("/knowledge/teach")
def teach_knowledge(
    content: str = Body(...),
    title: str = Body(""),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Human-in-the-loop KB learning: the operator adds free text (e.g. a FAQ answer learned in
    chat) that goes through the same ingest pipeline (chunk + embed). Labeled 'kb-manuale' so it
    shows up in the knowledge base list and can be re-synced/removed like any other source."""
    if not content.strip():
        raise HTTPException(400, "content required")
    if len(content) > MAX_INGEST_TEXT_CHARS:
        raise HTTPException(413, "content too large")
    text = f"{title.strip()}\n\n{content}" if title.strip() else content
    ref = f"kb-manuale: {title.strip()}" if title.strip() else "kb-manuale"
    job = _enqueue(session, operator.client_id, "document", {"source_ref": ref, "text": text})
    _audit(session, "operator", operator.email, "knowledge.teach", target=ref, client_id=operator.client_id)
    return {"ok": True, "job_id": job.id, "status": job.status}


@router.post("/ingest/site-page")
def ingest_site_page(url: str = Body(...), text: str = Body(...), client: Client = Depends(rate_limit_ingest), session: Session = Depends(get_session)):
    """Called by the WP plugin on publish/update to push page/product content. The worker
    replaces previous chunks for this URL when it processes the job (so edits don't duplicate)."""
    if len(url) > 2000 or len(text) > MAX_INGEST_TEXT_CHARS:
        raise HTTPException(413, "site page payload too large")
    job = _enqueue(session, client.id, "site-page", {"url": url, "text": text})
    return {"ok": True, "job_id": job.id, "status": job.status}


@router.post("/ingest/product")
def ingest_product_endpoint(
    url: str = Body(...),
    title: str = Body(...),
    price: str = Body(""),
    image_url: str = Body(""),
    description: str = Body(""),
    client: Client = Depends(rate_limit_ingest),
    session: Session = Depends(get_session),
):
    """Called by the WP plugin for WooCommerce products, in addition to /ingest/site-page."""
    text = f"{title}\n{description}\nPrezzo: {price}" if price else f"{title}\n{description}"
    if len(url) > 2000 or len(title) > 500 or len(text) > MAX_INGEST_TEXT_CHARS:
        raise HTTPException(413, "product payload too large")
    job = _enqueue(session, client.id, "product", {
        "url": url, "title": title, "price": price, "image_url": image_url, "text": text,
    })
    return {"ok": True, "job_id": job.id, "status": job.status}


@router.get("/ingest/jobs/{job_id}")
def ingest_job_status(job_id: int, client_id: int = Depends(resolve_client_id), session: Session = Depends(get_session)):
    """Poll the status of an enqueued ingest job (queued | processing | done | error)."""
    job = session.get(IngestJob, job_id)
    if not job or job.client_id != client_id:
        raise HTTPException(404, "job not found")
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "error": job.error,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
    }


@router.get("/knowledge-base")
def list_knowledge_base(
    limit: int = 200,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """What's actually been ingested for this client — documents/pages grouped by
    source (deduped, the worker replaces old chunks on re-sync) and products."""
    rows = session.exec(
        select(Chunk.source, Chunk.source_ref, func.count(Chunk.id), func.max(Chunk.id))
        .where(Chunk.client_id == operator.client_id)
        .group_by(Chunk.source, Chunk.source_ref)
        .order_by(func.max(Chunk.id).desc())
        .limit(_bounded_limit(limit, default=200))
    ).all()
    documents = [
        {"source": source, "source_ref": ref, "chunks": count}
        for source, ref, count, _ in rows
    ]
    products = session.exec(
        select(Product)
        .where(Product.client_id == operator.client_id)
        .order_by(Product.id.desc())
        .limit(_bounded_limit(limit, default=200))
    ).all()
    return {
        "documents": documents,
        "products": [
            {"title": p.title, "price": p.price, "image_url": p.image_url, "product_url": p.product_url}
            for p in products
        ],
    }

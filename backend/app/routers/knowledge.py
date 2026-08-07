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

from .. import events, woocommerce
from ..db import Chunk, Client, IngestJob, Operator, Product, get_session
from ..deps import (
    require_plugin_installation,
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


def _clear_client_knowledge(session: Session, client_id: int) -> dict:
    """Empty one tenant's knowledge base. Tenant-scoped by construction: the client id comes
    from the caller's own credential, never from the request body."""
    chunks = session.exec(select(Chunk).where(Chunk.client_id == client_id)).all()
    products = session.exec(select(Product).where(Product.client_id == client_id)).all()
    for row in (*chunks, *products):
        session.delete(row)
    session.commit()
    return {"removed_chunks": len(chunks), "removed_products": len(products)}


def _clear_source_ref(session: Session, client_id: int, source_ref: str) -> int:
    """Drop every chunk under one source ref. Returns how many went, so the caller can report
    what actually happened instead of a bare success."""
    rows = session.exec(
        select(Chunk).where(Chunk.client_id == client_id, Chunk.source_ref == source_ref)
    ).all()
    for chunk in rows:
        session.delete(chunk)
    session.commit()
    return len(rows)


WOOCOMMERCE_SOURCE_REF = "woocommerce://settings"


@router.post("/ingest/woocommerce")
def ingest_woocommerce_settings(
    settings: dict = Body(..., embed=True),
    client: Client = Depends(rate_limit_ingest),
    session: Session = Depends(get_session),
):
    """Shipping zones and payment gateways, straight from the shop's WooCommerce settings.

    They are the authoritative answer to two of the most common questions a shop receives, and
    they live in settings rather than on a page — so without this they were absent from the
    knowledge base and the model answered from general knowledge instead.

    The payload is structured and the wording is built server-side (see app/woocommerce.py), so
    the phrasing can improve without every site updating the plugin. Re-syncing replaces the
    previous version rather than adding to it: a method removed in WooCommerce must disappear
    from the answers too.
    """
    text = woocommerce.render_settings(settings or {})
    if not text:
        # nothing configured is a legitimate state, and an empty document would only invite
        # the model to fill the gap: drop what we had instead of storing a blank
        removed = _clear_source_ref(session, client.id, WOOCOMMERCE_SOURCE_REF)
        return {"ok": True, "indexed": False, "removed_chunks": removed}
    if len(text) > MAX_INGEST_TEXT_CHARS:
        raise HTTPException(413, "woocommerce settings payload too large")
    job = _enqueue(session, client.id, "woocommerce", {"text": text})
    return {"ok": True, "indexed": True, "job_id": job.id, "status": job.status}


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


@router.delete("/knowledge-base")
def clear_knowledge_base(
    confirm: str = Body("", embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Empty this tenant's knowledge base so it can be rebuilt from scratch.

    Wanted when a sync has gone wrong and the base holds content that no longer matches the
    site: re-syncing alone replaces only what is sent again, so anything deleted on the site
    would linger and keep being quoted back to visitors.

    Requires an explicit confirmation string rather than trusting the caller's intent: this
    leaves the assistant with nothing to answer from until a new sync completes, and a stray
    request must not be able to do that silently. Tenant-scoped and audited.
    """
    if confirm != "svuota":
        raise HTTPException(400, "confirm must be the word 'svuota'")
    removed = _clear_client_knowledge(session, operator.client_id)
    _audit(session, "operator", operator.email, "knowledge_base.cleared",
           client_id=operator.client_id, detail=removed)
    return {"ok": True, **removed}


@router.delete("/plugin/knowledge-base")
def clear_knowledge_base_from_plugin(
    confirm: str = Body("", embed=True),
    installation=Depends(require_plugin_installation),
    session: Session = Depends(get_session),
):
    """Same reset, triggered from the WordPress plugin.

    Authenticated with the **verified installation**, never the widget api_key: that key is
    embedded in every public page of the site, and a leaked one must not be able to wipe a
    tenant's knowledge base.
    """
    if confirm != "svuota":
        raise HTTPException(400, "confirm must be the word 'svuota'")
    removed = _clear_client_knowledge(session, installation.client_id)
    _audit(session, "plugin", installation.site_origin, "knowledge_base.cleared",
           client_id=installation.client_id, detail=removed)
    return {"ok": True, **removed}


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

"""Superadmin: onboarding, plans and cross-tenant visibility.

The only surface that sees every client at once — creating tenants and operators, plan
management, the system-wide statistics and health, the audit log, and the per-conversation
debug view that answers "why did the AI answer that?".

Gated by ADMIN_API_KEY and fails closed: with no key configured the whole area is disabled.

Final phase of the main.py split — see `docs/handoff.md`.
"""
import json
import logging
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import and_, func, or_
from sqlmodel import Session, select

from .. import billing, cors, email as email_service, metrics, webhooks
from ..analytics import build_stats as _build_stats
from ..billing import default_plan_id as _default_plan_id
from .. import retention
from ..conversations import operator_name as _operator_name
from ..db import (
    AiResponseLog, ApiKey, AuditLog, Chunk, Client, Conversation, IngestJob, Message, Operator,
    OperatorSession, Plan, Product, PushSubscription, Ticket, get_session,
)
from ..deps import audit as _audit, require_admin
from ..llm import CHAT_MODEL, EMBED_MODEL
from ..production_config import production_warnings
from ..rag import embed
from ..security import hash_password
from ..util import iso as _iso, normalize_origins as _normalize_origins

logger = logging.getLogger("wpai")

router = APIRouter()


@router.get("/admin/stats", dependencies=[Depends(require_admin)])
def admin_stats(session: Session = Depends(get_session)):
    """System-wide analytics for the superadmin dashboard: the same aggregates as /stats but
    across every client, plus client counts by plan/billing status and the top clients by volume."""
    data = _build_stats(session, None)
    plans = {p.id: p.name for p in session.exec(select(Plan)).all()}
    clients = session.exec(select(Client)).all()
    by_plan: dict = {}
    by_billing: dict = {}
    for c in clients:
        pname = plans.get(c.plan_id, "—")
        by_plan[pname] = by_plan.get(pname, 0) + 1
        by_billing[c.billing_status] = by_billing.get(c.billing_status, 0) + 1
    names = {c.id: c.name for c in clients}
    top_q = (
        select(Conversation.client_id, func.count().label("n"))
        .group_by(Conversation.client_id)
        .order_by(func.count().desc())
        .limit(5)
    )
    data["clients"] = {"total": len(clients), "by_plan": by_plan, "by_billing_status": by_billing}
    data["top_clients"] = [
        {"client_id": cid, "name": names.get(cid, "?"), "conversations": int(n)}
        for cid, n in session.exec(top_q).all()
    ]
    return data


@router.get("/admin/health", dependencies=[Depends(require_admin)])
def admin_health(session: Session = Depends(get_session)):
    """Operational snapshot for the superadmin: DB reachability, ingest queue depth (incl.
    errored jobs), worker flag, applied migration, configured models, and app version."""

    db_ok = True
    try:
        session.exec(select(func.count()).select_from(Client)).one()
    except Exception:  # noqa: BLE001
        db_ok = False

    queue = {"queued": 0, "processing": 0, "done": 0, "error": 0}
    try:
        for status, n in session.exec(select(IngestJob.status, func.count()).group_by(IngestJob.status)).all():
            queue[status] = int(n)
    except Exception:  # noqa: BLE001
        pass

    try:
        row = session.connection().exec_driver_sql("SELECT version_num FROM alembic_version").fetchone()
        migration = row[0] if row else None
    except Exception:  # noqa: BLE001
        migration = None  # e.g. dev DB created via DB_AUTO_CREATE without alembic

    overall = "ok" if db_ok and queue["error"] == 0 else "degraded"
    return {
        "status": overall,
        "db": "ok" if db_ok else "error",
        "ingest_queue": queue,
        "worker_enabled": os.getenv("INGEST_WORKER_ENABLED", "true").lower() == "true",
        "migration": migration,
        "models": {"chat": CHAT_MODEL, "embed": EMBED_MODEL},
        "email": email_service.config_status(),
        "production_config": {
            "strict": os.getenv("STRICT_PRODUCTION_CONFIG", "false").lower() == "true",
            "warnings": production_warnings(os.environ),
        },
        "version": os.getenv("APP_VERSION", "dev"),
    }


@router.post("/admin/test-email", dependencies=[Depends(require_admin)])
def admin_test_email(to: str = Body(..., embed=True)):
    """Send a diagnostic email to verify SMTP end-to-end. Reports whether SMTP is configured
    and whether the send succeeded (never exposes credentials)."""
    if not email_service.enabled():
        return {"configured": False, "sent": False, "detail": "SMTP non configurato (imposta SMTP_HOST)"}
    sent = email_service.send_test(to)
    return {"configured": True, "sent": sent, "detail": "Inviata" if sent else "Invio fallito — controlla le credenziali SMTP"}


@router.get("/admin/problematic", dependencies=[Depends(require_admin)])
def admin_problematic(
    client_id: int | None = None,
    limit: int = 50,
    include_ungrounded: bool = False,
    session: Session = Depends(get_session),
):
    """AI turns worth reviewing: model escalations (answer not in context) and LLM-down handoffs.
    With include_ungrounded=true also flags answers produced with *no* retrieved context — useful
    to catch ungrounded replies, but noisy (greetings are answered without context by design).
    Feeds a KB-improvement queue; open /admin/conversations/{id}/debug for the full picture."""
    problem_outcomes = ["escalated_model", "escalated_llm_down"]
    if include_ungrounded:
        condition = or_(
            AiResponseLog.outcome.in_(problem_outcomes),
            and_(AiResponseLog.outcome == "answered", AiResponseLog.retrieved == "[]"),
        )
    else:
        condition = AiResponseLog.outcome.in_(problem_outcomes)
    q = select(AiResponseLog).where(condition)
    if client_id is not None:
        q = q.where(AiResponseLog.client_id == client_id)
    rows = session.exec(q.order_by(AiResponseLog.id.desc()).limit(min(limit, 200))).all()
    result = []
    for r in rows:
        retrieved = json.loads(r.retrieved or "[]")
        distances = [c["distance"] for c in retrieved if "distance" in c]
        kind = r.outcome if r.outcome != "answered" else "answered_no_context"
        result.append({
            "id": r.id, "conversation_id": r.conversation_id, "client_id": r.client_id,
            "kind": kind, "model": r.model, "retrieved_count": len(retrieved),
            "best_distance": round(min(distances), 4) if distances else None,
            "created_at": r.created_at,
        })
    return result


@router.post("/admin/clients", dependencies=[Depends(require_admin)])
def create_client(
    name: str = Body(...),
    allowed_origins: str = Body(""),
    plan_id: int | None = Body(None),
    session: Session = Depends(get_session),
):
    """Provision a new client and return its generated api_key. The key is shown only here —
    it's not stored in a recoverable form for listing, so capture it now. allowed_origins is a
    comma-separated list of widget origins (empty = no per-client origin enforcement).
    Defaults to the Free plan if plan_id isn't given."""
    client = Client(
        name=name,
        api_key=secrets.token_urlsafe(32),
        allowed_origins=_normalize_origins(allowed_origins),
        plan_id=plan_id or _default_plan_id(session),
    )
    session.add(client)
    session.commit()
    session.refresh(client)
    cors.rebuild_allowed_origins(session)
    _audit(session, "admin", "admin", "client.create", target=f"client:{client.id}", client_id=client.id, detail={"name": name})
    return {"id": client.id, "name": client.name, "api_key": client.api_key, "allowed_origins": client.allowed_origins, "plan_id": client.plan_id}


@router.get("/admin/clients", dependencies=[Depends(require_admin)])
def list_clients(session: Session = Depends(get_session)):
    # deliberately omit api_key so a leaked admin listing doesn't hand out client keys
    clients = session.exec(select(Client)).all()
    plans = {p.id: p.name for p in session.exec(select(Plan)).all()}
    result = []
    for c in clients:
        result.append({
            "id": c.id,
            "name": c.name,
            "allowed_origins": c.allowed_origins,
            "plan_id": c.plan_id,
            "plan_name": plans.get(c.plan_id),
            "billing_status": c.billing_status,
            # le date del ciclo di vita: senza, il pannello mostra uno stato senza sapere da
            # quando vale né fino a quando, che è la prima cosa che si chiede guardando un cliente
            "created_at": c.created_at,
            "first_paid_at": c.first_paid_at,
            "subscription_period_end": c.subscription_period_end,
            "subscription_cancel_at_period_end": c.subscription_cancel_at_period_end,
            "subscription_canceled_at": c.subscription_canceled_at,
            "subscription_interval": c.subscription_interval,
            "data_deletion_due_at": c.data_deletion_due_at,
            "conversations": session.exec(
                select(func.count()).select_from(Conversation).where(Conversation.client_id == c.id)
            ).one(),
            "operators": session.exec(
                select(func.count()).select_from(Operator).where(Operator.client_id == c.id)
            ).one(),
            "documents": session.exec(
                select(func.count()).select_from(Chunk).where(Chunk.client_id == c.id)
            ).one(),
            "products": session.exec(
                select(func.count()).select_from(Product).where(Product.client_id == c.id)
            ).one(),
        })
    return result


@router.get("/admin/conversations/{conversation_id}/debug", dependencies=[Depends(require_admin)])
def conversation_debug(conversation_id: int, session: Session = Depends(get_session)):
    """Full diagnostic view of a conversation for the superadmin: every message plus, for each
    AI turn, what was retrieved (chunk refs + cosine distances + which the reranker selected),
    the model, latency and token usage, and the outcome — i.e. *why* the AI answered as it did."""
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404, "conversation not found")
    messages = session.exec(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)
    ).all()
    logs = session.exec(
        select(AiResponseLog).where(AiResponseLog.conversation_id == conversation_id).order_by(AiResponseLog.id)
    ).all()
    return {
        "conversation": {
            "id": conv.id, "client_id": conv.client_id, "visitor_id": conv.visitor_id,
            "channel": conv.channel, "contact_id": conv.contact_id,
            "status": conv.status, "created_at": conv.created_at, "updated_at": conv.updated_at,
            "closed_at": conv.closed_at,
        },
        "messages": [
            {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at}
            for m in messages
        ],
        "ai_turns": [
            {
                "id": lg.id, "outcome": lg.outcome, "model": lg.model,
                "latency_ms": lg.latency_ms, "tokens_prompt": lg.tokens_prompt,
                "tokens_completion": lg.tokens_completion, "message_id": lg.message_id,
                "created_at": lg.created_at, "retrieved": json.loads(lg.retrieved or "[]"),
            }
            for lg in logs
        ],
    }


@router.get("/admin/audit", dependencies=[Depends(require_admin)])
def list_audit(client_id: int | None = None, limit: int = 100, session: Session = Depends(get_session)):
    """Recent privileged actions (who did what, when). Optional client_id filter; newest first."""
    q = select(AuditLog)
    if client_id is not None:
        q = q.where(AuditLog.client_id == client_id)
    rows = session.exec(q.order_by(AuditLog.id.desc()).limit(min(limit, 500))).all()
    return [
        {
            "id": r.id, "actor_type": r.actor_type, "actor_id": r.actor_id,
            "action": r.action, "target": r.target, "client_id": r.client_id,
            "detail": json.loads(r.detail or "{}"), "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/admin/plans", dependencies=[Depends(require_admin)])
def list_plans(session: Session = Depends(get_session)):
    return session.exec(select(Plan).order_by(Plan.id)).all()


def _reject_free_plan(price_cents: int, yearly_price_cents: int, internal: bool = False) -> None:
    """Un piano vendibile deve costare qualcosa su almeno un intervallo.

    Non esiste una versione gratuita del prodotto: un piano a zero su entrambi gli intervalli
    darebbe accesso al servizio senza contropartita e comparirebbe nei ricavi come cliente che
    non paga, falsando margine e funnel. Mensile-solo o annuale-solo restano legittimi — è la
    gratuità totale a non esserlo.

    I piani **interni** sono esclusi: non sono prodotti, non compaiono in nessun elenco rivolto
    a un cliente e non concedono nulla. Dare loro un prezzo per far passare questo controllo li
    farebbe sembrare acquistabili, che è esattamente il problema che si vuole evitare.
    """
    if internal:
        return
    if price_cents <= 0 and yearly_price_cents <= 0:
        raise HTTPException(400, "un piano deve avere un prezzo mensile o annuale maggiore di zero")


@router.post("/admin/plans", dependencies=[Depends(require_admin)])
def create_plan(
    name: str = Body(...),
    price_cents: int = Body(0),
    currency: str = Body("eur"),
    chat_rate_limit: int = Body(30),
    ingest_rate_limit: int = Body(60),
    monthly_message_limit: int = Body(0),
    yearly_price_cents: int = Body(0),
    stripe_price_id: str = Body(""),
    stripe_yearly_price_id: str = Body(""),
    session: Session = Depends(get_session),
):
    if session.exec(select(Plan).where(Plan.name == name)).first():
        raise HTTPException(409, "a plan with this name already exists")
    _reject_free_plan(price_cents, yearly_price_cents)
    plan = Plan(
        name=name, price_cents=price_cents, currency=currency,
        chat_rate_limit=chat_rate_limit, ingest_rate_limit=ingest_rate_limit,
        monthly_message_limit=monthly_message_limit,
        yearly_price_cents=yearly_price_cents,
        stripe_price_id=stripe_price_id,
        stripe_yearly_price_id=stripe_yearly_price_id,
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


@router.post("/admin/plans/{plan_id}", dependencies=[Depends(require_admin)])
def update_plan(
    plan_id: int,
    name: str | None = Body(None),
    price_cents: int | None = Body(None),
    currency: str | None = Body(None),
    chat_rate_limit: int | None = Body(None),
    ingest_rate_limit: int | None = Body(None),
    stripe_price_id: str | None = Body(None),
    stripe_yearly_price_id: str | None = Body(None),
    yearly_price_cents: int | None = Body(None),
    monthly_message_limit: int | None = Body(None),
    session: Session = Depends(get_session),
):
    """Update a plan's commercial settings (only the fields provided)."""
    plan = session.get(Plan, plan_id)
    if not plan:
        raise HTTPException(404, "plan not found")
    if name is not None:
        normalized_name = name.strip()
        if not normalized_name:
            raise HTTPException(400, "plan name cannot be empty")
        duplicate = session.exec(
            select(Plan).where(Plan.name == normalized_name, Plan.id != plan_id)
        ).first()
        if duplicate:
            raise HTTPException(409, "a plan with this name already exists")
        plan.name = normalized_name
    if price_cents is not None:
        if price_cents < 0:
            raise HTTPException(400, "price_cents cannot be negative")
        plan.price_cents = price_cents
    if currency is not None:
        normalized_currency = currency.strip().lower()
        if len(normalized_currency) != 3:
            raise HTTPException(400, "currency must be a 3-letter ISO code")
        plan.currency = normalized_currency
    if chat_rate_limit is not None:
        if chat_rate_limit < 1:
            raise HTTPException(400, "chat_rate_limit must be positive")
        plan.chat_rate_limit = chat_rate_limit
    if ingest_rate_limit is not None:
        if ingest_rate_limit < 1:
            raise HTTPException(400, "ingest_rate_limit must be positive")
        plan.ingest_rate_limit = ingest_rate_limit
    if stripe_price_id is not None:
        plan.stripe_price_id = stripe_price_id
    if stripe_yearly_price_id is not None:
        plan.stripe_yearly_price_id = stripe_yearly_price_id
    if yearly_price_cents is not None:
        if yearly_price_cents < 0:
            raise HTTPException(400, "yearly_price_cents cannot be negative")
        plan.yearly_price_cents = yearly_price_cents
    if monthly_message_limit is not None:
        if monthly_message_limit < 0:
            raise HTTPException(400, "monthly_message_limit cannot be negative")
        plan.monthly_message_limit = monthly_message_limit
    # dopo che entrambi i prezzi sono stati applicati: azzerarne uno solo è legittimo (un piano
    # può non essere offerto ad anno), ritrovarsi con tutti e due a zero no
    _reject_free_plan(plan.price_cents, plan.yearly_price_cents, plan.internal)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


@router.get("/admin/clients/{client_id}/operators", dependencies=[Depends(require_admin)])
def list_operators(client_id: int, session: Session = Depends(get_session)):
    operators = session.exec(select(Operator).where(Operator.client_id == client_id)).all()
    return [{"id": o.id, "email": o.email, "created_at": o.created_at} for o in operators]


@router.delete("/admin/operators/{operator_id}", dependencies=[Depends(require_admin)])
def delete_operator(operator_id: int, session: Session = Depends(get_session)):
    operator = session.get(Operator, operator_id)
    if not operator:
        raise HTTPException(404, "operator not found")
    for conv in session.exec(select(Conversation).where(Conversation.assigned_operator_id == operator_id)).all():
        conv.assigned_operator_id = None
        session.add(conv)
    for s in session.exec(select(OperatorSession).where(OperatorSession.operator_id == operator_id)).all():
        session.delete(s)
    for subscription in session.exec(
        select(PushSubscription).where(PushSubscription.operator_id == operator_id)
    ).all():
        session.delete(subscription)
    session.commit()  # flush the FK-dependent sessions before deleting their operator
    client_id = operator.client_id
    session.delete(operator)
    session.commit()
    _audit(session, "admin", "admin", "operator.delete", target=f"operator:{operator_id}", client_id=client_id)
    return {"ok": True}


@router.post("/admin/clients/{client_id}/origins", dependencies=[Depends(require_admin)])
def set_client_origins(client_id: int, allowed_origins: str = Body(..., embed=True), session: Session = Depends(get_session)):
    """Set the comma-separated widget origins allowed to use this client's key from a browser."""
    client = session.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")
    client.allowed_origins = _normalize_origins(allowed_origins)
    session.add(client)
    session.commit()
    cors.rebuild_allowed_origins(session)
    _audit(session, "admin", "admin", "client.set_origins", target=f"client:{client_id}", client_id=client_id, detail={"allowed_origins": client.allowed_origins})
    return {"id": client.id, "name": client.name, "allowed_origins": client.allowed_origins}


@router.patch("/admin/clients/{client_id}", dependencies=[Depends(require_admin)])
def update_client(
    client_id: int,
    name: str = Body(..., embed=True),
    session: Session = Depends(get_session),
):
    """Rinomina un cliente. È il nome che compare in ogni vista del pannello e nelle email al
    visitatore («Nuova risposta dal supporto — <nome>»), quindi un refuso alla creazione va
    potuto correggere senza rifare l'account."""
    client = session.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")
    new_name = name.strip()
    if not new_name:
        raise HTTPException(400, "il nome non può essere vuoto")
    before = client.name
    client.name = new_name
    session.add(client)
    session.commit()
    _audit(session, "admin", "admin", "client.renamed", target=f"client:{client_id}",
           client_id=client_id, detail={"from": before, "to": new_name})
    return {"id": client.id, "name": client.name}


@router.delete("/admin/clients/{client_id}", dependencies=[Depends(require_admin)])
def delete_client(
    client_id: int,
    confirm: str = Body("", embed=True),
    session: Session = Depends(get_session),
):
    """Elimina un tenant e tutti i suoi dati. Definitiva, non annullabile.

    Chiede il nome esatto del cliente come conferma, non un "sì": è l'unica azione del pannello
    che distrugge i dati di qualcun altro, e in una lista di clienti la riga sbagliata è a un
    pixel di distanza da quella giusta. Scrivere il nome costringe a guardare **quale**.

    La stessa `purge_client` è usata dalla scadenza dei 90 giorni dopo la disdetta: un solo
    posto che sa cosa significa cancellare un tenant, così non divergono.
    """
    client = session.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")
    if confirm.strip() != client.name:
        raise HTTPException(400, "per confermare, scrivi il nome esatto del cliente")
    name = client.name
    removed = retention.purge_client(session, client_id)
    # L'audit va scritto **dopo** e senza client_id: la tabella è per tenant, quindi una riga
    # scritta prima verrebbe cancellata dalla purga insieme al resto e la traccia di chi ha
    # cancellato cosa sparirebbe proprio nel momento in cui serve. Nome e id restano nel
    # dettaglio: sono il registro della piattaforma, non dati del cliente.
    _audit(session, "admin", "admin", "client.deleted", target=f"client:{client_id}",
           detail={"name": name, "client_id": client_id, "removed": removed})
    cors.rebuild_allowed_origins(session)
    return {"deleted": True, "name": name, "removed": removed}


@router.post("/admin/clients/{client_id}/rotate-key", dependencies=[Depends(require_admin)])
def rotate_client_key(client_id: int, session: Session = Depends(get_session)):
    client = session.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")
    client.api_key = secrets.token_urlsafe(32)
    session.add(client)
    session.commit()
    _audit(session, "admin", "admin", "client.rotate_key", target=f"client:{client_id}", client_id=client_id)
    return {"id": client.id, "name": client.name, "api_key": client.api_key}


@router.post("/admin/clients/{client_id}/operators", dependencies=[Depends(require_admin)])
def create_operator(client_id: int, email: str = Body(...), password: str = Body(...), name: str = Body(""), session: Session = Depends(get_session)):
    """Provision a panel operator for a client. Password is stored hashed (PBKDF2)."""
    if not session.get(Client, client_id):
        raise HTTPException(404, "client not found")
    if session.exec(select(Operator).where(Operator.email == email)).first():
        raise HTTPException(409, "email already registered")
    # admin-provisioned by a trusted human => no email round-trip needed, log in right away
    operator = Operator(client_id=client_id, email=email, name=name, password_hash=hash_password(password), email_verified=True)
    session.add(operator)
    session.commit()
    session.refresh(operator)
    _audit(session, "admin", "admin", "operator.create", target=f"operator:{operator.id}", client_id=client_id, detail={"email": email})
    return {"id": operator.id, "client_id": client_id, "email": email}


@router.post("/admin/reembed", dependencies=[Depends(require_admin)])
def reembed(limit: int = 200, session: Session = Depends(get_session)):
    """Re-embed content whose embedding is NULL (e.g. after an embedding-model/dimension
    change). Processes up to `limit` chunks and `limit` products per call so it never
    times out on large datasets — call repeatedly until `remaining` is zero."""
    chunks = session.exec(select(Chunk).where(Chunk.embedding.is_(None)).limit(limit)).all()
    for chunk in chunks:
        chunk.embedding = embed(chunk.text)
        session.add(chunk)
    products = session.exec(select(Product).where(Product.embedding.is_(None)).limit(limit)).all()
    for product in products:
        text = f"{product.title}\nPrezzo: {product.price}" if product.price else product.title
        product.embedding = embed(text)
        session.add(product)
    session.commit()
    remaining_chunks = session.exec(select(func.count()).select_from(Chunk).where(Chunk.embedding.is_(None))).one()
    remaining_products = session.exec(select(func.count()).select_from(Product).where(Product.embedding.is_(None))).one()
    return {
        "reembedded": {"chunks": len(chunks), "products": len(products)},
        "remaining": {"chunks": remaining_chunks, "products": remaining_products},
    }

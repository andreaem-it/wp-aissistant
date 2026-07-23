import json
import logging
import os
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request, Response, UploadFile
from sqlmodel import Session, select

from .db import (
    Client,
    Conversation,
    IngestJob,
    Message,
    Operator,
    OperatorSession,
    Ticket,
    engine,
    get_session,
    init_db,
)
from .llm import LLMUnavailableError
from .llm import chat as llm_chat
from .logging_config import log, request_id_var, setup_logging
from .notify import notify_new_ticket
from .rag import extract_text, retrieve, retrieve_products
from .ratelimit import FixedWindowLimiter
from .security import hash_password, verify_password
from .worker import requeue_stale, run_worker

setup_logging()
logger = logging.getLogger("wpai")

_worker_stop = threading.Event()
_worker_thread: threading.Thread | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with Session(engine) as session:
        rebuild_allowed_origins(session)
        requeue_stale(session)  # recover jobs left 'processing' by a previous crash
    global _worker_thread
    if os.getenv("INGEST_WORKER_ENABLED", "true").lower() == "true":
        _worker_thread = threading.Thread(target=run_worker, args=(_worker_stop,), daemon=True)
        _worker_thread.start()
    log(logger, logging.INFO, "startup.complete")
    yield
    _worker_stop.set()
    if _worker_thread:
        _worker_thread.join(timeout=5)


app = FastAPI(title="wp-aissistant backend", lifespan=lifespan)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    """Tags every request with a request_id (propagated to the response header and to
    every log line emitted while handling it, via the contextvar), and logs one line
    per completed request with method/path/status/duration."""
    request_id = str(uuid.uuid4())
    token = request_id_var.set(request_id)
    start = time.monotonic()
    try:
        try:
            response = await call_next(request)
        except Exception:
            log(logger, logging.ERROR, "request.unhandled_error", method=request.method, path=request.url.path)
            raise
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        log(
            logger, logging.INFO, "request.complete",
            method=request.method, path=request.url.path,
            status_code=response.status_code, duration_ms=duration_ms,
        )
        response.headers["X-Request-Id"] = request_id
        return response
    finally:
        request_id_var.reset(token)


@app.get("/health")
def health():
    """Liveness probe (no auth) for container/orchestrator health checks."""
    return {"status": "ok"}

# admin token for client onboarding endpoints; unset => the /admin surface is disabled (fail closed)
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")

# /chat hits the LLM on every call, so it's the main abuse/cost surface — limit per client+IP.
# Ingest is limited per client. Windows are 60s; override the counts via env.
chat_limiter = FixedWindowLimiter(int(os.getenv("CHAT_RATE_LIMIT", "30")), 60)
ingest_limiter = FixedWindowLimiter(int(os.getenv("INGEST_RATE_LIMIT", "60")), 60)

# ponytail: deterministic safety net for categories that must always reach a human —
# small local LLMs don't reliably follow "always escalate refunds" instructions
ALWAYS_ESCALATE_KEYWORDS = [
    "rimborso", "refund", "reclamo", "complaint", "denuncia",
    "cambio password account", "eliminare il mio account", "delete my account",
]

# ---- Dynamic CORS ----
# CORS preflight (OPTIONS) doesn't carry the api_key, so it can't be scoped per-client at the
# CORS layer. Instead we reflect an Origin only if it's in a dynamic allowlist (panel origins +
# every client's configured widget origins). The enforceable per-client key<->site binding lives
# in rate_limit_chat, which can see the api_key. CORS_ALLOW_ALL keeps the permissive default
# until origins are configured; set it false to enforce the allowlist strictly.
CORS_ALLOW_ALL = os.getenv("CORS_ALLOW_ALL", "true").lower() == "true"
PANEL_ORIGINS = [o.strip() for o in os.getenv("PANEL_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
_ALLOWED_ORIGINS: set[str] = set(PANEL_ORIGINS)


def _split_origins(raw: str) -> list[str]:
    return [o.strip() for o in (raw or "").split(",") if o.strip()]


def rebuild_allowed_origins(session: Session) -> None:
    """Recompute the browser-layer allowlist: panel origins + every client's widget origins."""
    origins = set(PANEL_ORIGINS)
    for c in session.exec(select(Client)).all():
        origins.update(_split_origins(c.allowed_origins))
    global _ALLOWED_ORIGINS
    _ALLOWED_ORIGINS = origins


def _cors_headers(origin: str) -> dict:
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type, ngrok-skip-browser-warning",
        "Access-Control-Max-Age": "600",
        "Vary": "Origin",
    }


@app.middleware("http")
async def dynamic_cors(request: Request, call_next):
    origin = request.headers.get("origin")
    allowed = bool(origin) and (CORS_ALLOW_ALL or origin in _ALLOWED_ORIGINS)
    # answer preflight before routing (routes don't declare OPTIONS handlers)
    if request.method == "OPTIONS" and origin and request.headers.get("access-control-request-method"):
        return Response(status_code=204 if allowed else 403, headers=_cors_headers(origin) if allowed else {})
    response = await call_next(request)
    if allowed:
        response.headers.update(_cors_headers(origin))
    return response


def _enqueue(session: Session, client_id: int, kind: str, payload: dict) -> IngestJob:
    job = IngestJob(client_id=client_id, kind=kind, payload=json.dumps(payload))
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def get_client(api_key: str, session: Session) -> Client:
    client = session.exec(select(Client).where(Client.api_key == api_key)).first()
    if not client:
        raise HTTPException(401, "invalid api key")
    return client


def require_client(
    authorization: str = Header(None),
    session: Session = Depends(get_session),
) -> Client:
    """Auth dependency: reads the client api_key from the `Authorization: Bearer <key>`
    header instead of a query param, so keys don't leak into server/proxy access logs.
    FastAPI caches get_session within a request, so the endpoint shares this session."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    return get_client(authorization[7:].strip(), session)


def require_admin(authorization: str = Header(None)) -> None:
    """Gates the client-onboarding endpoints behind the ADMIN_API_KEY env var.
    Fails closed: if no admin key is configured the whole /admin surface is disabled."""
    if not ADMIN_API_KEY:
        raise HTTPException(503, "admin api not configured")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    if not secrets.compare_digest(authorization[7:].strip(), ADMIN_API_KEY):
        raise HTTPException(401, "invalid admin key")


def rate_limit_chat(request: Request, client: Client = Depends(require_client)) -> Client:
    # enforceable per-client binding: a browser call with this client's key must come from
    # one of its configured origins (skipped when unconfigured or for server-side calls)
    allowed = _split_origins(client.allowed_origins)
    origin = request.headers.get("origin")
    if allowed and origin and origin not in allowed:
        raise HTTPException(403, "origin not allowed for this client")
    ip = request.client.host if request.client else "unknown"
    chat_limiter.check(f"chat:{client.id}:{ip}")
    return client


def rate_limit_ingest(client: Client = Depends(require_client)) -> Client:
    ingest_limiter.check(f"ingest:{client.id}")
    return client


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    return authorization[7:].strip()


def require_operator(
    authorization: str = Header(None), session: Session = Depends(get_session)
) -> Operator:
    """Auth for the human panel: resolves an operator session token to its Operator."""
    op_session = session.exec(
        select(OperatorSession).where(OperatorSession.token == _bearer_token(authorization))
    ).first()
    operator = session.get(Operator, op_session.operator_id) if op_session else None
    if not operator:
        raise HTTPException(401, "invalid or expired session")
    return operator


def resolve_client_id(
    authorization: str = Header(None), session: Session = Depends(get_session)
) -> int:
    """Dual auth for endpoints shared by the widget (client api_key) and the panel
    (operator session token). Returns the owning client_id from whichever matches."""
    token = _bearer_token(authorization)
    op_session = session.exec(
        select(OperatorSession).where(OperatorSession.token == token)
    ).first()
    if op_session:
        return op_session.client_id
    client = session.exec(select(Client).where(Client.api_key == token)).first()
    if client:
        return client.id
    raise HTTPException(401, "invalid credentials")


@app.post("/ingest/document")
async def ingest_document(file: UploadFile, operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    data = await file.read()
    text = extract_text(file.filename, data)
    job = _enqueue(session, operator.client_id, "document", {"source_ref": file.filename, "text": text})
    return {"ok": True, "job_id": job.id, "status": job.status, "chars": len(text)}


@app.post("/ingest/site-page")
def ingest_site_page(url: str = Body(...), text: str = Body(...), client: Client = Depends(rate_limit_ingest), session: Session = Depends(get_session)):
    """Called by the WP plugin on publish/update to push page/product content. The worker
    replaces previous chunks for this URL when it processes the job (so edits don't duplicate)."""
    job = _enqueue(session, client.id, "site-page", {"url": url, "text": text})
    return {"ok": True, "job_id": job.id, "status": job.status}


@app.post("/ingest/product")
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
    job = _enqueue(session, client.id, "product", {
        "url": url, "title": title, "price": price, "image_url": image_url, "text": text,
    })
    return {"ok": True, "job_id": job.id, "status": job.status}


@app.get("/ingest/jobs/{job_id}")
def ingest_job_status(job_id: int, client_id: int = Depends(resolve_client_id), session: Session = Depends(get_session)):
    """Poll the status of an enqueued ingest job (queued | processing | done | error)."""
    job = session.get(IngestJob, job_id)
    if not job or job.client_id != client_id:
        raise HTTPException(404, "job not found")
    return {"id": job.id, "kind": job.kind, "status": job.status, "error": job.error}


@app.post("/chat")
def chat_endpoint(
    visitor_id: str = Body(...),
    message: str = Body(...),
    conversation_id: int | None = Body(None),
    client: Client = Depends(rate_limit_chat),
    session: Session = Depends(get_session),
):
    if conversation_id:
        conv = session.get(Conversation, conversation_id)
        if not conv or conv.client_id != client.id:
            raise HTTPException(404, "conversation not found")
    else:
        conv = Conversation(client_id=client.id, visitor_id=visitor_id)
        session.add(conv)
        session.commit()
        session.refresh(conv)

    history = [
        {"role": m.role if m.role != "operator" else "assistant", "content": m.content}
        for m in session.exec(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)).all()
    ]
    session.add(Message(conversation_id=conv.id, role="user", content=message))
    session.commit()

    if conv.status == "escalated":
        return {"conversation_id": conv.id, "status": "escalated", "reply": None}

    lowered = message.lower()
    keyword_hit = next((k for k in ALWAYS_ESCALATE_KEYWORDS if k in lowered), None)
    if keyword_hit:
        reason = f"richiede intervento umano ({keyword_hit})"
        conv.status = "escalated"
        session.add(conv)
        ticket = Ticket(conversation_id=conv.id, reason=reason)
        session.add(ticket)
        session.commit()
        session.refresh(ticket)
        log(logger, logging.INFO, "chat.escalated", client_id=client.id, conversation_id=conv.id, trigger="keyword", keyword=keyword_hit)
        notify_new_ticket(client.name, conv.id, ticket.id, reason)
        return {"conversation_id": conv.id, "status": "escalated", "reply": None}

    try:
        context = retrieve(session, client.id, message)
        system = (
            "You are a customer support assistant. Handle greetings and small talk yourself, "
            "normally, without calling any tool. For substantive questions, answer only using "
            "the context below. Call escalate_to_human ONLY when: the answer to a substantive "
            "question isn't in the context, or the request needs human authority (refunds, "
            "complaints, account changes). Do not escalate greetings or vague messages — ask "
            "the user to clarify instead.\n\nContext:\n" + "\n---\n".join(context)
        )
        result = llm_chat(system, history, message)
    except LLMUnavailableError as exc:
        # model provider unreachable after retries — hand off instead of failing the request
        reason = "assistente AI non disponibile al momento"
        conv.status = "escalated"
        session.add(conv)
        ticket = Ticket(conversation_id=conv.id, reason=reason)
        session.add(ticket)
        session.commit()
        session.refresh(ticket)
        log(logger, logging.ERROR, "chat.llm_unavailable", client_id=client.id, conversation_id=conv.id, error=str(exc))
        notify_new_ticket(client.name, conv.id, ticket.id, reason)
        return {"conversation_id": conv.id, "status": "escalated", "reply": None}

    if "escalate" in result:
        conv.status = "escalated"
        session.add(conv)
        ticket = Ticket(conversation_id=conv.id, reason=result["escalate"])
        session.add(ticket)
        session.commit()
        session.refresh(ticket)
        log(logger, logging.INFO, "chat.escalated", client_id=client.id, conversation_id=conv.id, trigger="model", reason=result["escalate"])
        notify_new_ticket(client.name, conv.id, ticket.id, result["escalate"])
        return {"conversation_id": conv.id, "status": "escalated", "reply": None}

    session.add(Message(conversation_id=conv.id, role="assistant", content=result["reply"]))
    session.commit()
    try:
        products = retrieve_products(session, client.id, message)
    except LLMUnavailableError:
        products = []  # reply already succeeded; don't lose it over a second embedding call
    return {"conversation_id": conv.id, "status": "open", "reply": result["reply"], "products": products}


@app.get("/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: int, after_id: int = 0, client_id: int = Depends(resolve_client_id), session: Session = Depends(get_session)):
    """Polled by the chat widget (client api_key) and read by the panel (operator token)."""
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != client_id:
        raise HTTPException(404, "conversation not found")
    messages = session.exec(
        select(Message).where(Message.conversation_id == conversation_id, Message.id > after_id).order_by(Message.id)
    ).all()
    return {"status": conv.status, "messages": [{"id": m.id, "role": m.role, "content": m.content} for m in messages]}


@app.get("/conversations")
def list_conversations(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    convs = session.exec(
        select(Conversation).where(Conversation.client_id == operator.client_id).order_by(Conversation.created_at.desc())
    ).all()
    result = []
    for c in convs:
        last = session.exec(
            select(Message).where(Message.conversation_id == c.id).order_by(Message.id.desc())
        ).first()
        result.append({"conversation": c, "last_message": last.content if last else None})
    return result


@app.get("/tickets")
def list_tickets(status: str = "open", operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    tickets = session.exec(
        select(Ticket, Conversation)
        .join(Conversation, Ticket.conversation_id == Conversation.id)
        .where(Conversation.client_id == operator.client_id, Ticket.status == status)
    ).all()
    return [{"ticket": t, "conversation": c} for t, c in tickets]


@app.post("/tickets/{ticket_id}/reply")
def reply_ticket(ticket_id: int, reply: str, operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    ticket = session.get(Ticket, ticket_id)
    conv = session.get(Conversation, ticket.conversation_id) if ticket else None
    # verify the ticket belongs to this operator's client before replying as the operator
    if not ticket or not conv or conv.client_id != operator.client_id:
        raise HTTPException(404, "ticket not found")
    session.add(Message(conversation_id=ticket.conversation_id, role="operator", content=reply))
    ticket.status = "answered"
    conv.status = "open"
    session.add(ticket)
    session.add(conv)
    session.commit()
    return {"ok": True}


@app.get("/stats")
def stats(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    convs = session.exec(select(Conversation).where(Conversation.client_id == operator.client_id)).all()
    return {
        "total_conversations": len(convs),
        "escalated": sum(1 for c in convs if c.status == "escalated"),
        "closed": sum(1 for c in convs if c.status == "closed"),
    }


# ---- Admin: client onboarding (guarded by ADMIN_API_KEY) ----


@app.post("/admin/clients", dependencies=[Depends(require_admin)])
def create_client(name: str = Body(...), allowed_origins: str = Body(""), session: Session = Depends(get_session)):
    """Provision a new client and return its generated api_key. The key is shown only here —
    it's not stored in a recoverable form for listing, so capture it now. allowed_origins is a
    comma-separated list of widget origins (empty = no per-client origin enforcement)."""
    client = Client(name=name, api_key=secrets.token_urlsafe(32), allowed_origins=allowed_origins)
    session.add(client)
    session.commit()
    session.refresh(client)
    rebuild_allowed_origins(session)
    return {"id": client.id, "name": client.name, "api_key": client.api_key, "allowed_origins": client.allowed_origins}


@app.get("/admin/clients", dependencies=[Depends(require_admin)])
def list_clients(session: Session = Depends(get_session)):
    # deliberately omit api_key so a leaked admin listing doesn't hand out client keys
    return [{"id": c.id, "name": c.name, "allowed_origins": c.allowed_origins} for c in session.exec(select(Client)).all()]


@app.post("/admin/clients/{client_id}/origins", dependencies=[Depends(require_admin)])
def set_client_origins(client_id: int, allowed_origins: str = Body(..., embed=True), session: Session = Depends(get_session)):
    """Set the comma-separated widget origins allowed to use this client's key from a browser."""
    client = session.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")
    client.allowed_origins = allowed_origins
    session.add(client)
    session.commit()
    rebuild_allowed_origins(session)
    return {"id": client.id, "name": client.name, "allowed_origins": client.allowed_origins}


@app.post("/admin/clients/{client_id}/rotate-key", dependencies=[Depends(require_admin)])
def rotate_client_key(client_id: int, session: Session = Depends(get_session)):
    client = session.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")
    client.api_key = secrets.token_urlsafe(32)
    session.add(client)
    session.commit()
    return {"id": client.id, "name": client.name, "api_key": client.api_key}


@app.post("/admin/clients/{client_id}/operators", dependencies=[Depends(require_admin)])
def create_operator(client_id: int, email: str = Body(...), password: str = Body(...), session: Session = Depends(get_session)):
    """Provision a panel operator for a client. Password is stored hashed (PBKDF2)."""
    if not session.get(Client, client_id):
        raise HTTPException(404, "client not found")
    if session.exec(select(Operator).where(Operator.email == email)).first():
        raise HTTPException(409, "email already registered")
    operator = Operator(client_id=client_id, email=email, password_hash=hash_password(password))
    session.add(operator)
    session.commit()
    session.refresh(operator)
    return {"id": operator.id, "client_id": client_id, "email": email}


# ---- Operator auth (panel login) ----


@app.post("/operator/login")
def operator_login(email: str = Body(...), password: str = Body(...), session: Session = Depends(get_session)):
    operator = session.exec(select(Operator).where(Operator.email == email)).first()
    if not operator or not verify_password(password, operator.password_hash):
        raise HTTPException(401, "invalid credentials")
    token = secrets.token_urlsafe(32)
    session.add(OperatorSession(operator_id=operator.id, client_id=operator.client_id, token=token))
    session.commit()
    return {"token": token, "client_id": operator.client_id, "email": operator.email}


@app.post("/operator/logout")
def operator_logout(authorization: str = Header(None), operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    op_session = session.exec(
        select(OperatorSession).where(OperatorSession.token == _bearer_token(authorization))
    ).first()
    if op_session:
        session.delete(op_session)
        session.commit()
    return {"ok": True}

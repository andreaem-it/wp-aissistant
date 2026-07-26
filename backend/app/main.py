import json
import logging
import os
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import stripe
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request, Response, UploadFile
from sqlalchemy import and_, func, or_
from sqlmodel import Session, select

from . import billing

from .db import (
    AiResponseLog,
    AuditLog,
    AuthToken,
    Chunk,
    Client,
    Conversation,
    IngestJob,
    Message,
    Operator,
    OperatorSession,
    Plan,
    Product,
    Ticket,
    engine,
    get_session,
    init_db,
)
from . import email as email_service
from fastapi.responses import StreamingResponse

from .llm import ESCALATE_PREFIX, LLMUnavailableError
from .llm import chat as llm_chat
from .llm import chat_stream as llm_chat_stream
from .llm import embed
from .logging_config import log, request_id_var, setup_logging
from . import metrics
from .notify import notify_new_ticket
from .rag import extract_text, retrieve, retrieve_products, retrieve_with_meta
from .ratelimit import make_limiter
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


# On Railway there's no reverse proxy in front to filter these, so gate them in the app:
# docs are off unless explicitly enabled, and /metrics needs a token (see below).
DOCS_ENABLED = os.getenv("DOCS_ENABLED", "false").lower() == "true"
METRICS_TOKEN = os.getenv("METRICS_TOKEN")

app = FastAPI(
    title="wp-aissistant backend",
    lifespan=lifespan,
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
)


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
        elapsed = time.monotonic() - start
        log(
            logger, logging.INFO, "request.complete",
            method=request.method, path=request.url.path,
            status_code=response.status_code, duration_ms=round(elapsed * 1000, 1),
        )
        # record Prometheus metrics keyed by the route *template* (not the raw path) to
        # keep label cardinality bounded; skip the scrape endpoint itself
        route = request.scope.get("route")
        metric_path = route.path if route is not None else "__unmatched__"
        if metric_path != "/metrics":
            metrics.http_requests_total.labels(request.method, metric_path, response.status_code).inc()
            metrics.http_request_duration_seconds.labels(request.method, metric_path).observe(elapsed)
        response.headers["X-Request-Id"] = request_id
        return response
    finally:
        request_id_var.reset(token)


@app.get("/metrics")
def metrics_endpoint(authorization: str = Header(None)):
    """Prometheus scrape endpoint. Disabled (404) unless METRICS_TOKEN is set; when set,
    requires `Authorization: Bearer <METRICS_TOKEN>`. Scrape config: set the bearer token."""
    if not METRICS_TOKEN:
        raise HTTPException(404, "not found")
    token = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""
    if not secrets.compare_digest(token, METRICS_TOKEN):
        raise HTTPException(401, "unauthorized")
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health():
    """Liveness probe (no auth) for container/orchestrator health checks."""
    return {"status": "ok"}

# admin token for client onboarding endpoints; unset => the /admin surface is disabled (fail closed)
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")

# TTLs for single-use email tokens (app/email.py sends the links)
RESET_TOKEN_TTL = timedelta(hours=int(os.getenv("RESET_TOKEN_TTL_HOURS", "1")))
VERIFY_TOKEN_TTL = timedelta(hours=int(os.getenv("VERIFY_TOKEN_TTL_HOURS", "48")))

# /chat hits the LLM on every call, so it's the main abuse/cost surface — limit per client+IP.
# Ingest is limited per client. Windows are 60s; override the counts via env.
chat_limiter = make_limiter(int(os.getenv("CHAT_RATE_LIMIT", "30")), 60)
ingest_limiter = make_limiter(int(os.getenv("INGEST_RATE_LIMIT", "60")), 60)

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


def _normalize_origins(raw: str) -> str:
    """Reduce each comma-separated entry to a browser Origin (scheme://host[:port]), dropping
    any path/query/fragment. A browser's Origin header never includes a path, so a value like
    'https://site.it/shop' could never match and would silently 403 the widget. Tolerates a
    missing scheme; leaves an unparseable entry as-is."""
    from urllib.parse import urlparse

    out: list[str] = []
    for entry in _split_origins(raw):
        parsed = urlparse(entry if "//" in entry else "//" + entry)
        if parsed.scheme and parsed.netloc:
            normalized = f"{parsed.scheme}://{parsed.netloc}"
        elif parsed.netloc:
            normalized = parsed.netloc  # host only (no scheme given)
        else:
            normalized = entry
        if normalized not in out:
            out.append(normalized)
    return ",".join(out)


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


def _plan_limit(session: Session, client: Client, attr: str, fallback: int) -> int:
    """The client's plan limit for `attr` (chat_rate_limit/ingest_rate_limit), or the
    global default if the client has no plan (shouldn't happen post-migration, but a
    missing/deleted plan must degrade to *some* limit rather than 500)."""
    plan = session.get(Plan, client.plan_id) if client.plan_id else None
    return getattr(plan, attr) if plan else fallback


def rate_limit_chat(request: Request, client: Client = Depends(require_client), session: Session = Depends(get_session)) -> Client:
    # enforceable per-client binding: a browser call with this client's key must come from
    # one of its configured origins (skipped when unconfigured or for server-side calls)
    allowed = _split_origins(client.allowed_origins)
    origin = request.headers.get("origin")
    if allowed and origin and origin not in allowed:
        raise HTTPException(403, "origin not allowed for this client")
    ip = request.client.host if request.client else "unknown"
    limit = _plan_limit(session, client, "chat_rate_limit", chat_limiter.limit)
    chat_limiter.check(f"chat:{client.id}:{ip}", limit=limit)
    return client


def rate_limit_ingest(client: Client = Depends(require_client), session: Session = Depends(get_session)) -> Client:
    limit = _plan_limit(session, client, "ingest_rate_limit", ingest_limiter.limit)
    ingest_limiter.check(f"ingest:{client.id}", limit=limit)
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


def _log_ai_response(session, client_id, conversation_id, outcome, retrieval_meta=None, llm_meta=None, message_id=None):
    """Persist one AiResponseLog row (the admin debug/stats record for a /chat turn). Never
    raises — diagnostics must not break the chat flow."""
    m = llm_meta or {}
    try:
        session.add(AiResponseLog(
            client_id=client_id,
            conversation_id=conversation_id,
            message_id=message_id,
            outcome=outcome,
            model=m.get("model", "") or "",
            latency_ms=int(m.get("latency_ms", 0) or 0),
            tokens_prompt=int(m.get("tokens_prompt", 0) or 0),
            tokens_completion=int(m.get("tokens_completion", 0) or 0),
            retrieved=json.dumps(retrieval_meta or []),
        ))
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        log(logger, logging.WARNING, "ai_response_log.failed", conversation_id=conversation_id, error=str(exc))


def _audit(session, actor_type, actor_id, action, target="", client_id=None, detail=None):
    """Append an AuditLog entry. Best-effort: a logging failure must never fail the action
    it records, so errors are swallowed (and logged)."""
    try:
        session.add(AuditLog(
            actor_type=actor_type, actor_id=str(actor_id), action=action,
            target=target, client_id=client_id, detail=json.dumps(detail or {}),
        ))
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        log(logger, logging.WARNING, "audit.failed", action=action, error=str(exc))


def _build_system(context: list[str]) -> str:
    return (
        "You are a customer support assistant. Handle greetings and small talk yourself, "
        "normally, without calling any tool. For substantive questions, answer only using "
        "the context below. Call escalate_to_human ONLY when: the answer to a substantive "
        "question isn't in the context, or the request needs human authority (refunds, "
        "complaints, account changes). Do not escalate greetings or vague messages — ask "
        "the user to clarify instead.\n\nContext:\n" + "\n---\n".join(context)
    )


def _escalate(session, client_id, client_name, conv, reason, *, outcome, trigger,
              retrieval_meta=None, llm_meta=None, error=None):
    """Shared escalation: mark the conversation escalated, open a ticket, log + count the
    escalation, record the AI-response diagnostics, and notify operators. Used by both the
    sync /chat and the streaming /chat/stream so the two stay in lockstep."""
    conv.status = "escalated"
    conv.updated_at = datetime.utcnow()
    session.add(conv)
    ticket = Ticket(conversation_id=conv.id, reason=reason)
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    if error is not None:
        log(logger, logging.ERROR, "chat.llm_unavailable", client_id=client_id, conversation_id=conv.id, error=error)
    else:
        log(logger, logging.INFO, "chat.escalated", client_id=client_id, conversation_id=conv.id, trigger=trigger, reason=reason)
    metrics.escalations_total.labels(trigger=trigger).inc()
    _log_ai_response(session, client_id, conv.id, outcome, retrieval_meta=retrieval_meta, llm_meta=llm_meta)
    notify_new_ticket(client_name, conv.id, ticket.id, reason)
    return ticket


def _sse(payload: dict) -> str:
    """Serialize one Server-Sent Event frame."""
    return f"data: {json.dumps(payload)}\n\n"


@app.post("/chat/stream")
def chat_stream_endpoint(
    visitor_id: str = Body(...),
    message: str = Body(...),
    conversation_id: int | None = Body(None),
    client: Client = Depends(rate_limit_chat),
    session: Session = Depends(get_session),
):
    """Streaming variant of /chat over Server-Sent Events. Emits JSON frames:
      {"type":"start","conversation_id"} → {"type":"token","text"}* →
      {"type":"done","conversation_id","message_id","products"}  (answered)
      or {"type":"escalated","conversation_id"}                  (handed to a human)
      or {"type":"error"}                                        (unexpected failure).
    Escalation is decided by buffering the first tokens (same ESCALATE_PREFIX convention as
    /chat) before any token is shown, so an escalation never leaks a partial reply.
    The sync /chat endpoint stays available as a fallback for older widgets."""
    client_id = client.id
    client_name = client.name
    # validate ownership up front so we can 404 *before* the stream starts
    if conversation_id:
        conv = session.get(Conversation, conversation_id)
        if not conv or conv.client_id != client_id:
            raise HTTPException(404, "conversation not found")

    def event_stream():
        # a fresh session: the request-scoped one closes when this function returns, before the
        # generator is consumed while streaming
        with Session(engine) as s:
            if conversation_id:
                conv = s.get(Conversation, conversation_id)
            else:
                conv = Conversation(client_id=client_id, visitor_id=visitor_id)
                s.add(conv)
                s.commit()
                s.refresh(conv)

            history = [
                {"role": m.role if m.role != "operator" else "assistant", "content": m.content}
                for m in s.exec(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)).all()
            ]
            s.add(Message(conversation_id=conv.id, role="user", content=message))
            conv.updated_at = datetime.utcnow()
            s.add(conv)
            s.commit()
            metrics.chat_messages_total.inc()

            yield _sse({"type": "start", "conversation_id": conv.id})

            if conv.status == "escalated":
                yield _sse({"type": "escalated", "conversation_id": conv.id})
                return

            lowered = message.lower()
            keyword_hit = next((k for k in ALWAYS_ESCALATE_KEYWORDS if k in lowered), None)
            if keyword_hit:
                reason = f"richiede intervento umano ({keyword_hit})"
                _escalate(s, client_id, client_name, conv, reason, outcome="escalated_keyword", trigger="keyword")
                yield _sse({"type": "escalated", "conversation_id": conv.id})
                return

            retrieval_meta: list[dict] = []
            buffer = ""
            decided = False
            is_escalation = False
            full = ""
            meta: dict = {}
            try:
                context, retrieval_meta = retrieve_with_meta(s, client_id, message)
                system = _build_system(context)
                for kind, payload in llm_chat_stream(system, history, message):
                    if kind == "meta":
                        meta = payload
                        continue
                    full += payload
                    if not decided:
                        buffer += payload
                        # decide escalation only once enough has arrived to compare the prefix
                        if len(buffer) >= len(ESCALATE_PREFIX) or "\n" in buffer:
                            decided = True
                            is_escalation = buffer.startswith(ESCALATE_PREFIX)
                            if not is_escalation and buffer:
                                yield _sse({"type": "token", "text": buffer})
                    elif not is_escalation:
                        yield _sse({"type": "token", "text": payload})
            except LLMUnavailableError as exc:
                reason = "assistente AI non disponibile al momento"
                _escalate(s, client_id, client_name, conv, reason, outcome="escalated_llm_down",
                          trigger="llm_down", retrieval_meta=retrieval_meta, error=str(exc))
                yield _sse({"type": "escalated", "conversation_id": conv.id})
                return

            # very short output that never reached the decision threshold
            if not decided:
                is_escalation = full.startswith(ESCALATE_PREFIX)
                if not is_escalation and full:
                    yield _sse({"type": "token", "text": full})

            if is_escalation:
                reason = full[len(ESCALATE_PREFIX):].strip() or "unspecified"
                _escalate(s, client_id, client_name, conv, reason, outcome="escalated_model",
                          trigger="model", retrieval_meta=retrieval_meta, llm_meta=meta)
                yield _sse({"type": "escalated", "conversation_id": conv.id})
                return

            reply_msg = Message(conversation_id=conv.id, role="assistant", content=full)
            s.add(reply_msg)
            conv.updated_at = datetime.utcnow()
            s.add(conv)
            s.commit()
            s.refresh(reply_msg)
            _log_ai_response(s, client_id, conv.id, "answered", retrieval_meta=retrieval_meta, llm_meta=meta, message_id=reply_msg.id)
            try:
                products = retrieve_products(s, client_id, message)
            except LLMUnavailableError:
                products = []
            yield _sse({"type": "done", "conversation_id": conv.id, "message_id": reply_msg.id, "products": products})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    conv.updated_at = datetime.utcnow()
    session.add(conv)
    session.commit()
    metrics.chat_messages_total.inc()

    if conv.status == "escalated":
        return {"conversation_id": conv.id, "status": "escalated", "reply": None}

    lowered = message.lower()
    keyword_hit = next((k for k in ALWAYS_ESCALATE_KEYWORDS if k in lowered), None)
    if keyword_hit:
        reason = f"richiede intervento umano ({keyword_hit})"
        conv.status = "escalated"
        conv.updated_at = datetime.utcnow()
        session.add(conv)
        ticket = Ticket(conversation_id=conv.id, reason=reason)
        session.add(ticket)
        session.commit()
        session.refresh(ticket)
        log(logger, logging.INFO, "chat.escalated", client_id=client.id, conversation_id=conv.id, trigger="keyword", keyword=keyword_hit)
        metrics.escalations_total.labels(trigger="keyword").inc()
        _log_ai_response(session, client.id, conv.id, "escalated_keyword")
        notify_new_ticket(client.name, conv.id, ticket.id, reason)
        return {"conversation_id": conv.id, "status": "escalated", "reply": None}

    retrieval_meta: list[dict] = []
    try:
        context, retrieval_meta = retrieve_with_meta(session, client.id, message)
        system = _build_system(context)
        result = llm_chat(system, history, message)
    except LLMUnavailableError as exc:
        # model provider unreachable after retries — hand off instead of failing the request
        reason = "assistente AI non disponibile al momento"
        conv.status = "escalated"
        conv.updated_at = datetime.utcnow()
        session.add(conv)
        ticket = Ticket(conversation_id=conv.id, reason=reason)
        session.add(ticket)
        session.commit()
        session.refresh(ticket)
        log(logger, logging.ERROR, "chat.llm_unavailable", client_id=client.id, conversation_id=conv.id, error=str(exc))
        metrics.escalations_total.labels(trigger="llm_down").inc()
        _log_ai_response(session, client.id, conv.id, "escalated_llm_down", retrieval_meta=retrieval_meta)
        notify_new_ticket(client.name, conv.id, ticket.id, reason)
        return {"conversation_id": conv.id, "status": "escalated", "reply": None}

    if "escalate" in result:
        conv.status = "escalated"
        conv.updated_at = datetime.utcnow()
        session.add(conv)
        ticket = Ticket(conversation_id=conv.id, reason=result["escalate"])
        session.add(ticket)
        session.commit()
        session.refresh(ticket)
        log(logger, logging.INFO, "chat.escalated", client_id=client.id, conversation_id=conv.id, trigger="model", reason=result["escalate"])
        metrics.escalations_total.labels(trigger="model").inc()
        _log_ai_response(session, client.id, conv.id, "escalated_model", retrieval_meta=retrieval_meta, llm_meta=result)
        notify_new_ticket(client.name, conv.id, ticket.id, result["escalate"])
        return {"conversation_id": conv.id, "status": "escalated", "reply": None}

    reply_msg = Message(conversation_id=conv.id, role="assistant", content=result["reply"])
    session.add(reply_msg)
    conv.updated_at = datetime.utcnow()
    session.add(conv)
    session.commit()
    session.refresh(reply_msg)
    _log_ai_response(session, client.id, conv.id, "answered", retrieval_meta=retrieval_meta, llm_meta=result, message_id=reply_msg.id)
    try:
        products = retrieve_products(session, client.id, message)
    except LLMUnavailableError:
        products = []  # reply already succeeded; don't lose it over a second embedding call
    return {"conversation_id": conv.id, "status": "open", "reply": result["reply"], "products": products, "message_id": reply_msg.id}


@app.post("/chat/feedback")
def chat_feedback(
    conversation_id: int = Body(...),
    message_id: int = Body(...),
    value: str = Body(...),  # "up" | "down"
    client: Client = Depends(require_client),
    session: Session = Depends(get_session),
):
    """Visitor rates an assistant reply (👍/👎). Scoped by the client api_key + conversation
    ownership; only assistant messages can be rated. Idempotent — re-voting overwrites."""
    if value not in ("up", "down"):
        raise HTTPException(400, "value must be 'up' or 'down'")
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != client.id:
        raise HTTPException(404, "conversation not found")
    msg = session.get(Message, message_id)
    if not msg or msg.conversation_id != conversation_id or msg.role != "assistant":
        raise HTTPException(404, "message not found")
    msg.feedback = 1 if value == "up" else -1
    session.add(msg)
    session.commit()
    return {"ok": True}


@app.post("/chat/contact")
def chat_contact(
    conversation_id: int = Body(...),
    email: str = Body(...),
    url: str | None = Body(None),
    client: Client = Depends(require_client),
    session: Session = Depends(get_session),
):
    """The visitor leaves an email (typically after escalation) to be notified when an operator
    replies. `url` is the page they're on, used as the return link in the notification email."""
    if "@" not in email:
        raise HTTPException(400, "invalid email")
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != client.id:
        raise HTTPException(404, "conversation not found")
    conv.visitor_email = email.strip()[:255]
    if url:
        conv.visitor_url = url[:1000]
    session.add(conv)
    session.commit()
    return {"ok": True}


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
    now = datetime.utcnow()
    ticket.status = "answered"
    ticket.updated_at = now
    conv.status = "open"
    conv.updated_at = now
    session.add(ticket)
    session.add(conv)
    session.commit()
    _audit(session, "operator", operator.email, "ticket.reply", target=f"ticket:{ticket_id}", client_id=operator.client_id)
    # notify the visitor by email if they left one (best-effort: a mail failure never blocks the reply)
    if conv.visitor_email:
        client = session.get(Client, operator.client_id)
        email_service.send_visitor_reply(conv.visitor_email, client.name if client else "il supporto", conv.visitor_url)
    return {"ok": True}


@app.get("/knowledge-base")
def list_knowledge_base(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """What's actually been ingested for this client — documents/pages grouped by
    source (deduped, the worker replaces old chunks on re-sync) and products."""
    rows = session.exec(
        select(Chunk.source, Chunk.source_ref, func.count(Chunk.id), func.max(Chunk.id))
        .where(Chunk.client_id == operator.client_id)
        .group_by(Chunk.source, Chunk.source_ref)
        .order_by(func.max(Chunk.id).desc())
    ).all()
    documents = [
        {"source": source, "source_ref": ref, "chunks": count}
        for source, ref, count, _ in rows
    ]
    products = session.exec(
        select(Product)
        .where(Product.client_id == operator.client_id)
        .order_by(Product.id.desc())
    ).all()
    return {
        "documents": documents,
        "products": [
            {"title": p.title, "price": p.price, "image_url": p.image_url, "product_url": p.product_url}
            for p in products
        ],
    }


# ---- Analytics helpers (shared by operator /stats and admin /admin/stats) ----


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


def _build_stats(session: Session, client_id: int | None) -> dict:
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
        "volume_daily": _daily_volume(session, client_id),
    }


@app.get("/stats")
def stats(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    data = _build_stats(session, operator.client_id)
    # keep the original flat keys so older panel builds keep working
    data["total_conversations"] = data["conversations"]["total"]
    data["escalated"] = data["conversations"]["escalated"]
    data["closed"] = data["conversations"]["closed"]
    return data


@app.get("/admin/stats", dependencies=[Depends(require_admin)])
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


@app.get("/admin/health", dependencies=[Depends(require_admin)])
def admin_health(session: Session = Depends(get_session)):
    """Operational snapshot for the superadmin: DB reachability, ingest queue depth (incl.
    errored jobs), worker flag, applied migration, configured models, and app version."""
    from .llm import CHAT_MODEL, EMBED_MODEL

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
        "version": os.getenv("APP_VERSION", "dev"),
    }


@app.post("/admin/test-email", dependencies=[Depends(require_admin)])
def admin_test_email(to: str = Body(..., embed=True)):
    """Send a diagnostic email to verify SMTP end-to-end. Reports whether SMTP is configured
    and whether the send succeeded (never exposes credentials)."""
    if not email_service.enabled():
        return {"configured": False, "sent": False, "detail": "SMTP non configurato (imposta SMTP_HOST)"}
    sent = email_service.send_test(to)
    return {"configured": True, "sent": sent, "detail": "Inviata" if sent else "Invio fallito — controlla le credenziali SMTP"}


@app.get("/admin/problematic", dependencies=[Depends(require_admin)])
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


# ---- Admin: client onboarding (guarded by ADMIN_API_KEY) ----


def _default_plan_id(session: Session) -> int:
    """The oldest plan (seeded "Free" on fresh DBs via migration 0005). Auto-creates one
    if missing entirely — e.g. DB_AUTO_CREATE dev setups that skip migrations."""
    plan = session.exec(select(Plan).order_by(Plan.id)).first()
    if not plan:
        plan = Plan(name="Free", chat_rate_limit=chat_limiter.limit, ingest_rate_limit=ingest_limiter.limit)
        session.add(plan)
        session.commit()
        session.refresh(plan)
    return plan.id


@app.post("/admin/clients", dependencies=[Depends(require_admin)])
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
    rebuild_allowed_origins(session)
    _audit(session, "admin", "admin", "client.create", target=f"client:{client.id}", client_id=client.id, detail={"name": name})
    return {"id": client.id, "name": client.name, "api_key": client.api_key, "allowed_origins": client.allowed_origins, "plan_id": client.plan_id}


@app.get("/admin/clients", dependencies=[Depends(require_admin)])
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


@app.post("/admin/clients/{client_id}/plan", dependencies=[Depends(require_admin)])
def set_client_plan(client_id: int, plan_id: int = Body(..., embed=True), session: Session = Depends(get_session)):
    client = session.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")
    if not session.get(Plan, plan_id):
        raise HTTPException(404, "plan not found")
    client.plan_id = plan_id
    session.add(client)
    session.commit()
    _audit(session, "admin", "admin", "client.set_plan", target=f"client:{client_id}", client_id=client_id, detail={"plan_id": plan_id})
    return {"id": client.id, "plan_id": client.plan_id}


@app.get("/admin/conversations/{conversation_id}/debug", dependencies=[Depends(require_admin)])
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


@app.get("/admin/audit", dependencies=[Depends(require_admin)])
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


@app.get("/admin/plans", dependencies=[Depends(require_admin)])
def list_plans(session: Session = Depends(get_session)):
    return session.exec(select(Plan).order_by(Plan.id)).all()


@app.post("/admin/plans", dependencies=[Depends(require_admin)])
def create_plan(
    name: str = Body(...),
    price_cents: int = Body(0),
    currency: str = Body("eur"),
    chat_rate_limit: int = Body(30),
    ingest_rate_limit: int = Body(60),
    stripe_price_id: str = Body(""),
    session: Session = Depends(get_session),
):
    if session.exec(select(Plan).where(Plan.name == name)).first():
        raise HTTPException(409, "a plan with this name already exists")
    plan = Plan(
        name=name, price_cents=price_cents, currency=currency,
        chat_rate_limit=chat_rate_limit, ingest_rate_limit=ingest_rate_limit,
        stripe_price_id=stripe_price_id,
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


@app.post("/admin/plans/{plan_id}", dependencies=[Depends(require_admin)])
def update_plan(plan_id: int, stripe_price_id: str = Body(..., embed=True), session: Session = Depends(get_session)):
    """Set the Stripe price id for a plan (needed before checkout can use it)."""
    plan = session.get(Plan, plan_id)
    if not plan:
        raise HTTPException(404, "plan not found")
    plan.stripe_price_id = stripe_price_id
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


# ---- Billing (Stripe) ----


@app.post("/billing/checkout")
def billing_checkout(plan_id: int = Body(..., embed=True), operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """Start a Stripe Checkout session for the operator's client to subscribe to `plan_id`.
    Returns the hosted checkout URL to redirect the browser to."""
    if not billing.enabled():
        raise HTTPException(503, "billing not configured")
    plan = session.get(Plan, plan_id)
    if not plan:
        raise HTTPException(404, "plan not found")
    if not plan.stripe_price_id:
        raise HTTPException(400, "plan has no stripe_price_id")
    client = session.get(Client, operator.client_id)

    params = {
        "mode": "subscription",
        "line_items": [{"price": plan.stripe_price_id, "quantity": 1}],
        "success_url": billing.SUCCESS_URL,
        "cancel_url": billing.CANCEL_URL,
        "client_reference_id": str(client.id),
        "metadata": {"client_id": str(client.id), "plan_id": str(plan.id)},
        # carry ids onto the subscription too, so later subscription.* events map back to the client
        "subscription_data": {"metadata": {"client_id": str(client.id), "plan_id": str(plan.id)}},
    }
    if client.stripe_customer_id:
        params["customer"] = client.stripe_customer_id
    checkout = stripe.checkout.Session.create(**params)
    return {"checkout_url": checkout.url, "id": checkout.id}


@app.post("/billing/webhook")
async def billing_webhook(request: Request, session: Session = Depends(get_session)):
    """Stripe webhook: verifies the signature, then syncs the client's plan/billing status."""
    if not billing.enabled():
        raise HTTPException(503, "billing not configured")
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, signature, billing.STRIPE_WEBHOOK_SECRET)
    except Exception:  # noqa: BLE001 — bad signature or malformed payload
        raise HTTPException(400, "invalid signature")
    billing.handle_event(session, event)
    return {"received": True}


@app.get("/billing/plans")
def billing_plans(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """Plans visible to an operator for self-serve upgrades (purchasable = has a Stripe price)."""
    return [
        {
            "id": p.id, "name": p.name, "price_cents": p.price_cents,
            "currency": p.currency, "purchasable": bool(p.stripe_price_id),
        }
        for p in session.exec(select(Plan).order_by(Plan.id)).all()
    ]


@app.get("/public/plans")
def public_plans(session: Session = Depends(get_session)):
    """Purchasable plans for the public signup page (no auth). Free/priceless plans are hidden."""
    return [
        {"id": p.id, "name": p.name, "price_cents": p.price_cents, "currency": p.currency}
        for p in session.exec(select(Plan).order_by(Plan.id)).all()
        if p.stripe_price_id
    ]


@app.post("/signup")
def signup(
    company_name: str = Body(...),
    email: str = Body(...),
    password: str = Body(...),
    plan_id: int = Body(...),
    session: Session = Depends(get_session),
):
    """Self-serve registration: create the account (on the Free plan, 'incomplete' until paid)
    and start a Stripe Checkout subscription with a free trial + card capture. The chosen plan is
    applied by the webhook once checkout completes. Returns the hosted checkout URL."""
    if not billing.enabled():
        raise HTTPException(503, "billing not configured")
    plan = session.get(Plan, plan_id)
    if not plan or not plan.stripe_price_id:
        raise HTTPException(400, "invalid plan")

    existing = session.exec(select(Operator).where(Operator.email == email)).first()
    if existing:
        client = session.get(Client, existing.client_id)
        # allow re-signup only if the previous attempt never completed payment
        if not client or client.billing_status != "incomplete":
            raise HTTPException(409, "email already registered")
        existing.password_hash = hash_password(password)
        session.add(existing)
        session.commit()
        operator = existing
    else:
        client = Client(
            name=company_name,
            api_key=secrets.token_urlsafe(32),
            plan_id=_default_plan_id(session),  # Free limits until the subscription activates
            billing_status="incomplete",
        )
        session.add(client)
        session.commit()
        session.refresh(client)
        operator = Operator(client_id=client.id, email=email, password_hash=hash_password(password))
        session.add(operator)
        session.commit()
        session.refresh(operator)
        rebuild_allowed_origins(session)

    # Email verification is enforced ONLY when SMTP is actually configured — otherwise the link
    # can't be delivered and blocking login would be a footgun. With SMTP: send the link and keep
    # login blocked until confirmed (best-effort send; they can also /auth/resend-verification).
    # Without SMTP: create the account already usable.
    if not operator.email_verified:
        if email_service.enabled():
            token = _issue_token(session, operator.id, "verify_email", VERIFY_TOKEN_TTL)
            email_service.send_verification(operator.email, token)
        else:
            operator.email_verified = True
            session.add(operator)
            session.commit()

    meta = {"client_id": str(client.id), "plan_id": str(plan.id)}
    checkout = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
        success_url=billing.SUCCESS_URL,
        cancel_url=billing.CANCEL_URL,
        client_reference_id=str(client.id),
        payment_method_collection="always",  # capture a card even during the free trial
        metadata=meta,
        subscription_data={"trial_period_days": billing.TRIAL_DAYS, "metadata": meta},
    )
    return {"checkout_url": checkout.url}


@app.get("/admin/clients/{client_id}/operators", dependencies=[Depends(require_admin)])
def list_operators(client_id: int, session: Session = Depends(get_session)):
    operators = session.exec(select(Operator).where(Operator.client_id == client_id)).all()
    return [{"id": o.id, "email": o.email, "created_at": o.created_at} for o in operators]


@app.delete("/admin/operators/{operator_id}", dependencies=[Depends(require_admin)])
def delete_operator(operator_id: int, session: Session = Depends(get_session)):
    operator = session.get(Operator, operator_id)
    if not operator:
        raise HTTPException(404, "operator not found")
    for s in session.exec(select(OperatorSession).where(OperatorSession.operator_id == operator_id)).all():
        session.delete(s)
    session.commit()  # flush the FK-dependent sessions before deleting their operator
    client_id = operator.client_id
    session.delete(operator)
    session.commit()
    _audit(session, "admin", "admin", "operator.delete", target=f"operator:{operator_id}", client_id=client_id)
    return {"ok": True}


@app.post("/admin/clients/{client_id}/origins", dependencies=[Depends(require_admin)])
def set_client_origins(client_id: int, allowed_origins: str = Body(..., embed=True), session: Session = Depends(get_session)):
    """Set the comma-separated widget origins allowed to use this client's key from a browser."""
    client = session.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")
    client.allowed_origins = _normalize_origins(allowed_origins)
    session.add(client)
    session.commit()
    rebuild_allowed_origins(session)
    _audit(session, "admin", "admin", "client.set_origins", target=f"client:{client_id}", client_id=client_id, detail={"allowed_origins": client.allowed_origins})
    return {"id": client.id, "name": client.name, "allowed_origins": client.allowed_origins}


@app.post("/admin/clients/{client_id}/rotate-key", dependencies=[Depends(require_admin)])
def rotate_client_key(client_id: int, session: Session = Depends(get_session)):
    client = session.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")
    client.api_key = secrets.token_urlsafe(32)
    session.add(client)
    session.commit()
    _audit(session, "admin", "admin", "client.rotate_key", target=f"client:{client_id}", client_id=client_id)
    return {"id": client.id, "name": client.name, "api_key": client.api_key}


@app.post("/admin/clients/{client_id}/operators", dependencies=[Depends(require_admin)])
def create_operator(client_id: int, email: str = Body(...), password: str = Body(...), session: Session = Depends(get_session)):
    """Provision a panel operator for a client. Password is stored hashed (PBKDF2)."""
    if not session.get(Client, client_id):
        raise HTTPException(404, "client not found")
    if session.exec(select(Operator).where(Operator.email == email)).first():
        raise HTTPException(409, "email already registered")
    # admin-provisioned by a trusted human => no email round-trip needed, log in right away
    operator = Operator(client_id=client_id, email=email, password_hash=hash_password(password), email_verified=True)
    session.add(operator)
    session.commit()
    session.refresh(operator)
    _audit(session, "admin", "admin", "operator.create", target=f"operator:{operator.id}", client_id=client_id, detail={"email": email})
    return {"id": operator.id, "client_id": client_id, "email": email}


@app.post("/admin/reembed", dependencies=[Depends(require_admin)])
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


# ---- Operator self-service (own account + own client's widget key) ----


@app.get("/me")
def get_me(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    client = session.get(Client, operator.client_id)
    plan = session.get(Plan, client.plan_id) if client.plan_id else None
    return {
        "email": operator.email,
        "client_name": client.name,
        "api_key": client.api_key,
        "plan_id": client.plan_id,
        "plan_name": plan.name if plan else None,
        "billing_status": client.billing_status,
    }


@app.post("/me/password")
def change_password(
    current_password: str = Body(...),
    new_password: str = Body(...),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    if not verify_password(current_password, operator.password_hash):
        raise HTTPException(401, "current password is incorrect")
    if len(new_password) < 8:
        raise HTTPException(400, "new password must be at least 8 characters")
    operator.password_hash = hash_password(new_password)
    session.add(operator)
    session.commit()
    return {"ok": True}


@app.post("/me/rotate-key")
def rotate_own_key(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """Rotate the widget api_key for the operator's own client. Old key stops working
    immediately — the WP plugin (or anything else using it) needs the new key."""
    client = session.get(Client, operator.client_id)
    client.api_key = secrets.token_urlsafe(32)
    session.add(client)
    session.commit()
    return {"api_key": client.api_key}


# ---- Auth: email verification + password reset ----


def _issue_token(session: Session, operator_id: int, purpose: str, ttl: timedelta) -> str:
    """Create a single-use token for an email flow and return its opaque value. Any
    outstanding unused token of the same purpose is invalidated first, so only the latest
    link works (re-requesting a reset shouldn't leave older links live)."""
    now = datetime.utcnow()
    for old in session.exec(
        select(AuthToken).where(
            AuthToken.operator_id == operator_id,
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
        )
    ).all():
        old.used_at = now
        session.add(old)
    token = secrets.token_urlsafe(32)
    session.add(AuthToken(operator_id=operator_id, purpose=purpose, token=token, expires_at=now + ttl))
    session.commit()
    return token


def _consume_token(session: Session, token: str, purpose: str) -> Operator | None:
    """Validate a token for the given purpose; if valid, mark it used and return the
    operator. Returns None for unknown/expired/already-used/wrong-purpose tokens."""
    row = session.exec(select(AuthToken).where(AuthToken.token == token)).first()
    if not row or row.purpose != purpose or row.used_at is not None or row.expires_at < datetime.utcnow():
        return None
    row.used_at = datetime.utcnow()
    session.add(row)
    session.commit()
    return session.get(Operator, row.operator_id)


@app.post("/auth/verify-email")
def verify_email(token: str = Body(..., embed=True), session: Session = Depends(get_session)):
    """Confirm an operator's email from the link sent at signup. Idempotent-ish: a used or
    expired token 400s, but an already-verified operator re-clicking simply succeeds again
    only while the token is fresh — after that they can just log in."""
    operator = _consume_token(session, token, "verify_email")
    if not operator:
        raise HTTPException(400, "invalid or expired token")
    if not operator.email_verified:
        operator.email_verified = True
        session.add(operator)
        session.commit()
    log(logger, logging.INFO, "auth.email_verified", operator_id=operator.id)
    return {"ok": True}


@app.post("/auth/resend-verification")
def resend_verification(email: str = Body(..., embed=True), session: Session = Depends(get_session)):
    """Re-send the verification email. Like /auth/forgot, always returns ok to avoid leaking
    which emails are registered; only actually sends for an existing, still-unverified account."""
    operator = session.exec(select(Operator).where(Operator.email == email)).first()
    if operator and not operator.email_verified:
        token = _issue_token(session, operator.id, "verify_email", VERIFY_TOKEN_TTL)
        email_service.send_verification(operator.email, token)
    return {"ok": True}


@app.post("/auth/forgot")
def forgot_password(email: str = Body(..., embed=True), session: Session = Depends(get_session)):
    """Start a password reset. Always returns ok (no user enumeration); when the email maps
    to an operator, issue a single-use token and email the reset link."""
    operator = session.exec(select(Operator).where(Operator.email == email)).first()
    if operator:
        token = _issue_token(session, operator.id, "reset", RESET_TOKEN_TTL)
        email_service.send_password_reset(operator.email, token)
        log(logger, logging.INFO, "auth.reset_requested", operator_id=operator.id)
    return {"ok": True}


@app.post("/auth/reset")
def reset_password(
    token: str = Body(...),
    new_password: str = Body(...),
    session: Session = Depends(get_session),
):
    """Complete a password reset. Consumes the token, sets the new password, and revokes all
    of the operator's active sessions so a leaked/old login can't survive the reset."""
    if len(new_password) < 8:
        raise HTTPException(400, "new password must be at least 8 characters")
    operator = _consume_token(session, token, "reset")
    if not operator:
        raise HTTPException(400, "invalid or expired token")
    operator.password_hash = hash_password(new_password)
    # a reset also confirms control of the mailbox, so treat the email as verified
    operator.email_verified = True
    session.add(operator)
    for s in session.exec(select(OperatorSession).where(OperatorSession.operator_id == operator.id)).all():
        session.delete(s)
    session.commit()
    log(logger, logging.INFO, "auth.reset_completed", operator_id=operator.id)
    return {"ok": True}


# ---- Operator auth (panel login) ----


@app.post("/operator/login")
def operator_login(email: str = Body(...), password: str = Body(...), session: Session = Depends(get_session)):
    operator = session.exec(select(Operator).where(Operator.email == email)).first()
    if not operator or not verify_password(password, operator.password_hash):
        raise HTTPException(401, "invalid credentials")
    if not operator.email_verified:
        # signup created the account but the mailbox was never confirmed; the panel maps this
        # 403 to a "verify your email / resend" prompt
        raise HTTPException(403, "email not verified")
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

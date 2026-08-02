import hashlib
import json
import hmac
import ipaddress
import logging
import os
from pathlib import Path
import re
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import stripe
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool
from sqlalchemy import and_, case, func, or_
from sqlmodel import Session, select

from . import billing

from .db import (
    AiResponseLog,
    Attachment,
    ApiKey,
    AuditLog,
    AuthToken,
    CannedResponse,
    Chunk,
    Client,
    Contact,
    Conversation,
    ConversationRating,
    ConversationTag,
    CrmConnection,
    CrmSync,
    HelpdeskConnection,
    HelpdeskExport,
    Department,
    DepartmentMember,
    InfoField,
    IngestJob,
    InternalNote,
    Lead,
    LeadForm,
    Message,
    NoteMention,
    Operator,
    OperatorSession,
    Plan,
    PluginInstallation,
    ProactiveRule,
    Product,
    PushSubscription,
    RoutingSetting,
    SavedView,
    SlaPolicy,
    SupportSchedule,
    Tag,
    Ticket,
    WebhookDelivery,
    WebhookEndpoint,
    WhatsAppConsent,
    Workflow,
    WorkflowRun,
    engine,
    get_session,
    init_db,
)
from . import email as email_service
from . import whatsapp as whatsapp_service
from . import meta_messaging as meta_messaging_service
from . import push as push_service
from . import attachments as attachment_service
from . import crm as crm_service
from . import helpdesk as helpdesk_service
from . import business_hours
from fastapi.responses import StreamingResponse

import urllib.error
import urllib.request

from .llm import INTENTS as llm_intents
from .llm import URGENCIES as llm_urgencies
from .llm import ESCALATE_PREFIX, ORDER_LOOKUP_RE, LLMUnavailableError
from .llm import chat as llm_chat
from .llm import chat_stream as llm_chat_stream
from .llm import embed
from .logging_config import log, request_id_var, setup_logging
from . import metrics
from .notify import notify_new_ticket, notify_sla_breach
from .production_config import enforce_production_config, production_warnings
from .rag import extract_text, retrieve, retrieve_products, retrieve_with_meta
from .ratelimit import make_limiter
from .security import hash_password, password_needs_rehash, verify_password
from . import analytics
from . import i18n
from . import language
from . import tagging
from . import webhooks
from . import events
from . import workflows
from .worker import requeue_stale, run_worker

setup_logging()
logger = logging.getLogger("wpai")

# Error tracking (Sentry). Opt-in: unset SENTRY_DSN => disabled (no-op). When set, sentry-sdk
# auto-instruments FastAPI/Starlette and captures unhandled exceptions with request context.
# send_default_pii=False so we don't ship visitor messages/emails to Sentry.
_sentry_dsn = os.getenv("SENTRY_DSN", "").strip()
if _sentry_dsn:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=_sentry_dsn,
            environment=os.getenv("SENTRY_ENV", "production"),
            release=os.getenv("APP_VERSION", "dev"),
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
            send_default_pii=False,
        )
        log(logger, logging.INFO, "sentry.enabled")
    except Exception as exc:  # noqa: BLE001 — monitoring must never break startup
        log(logger, logging.WARNING, "sentry.init_failed", error=str(exc))

_worker_stop = threading.Event()
_worker_thread: threading.Thread | None = None
_purge_thread: threading.Thread | None = None
_sla_thread: threading.Thread | None = None
_webhook_thread: threading.Thread | None = None

# GDPR data-minimization: auto-delete conversations older than this many days (0 = keep forever).
DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", "0"))


def _run_purge(stop: threading.Event) -> None:
    """Background loop: purge conversations past the retention window, once a day."""
    while not stop.is_set():
        try:
            with Session(engine) as session:
                n = purge_old_conversations(session, DATA_RETENTION_DAYS)
                if n:
                    log(logger, logging.INFO, "retention.purged", conversations=n, days=DATA_RETENTION_DAYS)
        except Exception as exc:  # noqa: BLE001 — never let the purge loop crash the app
            log(logger, logging.WARNING, "retention.purge_failed", error=str(exc))
        stop.wait(24 * 3600)


def _run_sla_monitor(stop: threading.Event) -> None:
    """Background loop: flag and alert the SLA deadlines that have just been missed."""
    while not stop.is_set():
        try:
            with Session(engine) as session:
                n = check_sla_breaches(session)
                if n:
                    log(logger, logging.INFO, "sla.breaches_detected", breaches=n)
        except Exception as exc:  # noqa: BLE001 — never let the monitor crash the app
            log(logger, logging.WARNING, "sla.monitor_failed", error=str(exc))
        stop.wait(SLA_CHECK_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_warnings = enforce_production_config(os.environ)
    for warning in config_warnings:
        log(logger, logging.WARNING, "production.config_warning", warning=warning)
    init_db()
    with Session(engine) as session:
        rebuild_allowed_origins(session)
        requeue_stale(session)  # recover jobs left 'processing' by a previous crash
    global _worker_thread, _purge_thread, _sla_thread, _webhook_thread
    if os.getenv("INGEST_WORKER_ENABLED", "true").lower() == "true":
        _worker_thread = threading.Thread(target=run_worker, args=(_worker_stop,), daemon=True)
        _worker_thread.start()
    if DATA_RETENTION_DAYS > 0:
        _purge_thread = threading.Thread(target=_run_purge, args=(_worker_stop,), daemon=True)
        _purge_thread.start()
    if SLA_MONITOR_ENABLED:
        _sla_thread = threading.Thread(target=_run_sla_monitor, args=(_worker_stop,), daemon=True)
        _sla_thread.start()
    if WEBHOOK_DISPATCHER_ENABLED:
        _webhook_thread = threading.Thread(target=webhooks.run_dispatcher, args=(_worker_stop,), daemon=True)
        _webhook_thread.start()
    log(logger, logging.INFO, "startup.complete")
    yield
    _worker_stop.set()
    if _worker_thread:
        _worker_thread.join(timeout=5)
    if _purge_thread:
        _purge_thread.join(timeout=5)
    if _sla_thread:
        _sla_thread.join(timeout=5)
    if _webhook_thread:
        _webhook_thread.join(timeout=5)


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
OPERATOR_SESSION_TTL = timedelta(hours=int(os.getenv("OPERATOR_SESSION_TTL_HOURS", str(24 * 30))))

# /chat hits the LLM on every call, so it's the main abuse/cost surface — limit per client+IP.
# Ingest is limited per client. Windows are 60s; override the counts via env.
chat_limiter = make_limiter(int(os.getenv("CHAT_RATE_LIMIT", "30")), 60)
ingest_limiter = make_limiter(int(os.getenv("INGEST_RATE_LIMIT", "60")), 60)
auth_limiter = make_limiter(int(os.getenv("AUTH_RATE_LIMIT", "10")), 60)


def _rate_limit_auth(request: Request, scope: str, identity: str = "") -> None:
    ip = request.client.host if request.client else "unknown"
    identity_digest = hashlib.sha256(identity.strip().lower().encode()).hexdigest()[:16]
    auth_limiter.check(f"auth:{scope}:{ip}:{identity_digest}")

# ponytail: deterministic safety net for categories that must always reach a human —
# small local LLMs don't reliably follow "always escalate refunds" instructions
ALWAYS_ESCALATE_KEYWORDS = [
    "rimborso", "refund", "reclamo", "complaint", "denuncia",
    "cambio password account", "eliminare il mio account", "delete my account",
]

MAX_CHAT_MESSAGE_CHARS = int(os.getenv("MAX_CHAT_MESSAGE_CHARS", "4000"))
MAX_INGEST_TEXT_CHARS = int(os.getenv("MAX_INGEST_TEXT_CHARS", "2000000"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
# A substantive question must have at least one reasonably close knowledge-base result.
# This is stricter than the retrieval cutoff so loose context cannot enable general chat.
SCOPE_MAX_DISTANCE = float(os.getenv("SCOPE_MAX_DISTANCE", "0.62"))


def _bounded_limit(value: int, *, default: int = 100, maximum: int = 500) -> int:
    return min(max(value or default, 1), maximum)

# ponytail: same deterministic-safety-net pattern as ALWAYS_ESCALATE_KEYWORDS — the small model
# doesn't reliably combine "order number" (turn 1) and "identifier" (turn 2) into a single
# ORDER_LOOKUP marker across turns, and answering an order question straight from the LLM risks
# hallucinated order data. Scan the *whole* conversation (not just the latest message) so the
# two slots can land in different turns, same as a human support agent would track them.
_ORDER_NUMBER_RE = re.compile(r"ordine\D{0,15}(\d{2,})|order\D{0,15}#?\s*(\d{2,})|#(\d{2,})", re.I)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_ASKED_IDENTIFIER_RE = re.compile(r"cognome|email|e-mail", re.I)
# a bare identifier turn (e.g. "Prova Prova" answering "what's your surname?") — short, no
# digits, no obvious question — not a strict name validator, just "doesn't look like something
# else". Reused for the last user message, not run against normal free-text messages.
_BARE_IDENTIFIER_RE = re.compile(r"^[^\d@?]{2,40}$")


def _detect_order_lookup(history: list[dict], message: str) -> tuple[str, str] | None:
    full_text = "\n".join(h["content"] for h in history) + "\n" + message
    order_match = _ORDER_NUMBER_RE.search(full_text)
    if not order_match:
        return None
    order_number = next(g for g in order_match.groups() if g)

    email_match = _EMAIL_RE.search(full_text)
    if email_match:
        return order_number, email_match.group(0)

    # no email anywhere yet — accept a bare surname-shaped reply, but only right after the
    # assistant itself asked for one (avoids treating an unrelated short message as an identifier)
    last_assistant = next((h["content"] for h in reversed(history) if h["role"] == "assistant"), "")
    if _ASKED_IDENTIFIER_RE.search(last_assistant) and _BARE_IDENTIFIER_RE.match(message.strip()):
        return order_number, message.strip()

    return None

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
        "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Conversation-Token, ngrok-skip-browser-warning",
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
    job = IngestJob(
        client_id=client_id,
        kind=kind,
        payload=json.dumps(payload),
        max_attempts=int(os.getenv("INGEST_MAX_ATTEMPTS", "3")),
    )
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


def require_channel_write_key(
    authorization: str = Header(None),
    session: Session = Depends(get_session),
) -> ApiKey:
    """Server-only credential for inbound channel adapters.

    This deliberately does not accept Client.api_key: that key is embedded in public widget
    pages and must never authorize injection into the operator inbox.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    digest = hashlib.sha256(authorization[7:].strip().encode()).hexdigest()
    key = session.exec(select(ApiKey).where(ApiKey.token_hash == digest)).first()
    if key is None or key.revoked_at is not None:
        raise HTTPException(401, "invalid api key")
    if "channels:write" not in [s for s in (key.scopes or "").split(",") if s]:
        raise HTTPException(403, "scope richiesto: channels:write")
    return key


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


def _hash_conversation_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _get_or_create_contact(
    session: Session,
    client_id: int,
    channel: str,
    external_id: str,
    *,
    email: str | None = None,
    name: str = "",
) -> Contact:
    """Resolve identity inside one tenant/channel and enrich it without erasing known data."""
    contact = session.exec(
        select(Contact).where(
            Contact.client_id == client_id,
            Contact.channel == channel,
            Contact.external_id == external_id,
        )
    ).first()
    if contact:
        changed = False
        if email and contact.email != email:
            contact.email = email
            changed = True
        if name and contact.name != name:
            contact.name = name[:120]
            changed = True
        if changed:
            contact.updated_at = datetime.utcnow()
            session.add(contact)
            session.commit()
        return contact
    contact = Contact(
        client_id=client_id,
        channel=channel,
        external_id=external_id,
        email=email,
        name=name[:120],
    )
    session.add(contact)
    session.commit()
    session.refresh(contact)
    return contact


def _create_conversation(session: Session, client_id: int, visitor_id: str) -> tuple[Conversation, str]:
    """Create a visitor conversation and return its one-time plaintext access token.

    Only the digest is persisted. The tenant api_key is embedded in the public widget and
    therefore cannot authorize access to an individual visitor's transcript.
    """
    token = secrets.token_urlsafe(32)
    contact = _get_or_create_contact(session, client_id, "web", visitor_id)
    conv = Conversation(
        client_id=client_id,
        visitor_id=visitor_id,
        channel="web",
        contact_id=contact.id,
        access_token_hash=_hash_conversation_token(token),
    )
    session.add(conv)
    session.commit()
    session.refresh(conv)
    # the access token never leaves this function: webhooks carry the conversation id only
    events.emit(session, client_id, "conversation.created", {
        "conversation_id": conv.id, "visitor_id": conv.visitor_id, "channel": conv.channel,
    }, conv=conv)
    return conv, token


def _require_conversation_token(conv: Conversation, token: str | None) -> None:
    """Fail as not-found so callers cannot use the endpoint to enumerate conversations."""
    if (
        not conv.access_token_hash
        or not token
        or not secrets.compare_digest(_hash_conversation_token(token), conv.access_token_hash)
    ):
        raise HTTPException(404, "conversation not found")


def _get_operator_session(session: Session, token: str) -> OperatorSession | None:
    """Resolve an active session and eagerly remove it when its absolute TTL has elapsed."""
    digest = _hash_session_token(token)
    op_session = session.exec(
        select(OperatorSession).where(
            or_(OperatorSession.token_hash == digest, OperatorSession.token == token)
        )
    ).first()
    if op_session and op_session.expires_at <= datetime.utcnow():
        session.delete(op_session)
        session.commit()
        return None
    if op_session and op_session.token:
        # Transparent rolling upgrade for a pre-0015 plaintext row.
        op_session.token_hash = digest
        op_session.token = None
        session.add(op_session)
        session.commit()
    return op_session


def require_operator(
    authorization: str = Header(None), session: Session = Depends(get_session)
) -> Operator:
    """Auth for the human panel: resolves an operator session token to its Operator."""
    op_session = _get_operator_session(session, _bearer_token(authorization))
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
    op_session = _get_operator_session(session, token)
    if op_session:
        return op_session.client_id
    client = session.exec(select(Client).where(Client.api_key == token)).first()
    if client:
        return client.id
    raise HTTPException(401, "invalid credentials")


@app.post("/ingest/document")
async def ingest_document(file: UploadFile, operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file too large (max {MAX_UPLOAD_BYTES} bytes)")
    text = extract_text(file.filename, data)
    if len(text) > MAX_INGEST_TEXT_CHARS:
        raise HTTPException(413, "extracted text too large")
    job = _enqueue(session, operator.client_id, "document", {"source_ref": file.filename, "text": text})
    return {"ok": True, "job_id": job.id, "status": job.status, "chars": len(text)}


@app.post("/knowledge/teach")
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


@app.post("/ingest/site-page")
def ingest_site_page(url: str = Body(...), text: str = Body(...), client: Client = Depends(rate_limit_ingest), session: Session = Depends(get_session)):
    """Called by the WP plugin on publish/update to push page/product content. The worker
    replaces previous chunks for this URL when it processes the job (so edits don't duplicate)."""
    if len(url) > 2000 or len(text) > MAX_INGEST_TEXT_CHARS:
        raise HTTPException(413, "site page payload too large")
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
    if len(url) > 2000 or len(title) > 500 or len(text) > MAX_INGEST_TEXT_CHARS:
        raise HTTPException(413, "product payload too large")
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
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "error": job.error,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
    }


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


def _build_system(context: list[str], language: str | None = None) -> str:
    return (
        "You are a customer support assistant. Handle greetings and small talk yourself, "
        "normally, without calling any tool. For substantive questions, answer only using "
        "the context below. Call escalate_to_human ONLY when: the answer to a substantive "
        "question isn't in the context, or the request needs human authority (refunds, "
        "complaints, account changes). Do not escalate greetings or vague messages — ask "
        "the user to clarify instead. You cannot modify the WooCommerce cart, place orders, "
        "apply coupons, or calculate a new cart total. Never claim that you performed one of "
        "these actions. When a visitor asks to add a product to the cart, tell them to use the "
        "\"Aggiungi al carrello\" button on the product card; only the site can confirm that "
        "the operation succeeded.\n\nContext:\n" + "\n---\n".join(context)
        + i18n.prompt_language_instruction(language)
    )


_CART_MUTATION_RE = re.compile(
    r"\b(?:aggiung(?:i|ilo|ila|imi|ere)|metti|inserisci|add)\b.*\b(?:carrello|cart)\b"
    r"|\b(?:aggiungilo|aggiungila|aggiungili|aggiungile|aggiungimi)\b",
    re.IGNORECASE,
)


def _is_cart_mutation_request(message: str) -> bool:
    """Cart writes are performed by WooCommerce in the widget, never by the model."""
    return bool(_CART_MUTATION_RE.search(message or ""))


def _cart_instruction_reply(products: list[dict], language: str | None = None) -> str:
    return i18n.t("cart.use_button" if products else "cart.no_product", language)


_SMALL_TALK_RE = re.compile(
    r"^\s*(?:ciao|salve|buongiorno|buonasera|hey|hello|hi|grazie|thanks|"
    r"arrivederci|a presto|come stai|chi sei|cosa (?:sai|puoi) fare)[!?.\s]*$",
    re.IGNORECASE,
)
def _out_of_scope_reply(language: str | None = None) -> str:
    return i18n.t("scope.out_of_scope", language)


def _is_small_talk(message: str) -> bool:
    return bool(_SMALL_TALK_RE.match(message or ""))


def _retrieval_is_in_scope(retrieval_meta: list[dict]) -> bool:
    """Require semantic evidence from this tenant's own knowledge base."""
    return any(
        item.get("selected") and float(item.get("distance", 1.0)) <= SCOPE_MAX_DISTANCE
        for item in retrieval_meta
    )


def _trusted_callback_origin(allowed_origins: str, site_url, request) -> str:
    """The origin to call back for an order lookup — ONLY if it's one the client configured in
    allowed_origins. `site_url` is an attacker-controllable body param, so validating the chosen
    origin against the allowlist prevents SSRF (a spoofed site_url making the backend POST to an
    arbitrary/internal URL). Returns "" when nothing trusted matches (order lookup then fails
    gracefully instead of hitting an untrusted host). Requires allowed_origins to be configured."""
    allowed = set(_split_origins(allowed_origins))
    if not allowed:
        return ""
    # Reject literal internal/link-local targets outright instead of silently falling back.
    # This keeps attacker-controlled callback candidates visible as a failed validation and
    # prevents future refactors from accidentally using the original site_url.
    if site_url:
        from urllib.parse import urlparse

        try:
            hostname = urlparse(site_url).hostname
            address = ipaddress.ip_address(hostname) if hostname else None
            if address and not address.is_global:
                return ""
        except ValueError:
            pass  # regular DNS hostname; exact allowlist matching below remains authoritative
    for cand in (site_url, request.headers.get("origin"), request.headers.get("referer")):
        norm = _normalize_origins(cand or "")
        if norm and norm in allowed:
            return norm
    return ""


def _order_lookup(origin: str, api_key: str, order_number: str, identifier: str, user_token: str | None) -> dict:
    """Calls the WP plugin's dedicated order-lookup REST route (the plugin's own api_key is
    reused as the shared secret — no new credential to provision). `origin` is the widget
    page's Origin header, i.e. the WP site's own base URL."""
    req = urllib.request.Request(
        origin.rstrip("/") + "/wp-json/wpai/v1/order-lookup",
        data=json.dumps({"order_number": order_number, "identifier": identifier, "user_token": user_token}).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read())
        except Exception:  # noqa: BLE001
            return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _format_order_reply(data: dict, language: str | None = None) -> str:
    """Deterministic templating from the plugin's structured response — never a second LLM
    round-trip, so order/financial facts can't be hallucinated. Translated the same way, for
    the same reason: re-generating these lines in another language would be a chance to get a
    financial fact wrong."""
    if not data.get("verified"):
        return i18n.t("order.not_verified", language)
    status = data.get("status") or i18n.t("order.status_unknown", language)
    shipping = data.get("shipping_date")
    lines = [i18n.t("order.status", language, value=status)]
    lines.append(
        i18n.t("order.shipping_date", language, value=shipping) if shipping
        else i18n.t("order.no_shipping_date", language)
    )
    if data.get("verified") == "full":
        if data.get("total"):
            lines.append(i18n.t("order.total", language, value=data["total"]))
        if data.get("items"):
            lines.append(i18n.t("order.items", language, value=", ".join(data["items"])))
        if data.get("shipping_address"):
            lines.append(i18n.t("order.shipping_address", language, value=data["shipping_address"]))
    return " ".join(lines)


def _escalate(session, client_id, client_name, conv, reason, *, outcome, trigger,
              retrieval_meta=None, llm_meta=None, error=None, depth=0):
    """Shared escalation: mark the conversation escalated, open a ticket, log + count the
    escalation, record the AI-response diagnostics, and notify operators. Used by both the
    sync /chat and the streaming /chat/stream so the two stay in lockstep."""
    conv.status = "escalated"
    conv.updated_at = datetime.utcnow()
    # the conversation now needs a human: start the SLA clock and apply the routing rules
    assignee = _auto_assign(session, conv)
    _apply_sla(session, conv, start=True)
    session.add(conv)
    ticket = Ticket(conversation_id=conv.id, reason=reason)
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    if assignee is not None:
        log(
            logger, logging.INFO, "routing.auto_assigned",
            client_id=client_id, conversation_id=conv.id, operator_id=assignee.id,
        )
    # classify in the background: the operator opening the inbox finds intent/topic/urgency
    # already there, and a slow or failing classifier never delays the escalation itself
    if tagging.AI_CLASSIFY_ENABLED and conv.ai_classified_at is None:
        try:
            _enqueue(session, client_id, "classify", {"conversation_id": conv.id})
        except Exception as exc:  # noqa: BLE001 — queuing a classification is never critical
            log(logger, logging.WARNING, "classify.enqueue_failed", conversation_id=conv.id, error=str(exc))
    if error is not None:
        log(logger, logging.ERROR, "chat.llm_unavailable", client_id=client_id, conversation_id=conv.id, error=error)
    else:
        log(logger, logging.INFO, "chat.escalated", client_id=client_id, conversation_id=conv.id, trigger=trigger, reason=reason)
    metrics.escalations_total.labels(trigger=trigger).inc()
    _log_ai_response(session, client_id, conv.id, outcome, retrieval_meta=retrieval_meta, llm_meta=llm_meta)
    notify_new_ticket(client_name, conv.id, ticket.id, reason)
    push_service.send(
        session, client_id, "assignment" if assignee else "escalation",
        title="Nuova conversazione assegnata" if assignee else "Nuova escalation",
        body=reason[:180], conversation_id=conv.id,
        operator_ids=[assignee.id] if assignee else None,
    )
    events.emit(session, client_id, "conversation.escalated", {
        "conversation_id": conv.id, "ticket_id": ticket.id, "reason": reason, "trigger": trigger,
    }, conv=conv, depth=depth)
    return ticket


def _sse(payload: dict) -> str:
    """Serialize one Server-Sent Event frame."""
    return f"data: {json.dumps(payload)}\n\n"


def _month_start() -> datetime:
    now = datetime.utcnow()
    return datetime(now.year, now.month, 1)


def _monthly_message_count(session: Session, client_id: int) -> int:
    """Visitor chat messages this calendar month for the client — the monthly-quota unit."""
    return session.exec(
        select(func.count()).select_from(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Conversation.client_id == client_id, Message.role == "user", Message.created_at >= _month_start())
    ).one()


def _usage(session: Session, client_id: int) -> dict:
    client = session.get(Client, client_id)
    plan = session.get(Plan, client.plan_id) if client and client.plan_id else None
    limit = plan.monthly_message_limit if plan else 0
    used = _monthly_message_count(session, client_id)
    return {
        "plan": plan.name if plan else None,
        "period": _month_start().strftime("%Y-%m"),
        "limit": limit,  # 0 = unlimited
        "used": used,
        "remaining": max(limit - used, 0) if limit else None,
    }


def _over_quota(session: Session, client_id: int) -> bool:
    client = session.get(Client, client_id)
    plan = session.get(Plan, client.plan_id) if client and client.plan_id else None
    limit = plan.monthly_message_limit if plan else 0
    return bool(limit) and _monthly_message_count(session, client_id) > limit


def _prepare_chat_turn(
    session: Session,
    *,
    client_id: int,
    visitor_id: str,
    message: str,
    conversation_id: int | None,
    conversation_token: str | None,
    locale: str | None = None,
) -> tuple[Conversation, str, list[dict]]:
    """Shared state transition for both blocking and SSE chat transports."""
    if not message.strip():
        raise HTTPException(400, "message required")
    if len(message) > MAX_CHAT_MESSAGE_CHARS or len(visitor_id) > 128:
        raise HTTPException(413, "chat payload too large")
    if conversation_id:
        conv = session.get(Conversation, conversation_id)
        if not conv or conv.client_id != client_id:
            raise HTTPException(404, "conversation not found")
        _require_conversation_token(conv, conversation_token)
        access_token = conversation_token
    else:
        conv, access_token = _create_conversation(session, client_id, visitor_id)

    history = [
        {"role": m.role if m.role != "operator" else "assistant", "content": m.content}
        for m in session.exec(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.id)
        ).all()
    ]
    session.add(Message(conversation_id=conv.id, role="user", content=message))
    # Re-detected every turn: a visitor can switch language mid-conversation, and the browser
    # locale is only a hint — what they actually type wins when it says something.
    conv.language = language.detect(message, hint=locale, default=conv.language or language.DEFAULT)
    conv.updated_at = datetime.utcnow()
    if conv.status == "closed":
        conv.status = "open"
        conv.closed_at = None
    session.add(conv)
    session.commit()
    metrics.chat_messages_total.inc()
    return conv, access_token, history


def _deterministic_chat_action(
    session: Session,
    *,
    client_id: int,
    client_name: str,
    conv: Conversation,
    message: str,
    support_available: bool = True,
) -> str | None:
    """Handle transport-independent early exits before retrieval/LLM work."""
    if conv.status == "escalated":
        return "escalated"
    lowered = message.lower()
    keyword_hit = next((k for k in ALWAYS_ESCALATE_KEYWORDS if k in lowered), None)
    if keyword_hit:
        if not support_available:
            return "ticket_offered"
        _escalate(
            session,
            client_id,
            client_name,
            conv,
            f"richiede intervento umano ({keyword_hit})",
            outcome="escalated_keyword",
            trigger="keyword",
        )
        return "escalated"
    if _over_quota(session, client_id):
        return "quota_exceeded"
    return None


def _save_order_lookup_reply(
    session: Session,
    *,
    client_id: int,
    conv: Conversation,
    data: dict,
    retrieval_meta: list[dict] | None = None,
    llm_meta: dict | None = None,
) -> tuple[str, Message]:
    reply_text = _format_order_reply(data, conv.language)
    reply_msg = Message(conversation_id=conv.id, role="assistant", content=reply_text)
    session.add(reply_msg)
    conv.updated_at = datetime.utcnow()
    session.add(conv)
    session.commit()
    session.refresh(reply_msg)
    _log_ai_response(
        session,
        client_id,
        conv.id,
        "order_lookup",
        retrieval_meta=retrieval_meta,
        llm_meta=llm_meta,
        message_id=reply_msg.id,
    )
    return reply_text, reply_msg


@app.post("/chat/stream")
def chat_stream_endpoint(
    request: Request,
    visitor_id: str = Body(...),
    message: str = Body(...),
    conversation_id: int | None = Body(None),
    conversation_token: str | None = Body(None),
    wp_user_token: str | None = Body(None),
    site_url: str | None = Body(None),
    support_available: bool = Body(True),
    locale: str | None = Body(None),  # browser language, used only as a hint
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
        _require_conversation_token(conv, conversation_token)

    def event_stream():
        # a fresh session: the request-scoped one closes when this function returns, before the
        # generator is consumed while streaming
        with Session(engine) as s:
            conv, access_token, history = _prepare_chat_turn(
                s,
                client_id=client_id,
                visitor_id=visitor_id,
                message=message,
                conversation_id=conversation_id,
                conversation_token=conversation_token,
                locale=locale,
            )

            yield _sse({
                "type": "start",
                "conversation_id": conv.id,
                "conversation_token": access_token,
            })

            early_action = _deterministic_chat_action(
                s,
                client_id=client_id,
                client_name=client_name,
                conv=conv,
                message=message,
                support_available=support_available,
            )
            if early_action == "escalated":
                yield _sse({"type": "escalated", "conversation_id": conv.id})
                return
            if early_action == "quota_exceeded":
                yield _sse({"type": "quota_exceeded", "conversation_id": conv.id})
                return
            if early_action == "ticket_offered":
                yield _sse({
                    "type": "ticket_offered",
                    "conversation_id": conv.id,
                    "reason": "richiede intervento umano",
                })
                return

            detected = _detect_order_lookup(history, message)
            if detected:
                origin = _trusted_callback_origin(client.allowed_origins, site_url, request)
                data = _order_lookup(origin, client.api_key, detected[0], detected[1], wp_user_token)
                reply_text, reply_msg = _save_order_lookup_reply(
                    s, client_id=client_id, conv=conv, data=data
                )
                yield _sse({"type": "token", "text": reply_text})
                yield _sse({"type": "done", "conversation_id": conv.id, "message_id": reply_msg.id, "products": []})
                return

            if _is_cart_mutation_request(message):
                try:
                    products = retrieve_products(s, client_id, message)
                except LLMUnavailableError:
                    products = []
                reply_text = _cart_instruction_reply(products, conv.language)
                reply_msg = Message(conversation_id=conv.id, role="assistant", content=reply_text)
                s.add(reply_msg)
                conv.updated_at = datetime.utcnow()
                s.add(conv)
                s.commit()
                s.refresh(reply_msg)
                _log_ai_response(s, client_id, conv.id, "cart_action_required", message_id=reply_msg.id)
                yield _sse({"type": "token", "text": reply_text})
                yield _sse({
                    "type": "done",
                    "conversation_id": conv.id,
                    "message_id": reply_msg.id,
                    "products": products,
                })
                return

            retrieval_meta: list[dict] = []
            buffer = ""
            decided = False
            is_escalation = False
            is_order_lookup = False
            full = ""
            meta: dict = {}
            # markers are always a single short line — wait for the newline (or stream end)
            # instead of a fixed length, since the model doesn't reproduce prefixes verbatim
            # (e.g. "ORDERS_LOOKUP:" instead of "ORDER_LOOKUP:") so a fixed cutoff could split
            # mid-prefix.
            try:
                context, retrieval_meta = retrieve_with_meta(s, client_id, message)
                if not _is_small_talk(message) and not _retrieval_is_in_scope(retrieval_meta):
                    full = _out_of_scope_reply(conv.language)
                    reply_msg = Message(conversation_id=conv.id, role="assistant", content=full)
                    s.add(reply_msg)
                    conv.updated_at = datetime.utcnow()
                    s.add(conv)
                    s.commit()
                    s.refresh(reply_msg)
                    _log_ai_response(
                        s,
                        client_id,
                        conv.id,
                        "out_of_scope",
                        retrieval_meta=retrieval_meta,
                        message_id=reply_msg.id,
                    )
                    yield _sse({"type": "token", "text": full})
                    yield _sse({
                        "type": "done",
                        "conversation_id": conv.id,
                        "message_id": reply_msg.id,
                        "products": [],
                    })
                    return
                system = _build_system(context, conv.language)
                for kind, payload in llm_chat_stream(system, history, message):
                    if kind == "meta":
                        meta = payload
                        continue
                    full += payload
                    if not decided:
                        buffer += payload
                        if "\n" in buffer:
                            decided = True
                            is_escalation = buffer.startswith(ESCALATE_PREFIX)
                            is_order_lookup = bool(ORDER_LOOKUP_RE.match(buffer))
                            if not is_escalation and not is_order_lookup and buffer:
                                yield _sse({"type": "token", "text": buffer})
                    elif not is_escalation and not is_order_lookup:
                        yield _sse({"type": "token", "text": payload})
            except LLMUnavailableError as exc:
                reason = "assistente AI non disponibile al momento"
                if not support_available:
                    yield _sse({"type": "ticket_offered", "conversation_id": conv.id, "reason": reason})
                    return
                _escalate(s, client_id, client_name, conv, reason, outcome="escalated_llm_down",
                          trigger="llm_down", retrieval_meta=retrieval_meta, error=str(exc))
                yield _sse({"type": "escalated", "conversation_id": conv.id})
                return

            # very short output that never reached a newline
            if not decided:
                is_escalation = full.startswith(ESCALATE_PREFIX)
                is_order_lookup = bool(ORDER_LOOKUP_RE.match(full))
                if not is_escalation and not is_order_lookup and full:
                    yield _sse({"type": "token", "text": full})

            if is_escalation:
                reason = full[len(ESCALATE_PREFIX):].strip() or "unspecified"
                if not support_available:
                    yield _sse({"type": "ticket_offered", "conversation_id": conv.id, "reason": reason})
                    return
                _escalate(s, client_id, client_name, conv, reason, outcome="escalated_model",
                          trigger="model", retrieval_meta=retrieval_meta, llm_meta=meta)
                yield _sse({"type": "escalated", "conversation_id": conv.id})
                return

            if is_order_lookup:
                lookup_match = ORDER_LOOKUP_RE.match(full)
                order_number, identifier = lookup_match.group(1), lookup_match.group(2)
                origin = _trusted_callback_origin(client.allowed_origins, site_url, request)
                data = _order_lookup(origin, client.api_key, order_number.strip(), identifier.strip(), wp_user_token)
                reply_text, reply_msg = _save_order_lookup_reply(
                    s,
                    client_id=client_id,
                    conv=conv,
                    data=data,
                    retrieval_meta=retrieval_meta,
                    llm_meta=meta,
                )
                yield _sse({"type": "token", "text": reply_text})
                yield _sse({"type": "done", "conversation_id": conv.id, "message_id": reply_msg.id, "products": []})
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
    request: Request,
    visitor_id: str = Body(...),
    message: str = Body(...),
    conversation_id: int | None = Body(None),
    conversation_token: str | None = Body(None),
    wp_user_token: str | None = Body(None),
    site_url: str | None = Body(None),
    support_available: bool = Body(True),
    locale: str | None = Body(None),  # browser language, used only as a hint
    client: Client = Depends(rate_limit_chat),
    session: Session = Depends(get_session),
):
    conv, access_token, history = _prepare_chat_turn(
        session,
        client_id=client.id,
        visitor_id=visitor_id,
        message=message,
        conversation_id=conversation_id,
        conversation_token=conversation_token,
        locale=locale,
    )
    early_action = _deterministic_chat_action(
        session,
        client_id=client.id,
        client_name=client.name,
        conv=conv,
        message=message,
        support_available=support_available,
    )
    if early_action == "escalated":
        return {"conversation_id": conv.id, "conversation_token": access_token, "status": "escalated", "reply": None}
    if early_action == "quota_exceeded":
        return {"conversation_id": conv.id, "conversation_token": access_token, "status": "quota_exceeded", "reply": None}
    if early_action == "ticket_offered":
        return {
            "conversation_id": conv.id,
            "conversation_token": access_token,
            "status": "ticket_offered",
            "reply": None,
            "reason": "richiede intervento umano",
        }

    detected = _detect_order_lookup(history, message)
    if detected:
        origin = _trusted_callback_origin(client.allowed_origins, site_url, request)
        data = _order_lookup(origin, client.api_key, detected[0], detected[1], wp_user_token)
        reply_text, reply_msg = _save_order_lookup_reply(
            session, client_id=client.id, conv=conv, data=data
        )
        return {"conversation_id": conv.id, "conversation_token": access_token, "status": "open", "reply": reply_text, "products": [], "message_id": reply_msg.id}

    if _is_cart_mutation_request(message):
        try:
            products = retrieve_products(session, client.id, message)
        except LLMUnavailableError:
            products = []
        reply_text = _cart_instruction_reply(products, conv.language)
        reply_msg = Message(conversation_id=conv.id, role="assistant", content=reply_text)
        session.add(reply_msg)
        conv.updated_at = datetime.utcnow()
        session.add(conv)
        session.commit()
        session.refresh(reply_msg)
        _log_ai_response(session, client.id, conv.id, "cart_action_required", message_id=reply_msg.id)
        return {
            "conversation_id": conv.id,
            "conversation_token": access_token,
            "status": "open",
            "reply": reply_text,
            "products": products,
            "message_id": reply_msg.id,
        }

    retrieval_meta: list[dict] = []
    try:
        context, retrieval_meta = retrieve_with_meta(session, client.id, message)
        if not _is_small_talk(message) and not _retrieval_is_in_scope(retrieval_meta):
            reply_msg = Message(
                conversation_id=conv.id,
                role="assistant",
                content=_out_of_scope_reply(conv.language),
            )
            session.add(reply_msg)
            conv.updated_at = datetime.utcnow()
            session.add(conv)
            session.commit()
            session.refresh(reply_msg)
            _log_ai_response(
                session,
                client.id,
                conv.id,
                "out_of_scope",
                retrieval_meta=retrieval_meta,
                message_id=reply_msg.id,
            )
            return {
                "conversation_id": conv.id,
                "conversation_token": access_token,
                "status": "open",
                "reply": _out_of_scope_reply(conv.language),
                "products": [],
                "message_id": reply_msg.id,
            }
        system = _build_system(context, conv.language)
        result = llm_chat(system, history, message)
    except LLMUnavailableError as exc:
        # model provider unreachable after retries — hand off instead of failing the request
        reason = "assistente AI non disponibile al momento"
        if not support_available:
            return {
                "conversation_id": conv.id,
                "conversation_token": access_token,
                "status": "ticket_offered",
                "reply": None,
                "reason": reason,
            }
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
        return {"conversation_id": conv.id, "conversation_token": access_token, "status": "escalated", "reply": None}

    if "escalate" in result:
        if not support_available:
            return {
                "conversation_id": conv.id,
                "conversation_token": access_token,
                "status": "ticket_offered",
                "reply": None,
                "reason": result["escalate"],
            }
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
        return {"conversation_id": conv.id, "conversation_token": access_token, "status": "escalated", "reply": None}

    if "order_lookup" in result:
        order_number, _, identifier = result["order_lookup"].partition("|")
        origin = _trusted_callback_origin(client.allowed_origins, site_url, request)
        data = _order_lookup(origin, client.api_key, order_number.strip(), identifier.strip(), wp_user_token)
        reply_text, reply_msg = _save_order_lookup_reply(
            session,
            client_id=client.id,
            conv=conv,
            data=data,
            retrieval_meta=retrieval_meta,
            llm_meta=result,
        )
        return {"conversation_id": conv.id, "conversation_token": access_token, "status": "open", "reply": reply_text, "products": [], "message_id": reply_msg.id}

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
    return {"conversation_id": conv.id, "conversation_token": access_token, "status": "open", "reply": result["reply"], "products": products, "message_id": reply_msg.id}


@app.post("/chat/feedback")
def chat_feedback(
    conversation_id: int = Body(...),
    message_id: int = Body(...),
    value: str = Body(...),  # "up" | "down"
    conversation_token: str | None = Body(None),
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
    _require_conversation_token(conv, conversation_token)
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
    conversation_token: str | None = Body(None),
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
    _require_conversation_token(conv, conversation_token)
    normalized_email = email.strip().lower()[:255]
    conv.visitor_email = normalized_email
    if conv.contact_id:
        contact = session.get(Contact, conv.contact_id)
        if contact and contact.client_id == client.id:
            contact.email = normalized_email
            contact.updated_at = datetime.utcnow()
            session.add(contact)
    if url:
        conv.visitor_url = url[:1000]
    session.add(conv)
    session.commit()
    return {"ok": True}


@app.post("/chat/ticket")
def chat_ticket(
    conversation_id: int = Body(...),
    conversation_token: str | None = Body(None),
    reason: str = Body("richiesta del visitatore fuori orario"),
    client: Client = Depends(require_client),
    session: Session = Depends(get_session),
):
    """Open an asynchronous support ticket after an out-of-hours handoff was offered."""
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != client.id:
        raise HTTPException(404, "conversation not found")
    _require_conversation_token(conv, conversation_token)
    if conv.status == "escalated":
        return {"ok": True, "conversation_id": conv.id}
    _escalate(
        session,
        client.id,
        client.name,
        conv,
        reason.strip()[:500] or "richiesta del visitatore fuori orario",
        outcome="escalated_model",
        trigger="ticket",
    )
    return {"ok": True, "conversation_id": conv.id}


MAX_RATING_COMMENT_CHARS = int(os.getenv("MAX_RATING_COMMENT_CHARS", "1000"))


@app.post("/chat/rating")
def chat_rating(
    conversation_id: int = Body(...),
    score: int = Body(...),
    comment: str = Body(""),
    conversation_token: str | None = Body(None),
    client: Client = Depends(require_client),
    session: Session = Depends(get_session),
):
    """CSAT left by the visitor at the end of the chat: one rating per conversation, distinct
    from the 👍/👎 on a single AI answer. Sending it again updates the previous one — a visitor
    changing their mind must not create a second data point."""
    if score not in (1, 2, 3, 4, 5):
        raise HTTPException(400, "score must be between 1 and 5")
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != client.id:
        raise HTTPException(404, "conversation not found")
    _require_conversation_token(conv, conversation_token)
    handled_by_operator = session.exec(
        select(Message).where(Message.conversation_id == conv.id, Message.role == "operator")
    ).first() is not None
    rating = session.exec(
        select(ConversationRating).where(ConversationRating.conversation_id == conv.id)
    ).first()
    now = datetime.utcnow()
    if rating is None:
        rating = ConversationRating(
            client_id=client.id,
            conversation_id=conv.id,
            score=score,
            comment=(comment or "").strip()[:MAX_RATING_COMMENT_CHARS],
            resolved_by="operator" if handled_by_operator else "ai",
            operator_id=conv.assigned_operator_id,
            department_id=conv.department_id,
        )
    else:
        rating.score = score
        rating.comment = (comment or "").strip()[:MAX_RATING_COMMENT_CHARS]
        rating.resolved_by = "operator" if handled_by_operator else "ai"
        rating.updated_at = now
    session.add(rating)
    session.commit()
    log(logger, logging.INFO, "csat.recorded", client_id=client.id, conversation_id=conv.id, score=score)
    events.emit(session, client.id, "conversation.rated", {
        "conversation_id": conv.id, "score": rating.score, "comment": rating.comment,
        "resolved_by": rating.resolved_by,
    }, conv=conv)
    return {"ok": True}


def _rating_payload(rating: ConversationRating | None) -> dict | None:
    if rating is None:
        return None
    return {
        "score": rating.score,
        "comment": rating.comment,
        "resolved_by": rating.resolved_by,
        "created_at": _iso(rating.created_at),
    }


# transient "operator is typing" state: {conversation_id: (operator_name, monotonic_ts)}.
# In-memory (ephemeral, fine to lose on restart). ponytail: per-process — with multiple workers a
# typing ping and the widget's poll can land on different workers; back with Redis if we scale out.
_operator_typing: dict[int, tuple[str, float]] = {}
TYPING_TTL = float(os.getenv("TYPING_TTL_SECONDS", "8"))


def _operator_name(operator: Operator) -> str:
    return operator.name or operator.email


# ---- SLA & routing ----------------------------------------------------------------------
#
# The SLA clock starts when a conversation actually needs a human (escalation): the AI answers
# in seconds, so a "first response" target on every conversation would measure nothing. From
# that moment two targets run — first operator reply and resolution (close) — each with a
# deadline and a warning threshold, so the inbox can show ok / in scadenza / violato.

PRIORITIES = ("low", "normal", "high", "urgent")
SLA_STATES = ("ok", "in_scadenza", "violato")
ROUTING_MODES = ("off", "round_robin")
# share of the window after which a still-pending target is flagged "in scadenza"
SLA_WARN_RATIO = min(max(float(os.getenv("SLA_WARN_RATIO", "0.8")), 0.0), 1.0)
SLA_CHECK_INTERVAL_SECONDS = int(os.getenv("SLA_CHECK_INTERVAL_SECONDS", "300"))
SLA_MONITOR_ENABLED = os.getenv("SLA_MONITOR_ENABLED", "true").lower() == "true"
WEBHOOK_DISPATCHER_ENABLED = os.getenv("WEBHOOK_DISPATCHER_ENABLED", "true").lower() == "true"


def _match_sla_policy(session: Session, client_id: int, department_id: int | None, priority: str) -> SlaPolicy | None:
    """The most specific active policy wins: department+priority > department > priority >
    generic. Same specificity ties break on the oldest policy, so the choice is stable."""
    policies = session.exec(
        select(SlaPolicy)
        .where(SlaPolicy.client_id == client_id, SlaPolicy.active.is_(True))
        .order_by(SlaPolicy.id)
    ).all()
    best, best_score = None, -1
    for policy in policies:
        if policy.department_id is not None and policy.department_id != department_id:
            continue
        if policy.priority and policy.priority != priority:
            continue
        score = (2 if policy.department_id is not None else 0) + (1 if policy.priority else 0)
        if score > best_score:
            best, best_score = policy, score
    return best


def _apply_sla(session: Session, conv: Conversation, *, start: bool = False) -> None:
    """(Re)compute the SLA stamps of a conversation. `start=True` starts the clock if it isn't
    running yet. Recomputing after a priority/department change re-matches the policy and moves
    the deadlines, always measured from the original start. Nothing is committed here."""
    if start and conv.sla_started_at is None:
        conv.sla_started_at = datetime.utcnow()
    if conv.sla_started_at is None:
        return
    policy = _match_sla_policy(session, conv.client_id, conv.department_id, conv.priority)
    started = conv.sla_started_at
    conv.sla_policy_id = policy.id if policy else None
    conv.first_response_due_at = conv.first_response_warn_at = None
    conv.resolution_due_at = conv.resolution_warn_at = None
    schedule = session.exec(select(SupportSchedule).where(
        SupportSchedule.client_id == conv.client_id,
        SupportSchedule.enabled == True,  # noqa: E712
    )).first()

    def deadline(minutes: float) -> datetime:
        if schedule is None:
            return started + timedelta(minutes=minutes)
        return business_hours.add_business_minutes(
            started, minutes,
            weekdays=schedule.weekdays,
            start_time=schedule.start_time,
            end_time=schedule.end_time,
            timezone_name=schedule.timezone,
            closed_dates=json.loads(schedule.closed_dates or "[]"),
            include_italian_holidays=schedule.include_italian_holidays,
        )

    if policy and policy.first_response_minutes > 0:
        conv.first_response_due_at = deadline(policy.first_response_minutes)
        conv.first_response_warn_at = deadline(policy.first_response_minutes * SLA_WARN_RATIO)
    if policy and policy.resolution_minutes > 0:
        conv.resolution_due_at = deadline(policy.resolution_minutes)
        conv.resolution_warn_at = deadline(policy.resolution_minutes * SLA_WARN_RATIO)
    # a deadline moved back into the future is a new target: allow it to alert again
    now = datetime.utcnow()
    if conv.first_response_due_at is None or conv.first_response_due_at > now:
        conv.first_response_breach_notified = False
    if conv.resolution_due_at is None or conv.resolution_due_at > now:
        conv.resolution_breach_notified = False


def _target_state(due_at, warn_at, met_at, now) -> str | None:
    """ok | in_scadenza | violato for one SLA target, or None when the target isn't set."""
    if due_at is None:
        return None
    if met_at is not None:
        return "violato" if met_at > due_at else "ok"
    if now > due_at:
        return "violato"
    if warn_at is not None and now >= warn_at:
        return "in_scadenza"
    return "ok"


def _worst_sla_state(*states: str | None) -> str | None:
    for level in SLA_STATES[::-1]:  # violato, in_scadenza, ok
        if level in states:
            return level
    return None


def _sla_view(conv: Conversation, now: datetime | None = None) -> dict | None:
    """Serializable SLA summary for the inbox: per-target deadline, when it was met and the
    state, plus the worst of the two. None when no SLA is running on this conversation."""
    if conv.sla_started_at is None:
        return None
    if conv.first_response_due_at is None and conv.resolution_due_at is None:
        return None
    now = now or datetime.utcnow()
    first = _target_state(conv.first_response_due_at, conv.first_response_warn_at, conv.first_response_at, now)
    resolution = _target_state(conv.resolution_due_at, conv.resolution_warn_at, conv.closed_at, now)
    return {
        "started_at": _iso(conv.sla_started_at),
        "policy_id": conv.sla_policy_id,
        "state": _worst_sla_state(first, resolution),
        "first_response": {
            "due_at": _iso(conv.first_response_due_at),
            "met_at": _iso(conv.first_response_at),
            "state": first,
        },
        "resolution": {
            "due_at": _iso(conv.resolution_due_at),
            "met_at": _iso(conv.closed_at),
            "state": resolution,
        },
    }


def _sla_breached_clause(now: datetime):
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


def _sla_warning_clause(now: datetime):
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


def _filter_by_sla_state(query, state: str, now: datetime):
    running = Conversation.sla_started_at.is_not(None)
    breached = _sla_breached_clause(now)
    warning = _sla_warning_clause(now)
    if state == "violato":
        return query.where(running, breached)
    if state == "in_scadenza":
        return query.where(running, ~breached, warning)
    return query.where(running, ~breached, ~warning)  # ok


# ---- Tags & AI classification -----------------------------------------------------------


@app.get("/tags")
def list_tags(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(Tag).where(Tag.client_id == operator.client_id).order_by(Tag.name)
    ).all()
    return [{"id": t.id, "name": t.name, "color": t.color, "source": t.source} for t in rows]


@app.post("/tags")
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


@app.delete("/tags/{tag_id}")
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


@app.post("/conversations/{conversation_id}/tags")
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


@app.delete("/conversations/{conversation_id}/tags/{tag_id}")
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


@app.post("/conversations/{conversation_id}/classify")
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


# ---- Collaboration: internal notes, mentions, presence ----------------------------------

MAX_NOTE_CHARS = int(os.getenv("MAX_NOTE_CHARS", "4000"))
# how long an operator counts as "on this conversation" after their last heartbeat
PRESENCE_TTL = float(os.getenv("PRESENCE_TTL_SECONDS", "20"))
# {conversation_id: {operator_id: (name, last_seen_monotonic, composing)}}
# In-memory like the typing indicator: presence is a live hint, not data worth persisting.
# With several uvicorn workers each process sees its own heartbeats, so collision detection is
# best-effort — it warns, it never blocks a reply.
_conversation_presence: dict[int, dict[int, tuple[str, float, bool]]] = {}


def _require_conversation(session: Session, client_id: int, conversation_id: int) -> Conversation:
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != client_id:
        raise HTTPException(404, "conversation not found")
    return conv


# conversations tracked at once before a full sweep runs; presence entries are tiny, this only
# stops the dict from growing forever in a long-running process
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


@app.get("/conversations/{conversation_id}/notes")
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


@app.post("/conversations/{conversation_id}/notes")
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


@app.delete("/conversations/{conversation_id}/notes/{note_id}")
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


@app.get("/mentions")
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


@app.post("/mentions/read")
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


@app.post("/conversations/{conversation_id}/presence")
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


@app.get("/conversations/{conversation_id}/activity")
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


# ---- Inbox ordering & saved views ----

SORT_MODES = ("recent", "oldest", "priority", "sla")
# how urgent each priority is when sorting (higher = shown first)
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


@app.get("/saved-views")
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


@app.post("/saved-views")
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


@app.patch("/saved-views/{view_id}")
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


@app.delete("/saved-views/{view_id}")
def delete_saved_view(
    view_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    view = _own_saved_view(session, operator, view_id)
    session.delete(view)
    session.commit()
    return {"ok": True}


def _routing_setting(session: Session, client_id: int) -> RoutingSetting | None:
    return session.exec(select(RoutingSetting).where(RoutingSetting.client_id == client_id)).first()


def _assignable_operators(session: Session, client_id: int, department_id: int | None) -> list[Operator]:
    """The round-robin pool: the members of the conversation's department, or every verified
    operator of the tenant when the conversation has no department. A department with no
    members has no pool — the conversation stays in that queue, unassigned, on purpose."""
    if department_id is not None:
        member_ids = [
            m.operator_id
            for m in session.exec(
                select(DepartmentMember).where(
                    DepartmentMember.client_id == client_id,
                    DepartmentMember.department_id == department_id,
                )
            ).all()
        ]
        if not member_ids:
            return []
        return session.exec(
            select(Operator)
            .where(
                Operator.client_id == client_id,
                Operator.email_verified.is_(True),
                Operator.id.in_(member_ids),
            )
            .order_by(Operator.id)
        ).all()
    return session.exec(
        select(Operator)
        .where(Operator.client_id == client_id, Operator.email_verified.is_(True))
        .order_by(Operator.id)
    ).all()


def _auto_assign(session: Session, conv: Conversation) -> Operator | None:
    """Round-robin the conversation to the next operator of its queue when the tenant enabled
    it. Falls back to the configured department, then to the unassigned queue: never fails the
    escalation it is attached to. Nothing is committed here."""
    setting = _routing_setting(session, conv.client_id)
    if setting is None or setting.mode != "round_robin":
        return None
    if conv.department_id is None and setting.fallback_department_id:
        department = session.get(Department, setting.fallback_department_id)
        if department and department.client_id == conv.client_id:
            conv.department_id = department.id
    if conv.assigned_operator_id is not None:
        return None
    pool = _assignable_operators(session, conv.client_id, conv.department_id)
    if not pool:
        return None
    cursor = setting.last_operator_id
    chosen = next((op for op in pool if cursor is None or op.id > cursor), pool[0])
    conv.assigned_operator_id = chosen.id
    setting.last_operator_id = chosen.id
    setting.updated_at = datetime.utcnow()
    session.add(setting)
    return chosen


def check_sla_breaches(session: Session) -> int:
    """Stamp and alert every conversation that crossed an SLA deadline. Idempotent: the
    *_breach_notified flags make each target alert exactly once. Returns the number of new
    breaches. Called by the background monitor and directly by the tests."""
    now = datetime.utcnow()
    pending_first = and_(
        Conversation.first_response_breach_notified.is_(False),
        Conversation.first_response_at.is_(None),
        Conversation.first_response_due_at.is_not(None),
        Conversation.first_response_due_at < now,
    )
    pending_resolution = and_(
        Conversation.resolution_breach_notified.is_(False),
        Conversation.closed_at.is_(None),
        Conversation.resolution_due_at.is_not(None),
        Conversation.resolution_due_at < now,
    )
    convs = session.exec(
        select(Conversation).where(
            Conversation.sla_started_at.is_not(None),
            or_(pending_first, pending_resolution),
        )
    ).all()
    breaches = 0
    for conv in convs:
        client = session.get(Client, conv.client_id)
        client_name = client.name if client else "—"
        targets = []
        if not conv.first_response_breach_notified and conv.first_response_at is None \
                and conv.first_response_due_at is not None and conv.first_response_due_at < now:
            conv.first_response_breach_notified = True
            targets.append(("first_response", conv.first_response_due_at))
        if not conv.resolution_breach_notified and conv.closed_at is None \
                and conv.resolution_due_at is not None and conv.resolution_due_at < now:
            conv.resolution_breach_notified = True
            targets.append(("resolution", conv.resolution_due_at))
        if not targets:
            continue
        session.add(conv)
        for target, due_at in targets:
            breaches += 1
            metrics.sla_breaches_total.labels(target=target).inc()
            log(
                logger, logging.WARNING, "sla.breached",
                client_id=conv.client_id, conversation_id=conv.id, target=target, due_at=_iso(due_at),
            )
            _audit(
                session, "system", "sla-monitor", "sla.breach",
                target=f"conversation:{conv.id}", client_id=conv.client_id,
                detail={"target": target, "due_at": _iso(due_at)},
            )
            notify_sla_breach(client_name, conv.id, target, _iso(due_at) or "")
            push_service.send(
                session, conv.client_id, "sla_breach",
                title="SLA violato", body=f"Conversazione #{conv.id}: {target}",
                conversation_id=conv.id,
                operator_ids=[conv.assigned_operator_id] if conv.assigned_operator_id else None,
            )
            events.emit(session, conv.client_id, "sla.breached", {
                "conversation_id": conv.id, "target": target, "due_at": _iso(due_at),
            }, conv=conv)
    session.commit()
    return breaches


@app.post("/conversations/{conversation_id}/typing")
def operator_typing(conversation_id: int, operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """Panel pings this while the operator is typing; the widget's poll shows '<name> sta scrivendo'."""
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id:
        raise HTTPException(404, "conversation not found")
    _operator_typing[conversation_id] = (_operator_name(operator), time.monotonic())
    return {"ok": True}


@app.get("/usage")
def usage(client_id: int = Depends(resolve_client_id), session: Session = Depends(get_session)):
    """Current month's chat-message usage vs the plan quota. Dual auth: the WP plugin (client
    api_key) and the panel (operator token) both read it. remaining=null means unlimited."""
    return _usage(session, client_id)


@app.get("/conversations/{conversation_id}/messages")
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


@app.post("/channels/email/inbound")
def email_inbound(
    from_email: str = Body(...),
    subject: str = Body(...),
    text: str = Body(...),
    message_id: str = Body(...),
    thread_id: str = Body(""),
    in_reply_to: str = Body(""),
    from_name: str = Body(""),
    key: ApiKey = Depends(require_channel_write_key),
    session: Session = Depends(get_session),
):
    """Provider-neutral inbound email adapter.

    An email provider (or a tiny provider-specific adapter) posts normalized fields here using
    a server-side key scoped to channels:write. Provider message ids make retries idempotent;
    thread ids keep replies in the same inbox conversation.
    """
    address = (from_email or "").strip().lower()[:320]
    body = (text or "").strip()[:MAX_CHAT_MESSAGE_CHARS]
    provider_message_id = (message_id or "").strip()[:500]
    root_thread_id = (thread_id or in_reply_to or provider_message_id).strip()[:500]
    clean_subject = (subject or "").strip()[:500]
    if not address or not _EMAIL_RE.fullmatch(address):
        raise HTTPException(400, "valid from_email required")
    if not body:
        raise HTTPException(400, "text required")
    if not provider_message_id:
        raise HTTPException(400, "message_id required")
    duplicate = session.exec(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.client_id == key.client_id,
            Conversation.channel == "email",
            Message.external_id == provider_message_id,
        )
    ).first()
    if duplicate:
        return {"ok": True, "created": False, "conversation_id": duplicate.conversation_id}

    thread_candidates = [value for value in {root_thread_id, (in_reply_to or "").strip()[:500]} if value]
    conv = None
    if thread_candidates:
        conv = session.exec(
            select(Conversation).where(
                Conversation.client_id == key.client_id,
                Conversation.channel == "email",
                Conversation.external_thread_id.in_(thread_candidates),
            )
        ).first()

    contact = _get_or_create_contact(
        session,
        key.client_id,
        "email",
        address,
        email=address,
        name=(from_name or "").strip()[:255],
    )
    now = datetime.utcnow()
    if conv is None:
        conv = Conversation(
            client_id=key.client_id,
            visitor_id=f"email:{address}",
            channel="email",
            contact_id=contact.id,
            external_thread_id=root_thread_id,
            channel_subject=clean_subject,
            visitor_email=address,
            status="escalated",
            created_at=now,
            updated_at=now,
        )
        session.add(conv)
        session.flush()
    else:
        conv.contact_id = contact.id
        conv.visitor_email = address
        conv.channel_subject = clean_subject or conv.channel_subject
        conv.status = "escalated"
        conv.closed_at = None
        conv.updated_at = now
        session.add(conv)

    session.add(Message(
        conversation_id=conv.id,
        role="user",
        content=body,
        external_id=provider_message_id,
    ))
    open_ticket = session.exec(
        select(Ticket).where(Ticket.conversation_id == conv.id, Ticket.status == "open")
    ).first()
    ticket_created = open_ticket is None
    if not open_ticket:
        open_ticket = Ticket(conversation_id=conv.id, reason=f"Email: {clean_subject or 'senza oggetto'}")
        session.add(open_ticket)
    assignee = _auto_assign(session, conv)
    _apply_sla(session, conv, start=True)
    session.commit()
    session.refresh(conv)
    session.refresh(open_ticket)
    if ticket_created:
        tenant = session.get(Client, key.client_id)
        notify_new_ticket(tenant.name if tenant else "Supporto", conv.id, open_ticket.id, open_ticket.reason)
        push_service.send(
            session, key.client_id, "assignment" if assignee else "escalation",
            title="Nuova email assegnata" if assignee else "Nuova email di supporto",
            body=open_ticket.reason, conversation_id=conv.id,
            operator_ids=[assignee.id] if assignee else None,
        )
        events.emit(session, key.client_id, "conversation.escalated", {
            "conversation_id": conv.id,
            "ticket_id": open_ticket.id,
            "reason": open_ticket.reason,
            "trigger": "email",
            "channel": "email",
        }, conv=conv)
    return {"ok": True, "created": True, "conversation_id": conv.id}


@app.post("/channels/whatsapp/inbound")
def whatsapp_inbound(
    from_number: str = Body(...),
    text: str = Body(...),
    message_id: str = Body(...),
    from_name: str = Body(""),
    consent: bool | None = Body(None),
    consent_source: str = Body(""),
    key: ApiKey = Depends(require_channel_write_key),
    session: Session = Depends(get_session),
):
    """Accept a normalized inbound WhatsApp text message from a provider adapter."""
    number = re.sub(r"[^0-9+]", "", (from_number or "").strip())[:32]
    body = (text or "").strip()[:MAX_CHAT_MESSAGE_CHARS]
    provider_message_id = (message_id or "").strip()[:500]
    if not re.fullmatch(r"\+[1-9][0-9]{6,14}", number):
        raise HTTPException(400, "valid from_number required")
    if not body:
        raise HTTPException(400, "text required")
    if not provider_message_id:
        raise HTTPException(400, "message_id required")
    clean_consent_source = (consent_source or "").strip()[:255]
    if consent is True and not clean_consent_source:
        raise HTTPException(400, "consent_source required when consent is granted")

    duplicate = session.exec(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.client_id == key.client_id,
            Conversation.channel == "whatsapp",
            Message.external_id == provider_message_id,
        )
    ).first()
    if duplicate:
        return {"ok": True, "created": False, "conversation_id": duplicate.conversation_id}

    contact = _get_or_create_contact(
        session, key.client_id, "whatsapp", number, name=(from_name or "").strip()[:255]
    )
    if consent is not None:
        consent_row = session.exec(
            select(WhatsAppConsent).where(
                WhatsAppConsent.client_id == key.client_id,
                WhatsAppConsent.contact_id == contact.id,
            )
        ).first()
        now_consent = datetime.utcnow()
        if consent_row is None:
            consent_row = WhatsAppConsent(client_id=key.client_id, contact_id=contact.id)
        consent_row.granted = consent
        consent_row.source = clean_consent_source or consent_row.source
        consent_row.granted_at = now_consent if consent else consent_row.granted_at
        consent_row.revoked_at = None if consent else now_consent
        consent_row.updated_at = now_consent
        session.add(consent_row)
    conv = session.exec(
        select(Conversation).where(
            Conversation.client_id == key.client_id,
            Conversation.channel == "whatsapp",
            Conversation.contact_id == contact.id,
            Conversation.status != "closed",
        ).order_by(Conversation.id.desc())
    ).first()
    now = datetime.utcnow()
    if conv is None:
        conv = Conversation(
            client_id=key.client_id,
            visitor_id=f"whatsapp:{number}",
            channel="whatsapp",
            contact_id=contact.id,
            external_thread_id=number,
            status="escalated",
            created_at=now,
            updated_at=now,
        )
        session.add(conv)
        session.flush()
    else:
        conv.status = "escalated"
        conv.closed_at = None
        conv.updated_at = now
        session.add(conv)

    session.add(Message(conversation_id=conv.id, role="user", content=body, external_id=provider_message_id))
    open_ticket = session.exec(
        select(Ticket).where(Ticket.conversation_id == conv.id, Ticket.status == "open")
    ).first()
    ticket_created = open_ticket is None
    if open_ticket is None:
        open_ticket = Ticket(conversation_id=conv.id, reason="Messaggio WhatsApp")
        session.add(open_ticket)
    assignee = _auto_assign(session, conv)
    _apply_sla(session, conv, start=True)
    session.commit()
    session.refresh(conv)
    session.refresh(open_ticket)
    if ticket_created:
        tenant = session.get(Client, key.client_id)
        notify_new_ticket(tenant.name if tenant else "Supporto", conv.id, open_ticket.id, open_ticket.reason)
        push_service.send(
            session, key.client_id, "assignment" if assignee else "escalation",
            title="Nuovo WhatsApp assegnato" if assignee else "Nuovo messaggio WhatsApp",
            body=open_ticket.reason, conversation_id=conv.id,
            operator_ids=[assignee.id] if assignee else None,
        )
        events.emit(session, key.client_id, "conversation.escalated", {
            "conversation_id": conv.id,
            "ticket_id": open_ticket.id,
            "reason": open_ticket.reason,
            "trigger": "whatsapp",
            "channel": "whatsapp",
        }, conv=conv)
    return {"ok": True, "created": True, "conversation_id": conv.id}


@app.post("/channels/meta/inbound")
def meta_messaging_inbound(
    platform: str = Body(...),
    sender_id: str = Body(...),
    text: str = Body(...),
    message_id: str = Body(...),
    thread_id: str = Body(""),
    sender_name: str = Body(""),
    key: ApiKey = Depends(require_channel_write_key),
    session: Session = Depends(get_session),
):
    """Normalized inbound adapter shared by Messenger and Instagram Direct."""
    clean_platform = (platform or "").strip().lower()
    external_sender = (sender_id or "").strip()[:255]
    body = (text or "").strip()[:MAX_CHAT_MESSAGE_CHARS]
    provider_message_id = (message_id or "").strip()[:500]
    provider_thread_id = (thread_id or external_sender).strip()[:500]
    if clean_platform not in {"messenger", "instagram"}:
        raise HTTPException(400, "platform must be messenger or instagram")
    if not external_sender or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,255}", external_sender):
        raise HTTPException(400, "valid sender_id required")
    if not body:
        raise HTTPException(400, "text required")
    if not provider_message_id:
        raise HTTPException(400, "message_id required")

    duplicate = session.exec(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.client_id == key.client_id,
            Conversation.channel == clean_platform,
            Message.external_id == provider_message_id,
        )
    ).first()
    if duplicate:
        return {"ok": True, "created": False, "conversation_id": duplicate.conversation_id}

    contact = _get_or_create_contact(
        session, key.client_id, clean_platform, external_sender,
        name=(sender_name or "").strip()[:255],
    )
    conv = session.exec(
        select(Conversation).where(
            Conversation.client_id == key.client_id,
            Conversation.channel == clean_platform,
            Conversation.external_thread_id == provider_thread_id,
            Conversation.status != "closed",
        ).order_by(Conversation.id.desc())
    ).first()
    now = datetime.utcnow()
    if conv is None:
        conv = Conversation(
            client_id=key.client_id,
            visitor_id=f"{clean_platform}:{external_sender}",
            channel=clean_platform,
            contact_id=contact.id,
            external_thread_id=provider_thread_id,
            status="escalated",
            created_at=now,
            updated_at=now,
        )
        session.add(conv)
        session.flush()
    else:
        conv.contact_id = contact.id
        conv.status = "escalated"
        conv.closed_at = None
        conv.updated_at = now
        session.add(conv)

    session.add(Message(conversation_id=conv.id, role="user", content=body, external_id=provider_message_id))
    open_ticket = session.exec(
        select(Ticket).where(Ticket.conversation_id == conv.id, Ticket.status == "open")
    ).first()
    ticket_created = open_ticket is None
    channel_label = "Messenger" if clean_platform == "messenger" else "Instagram"
    if open_ticket is None:
        open_ticket = Ticket(conversation_id=conv.id, reason=f"Messaggio {channel_label}")
        session.add(open_ticket)
    assignee = _auto_assign(session, conv)
    _apply_sla(session, conv, start=True)
    session.commit()
    session.refresh(conv)
    session.refresh(open_ticket)
    if ticket_created:
        tenant = session.get(Client, key.client_id)
        notify_new_ticket(tenant.name if tenant else "Supporto", conv.id, open_ticket.id, open_ticket.reason)
        push_service.send(
            session, key.client_id, "assignment" if assignee else "escalation",
            title=f"Nuovo {channel_label} assegnato" if assignee else f"Nuovo messaggio {channel_label}",
            body=open_ticket.reason, conversation_id=conv.id,
            operator_ids=[assignee.id] if assignee else None,
        )
        events.emit(session, key.client_id, "conversation.escalated", {
            "conversation_id": conv.id,
            "ticket_id": open_ticket.id,
            "reason": open_ticket.reason,
            "trigger": clean_platform,
            "channel": clean_platform,
        }, conv=conv)
    return {"ok": True, "created": True, "conversation_id": conv.id}


@app.get("/conversations")
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


@app.patch("/conversations/{conversation_id}/routing")
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


@app.get("/tickets")
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


HELPDESK_PROVIDERS = ("zendesk", "freshdesk")


def _helpdesk_connection_payload(row: HelpdeskConnection) -> dict:
    return {
        "id": row.id,
        "provider": row.provider,
        "external_account_id": row.external_account_id,
        "enabled": row.enabled,
        "updated_at": _iso(row.updated_at),
    }


def _helpdesk_export_payload(row: HelpdeskExport) -> dict:
    return {
        "status": row.status,
        "external_id": row.external_id,
        "external_url": row.external_url,
        "error": row.error,
    }


@app.get("/helpdesk/connections")
def list_helpdesk_connections(
    operator: Operator = Depends(require_operator), session: Session = Depends(get_session),
):
    rows = session.exec(
        select(HelpdeskConnection).where(HelpdeskConnection.client_id == operator.client_id)
        .order_by(HelpdeskConnection.provider)
    ).all()
    return {"providers": list(HELPDESK_PROVIDERS), "connections": [_helpdesk_connection_payload(row) for row in rows]}


@app.put("/helpdesk/connections/{provider}")
def set_helpdesk_connection(
    provider: str,
    body: dict = Body(...),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    provider = provider.strip().lower()
    if provider not in HELPDESK_PROVIDERS:
        raise HTTPException(400, "Provider helpdesk non supportato")
    account_id = str(body.get("external_account_id", "")).strip()
    if not account_id or len(account_id) > 255 or not re.fullmatch(r"[A-Za-z0-9_.:@/-]+", account_id):
        raise HTTPException(400, "Identificativo account non valido")
    row = session.exec(select(HelpdeskConnection).where(
        HelpdeskConnection.client_id == operator.client_id,
        HelpdeskConnection.provider == provider,
    )).first() or HelpdeskConnection(client_id=operator.client_id, provider=provider)
    row.external_account_id = account_id
    row.enabled = bool(body.get("enabled", True))
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    _audit(session, "operator", operator.email, "helpdesk.connection.update",
           target=f"helpdesk:{provider}", client_id=operator.client_id,
           detail={"enabled": row.enabled})
    return _helpdesk_connection_payload(row)


@app.delete("/helpdesk/connections/{provider}")
def delete_helpdesk_connection(
    provider: str,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    row = session.exec(select(HelpdeskConnection).where(
        HelpdeskConnection.client_id == operator.client_id,
        HelpdeskConnection.provider == provider.strip().lower(),
    )).first()
    if row is None:
        raise HTTPException(404, "Connessione helpdesk non trovata")
    for export in session.exec(select(HelpdeskExport).where(HelpdeskExport.connection_id == row.id)).all():
        session.delete(export)
    session.delete(row)
    session.commit()
    _audit(session, "operator", operator.email, "helpdesk.connection.delete",
           target=f"helpdesk:{provider}", client_id=operator.client_id)
    return {"ok": True}


@app.post("/tickets/{ticket_id}/helpdesk-export")
def export_ticket_to_helpdesk(
    ticket_id: int,
    body: dict = Body(...),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    provider = str(body.get("provider", "")).strip().lower()
    ticket = session.get(Ticket, ticket_id)
    conversation = session.get(Conversation, ticket.conversation_id) if ticket else None
    if not ticket or not conversation or conversation.client_id != operator.client_id:
        raise HTTPException(404, "Ticket non trovato")
    connection = session.exec(select(HelpdeskConnection).where(
        HelpdeskConnection.client_id == operator.client_id,
        HelpdeskConnection.provider == provider,
        HelpdeskConnection.enabled == True,  # noqa: E712
    )).first()
    if connection is None:
        raise HTTPException(400, "Connessione helpdesk non attiva")
    export = session.exec(select(HelpdeskExport).where(
        HelpdeskExport.connection_id == connection.id,
        HelpdeskExport.ticket_id == ticket.id,
    )).first() or HelpdeskExport(
        client_id=operator.client_id, connection_id=connection.id, ticket_id=ticket.id,
    )
    export.status, export.external_id, export.external_url, export.error = "pending", "", "", ""
    export.updated_at = datetime.utcnow()
    session.add(export)
    session.commit()
    messages = session.exec(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id)
    ).all()
    contact = session.get(Contact, conversation.contact_id) if conversation.contact_id else None
    delivered, external_id, external_url, error = helpdesk_service.export_ticket(
        client_id=operator.client_id,
        provider=provider,
        external_account_id=connection.external_account_id,
        ticket={
            "id": ticket.id,
            "reason": ticket.reason,
            "status": ticket.status,
            "created_at": _iso(ticket.created_at),
            "conversation": {
                "id": conversation.id,
                "channel": conversation.channel,
                "subject": conversation.channel_subject,
                "priority": conversation.priority,
                "visitor_url": conversation.visitor_url or "",
            },
            "contact": {
                "name": contact.name if contact else "",
                "email": (contact.email if contact else None) or conversation.visitor_email or "",
                "external_id": contact.external_id if contact else "",
            },
            "messages": [
                {"role": message.role, "content": message.content, "created_at": _iso(message.created_at)}
                for message in messages
            ],
        },
    )
    export.status = "delivered" if delivered else "failed"
    export.external_id = external_id
    export.external_url = external_url
    export.error = error[:255]
    export.updated_at = datetime.utcnow()
    session.add(export)
    session.commit()
    _audit(session, "operator", operator.email, "ticket.helpdesk_export",
           target=f"ticket:{ticket.id}", client_id=operator.client_id,
           detail={"provider": provider, "status": export.status})
    return _helpdesk_export_payload(export)


@app.post("/tickets/{ticket_id}/reply")
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


def _notify_visitor_reply(session, client_id, conv):
    """Best-effort visitor email notification on an operator reply (never blocks the reply)."""
    if conv.channel == "whatsapp" and conv.contact_id:
        contact = session.get(Contact, conv.contact_id)
        last_inbound = session.exec(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.role == "user")
            .order_by(Message.created_at.desc())
            .limit(1)
        ).first()
        if not contact or not last_inbound or last_inbound.created_at < datetime.utcnow() - timedelta(hours=24):
            return False
        latest_operator = session.exec(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.role == "operator")
            .order_by(Message.id.desc())
            .limit(1)
        ).first()
        return bool(latest_operator) and whatsapp_service.send_message(
            client_id=client_id,
            to=contact.external_id,
            body=latest_operator.content,
            reply_to_message_id=last_inbound.external_id or "",
        )
    if conv.channel in {"messenger", "instagram"} and conv.contact_id:
        contact = session.get(Contact, conv.contact_id)
        last_inbound = session.exec(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.role == "user")
            .order_by(Message.created_at.desc())
            .limit(1)
        ).first()
        latest_operator = session.exec(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.role == "operator")
            .order_by(Message.id.desc())
            .limit(1)
        ).first()
        return bool(contact and latest_operator) and meta_messaging_service.send_message(
            client_id=client_id,
            platform=conv.channel,
            recipient_id=contact.external_id,
            body=latest_operator.content,
            reply_to_message_id=last_inbound.external_id if last_inbound else "",
        )
    if conv.visitor_email:
        client = session.get(Client, client_id)
        client_name = client.name if client else "il supporto"
        if conv.channel == "email":
            messages = session.exec(
                select(Message)
                .where(Message.conversation_id == conv.id, Message.role == "operator")
                .order_by(Message.id.desc())
                .limit(1)
            ).all()
            if messages:
                return email_service.send_channel_reply(
                    conv.visitor_email,
                    client_name,
                    conv.channel_subject,
                    messages[0].content,
                    conv.external_thread_id,
                )
        else:
            return email_service.send_visitor_reply(conv.visitor_email, client_name, conv.visitor_url)
    return True


def _whatsapp_channel_status(session: Session, conv: Conversation) -> dict:
    last_inbound = session.exec(
        select(Message)
        .where(Message.conversation_id == conv.id, Message.role == "user")
        .order_by(Message.created_at.desc())
        .limit(1)
    ).first()
    window_expires_at = last_inbound.created_at + timedelta(hours=24) if last_inbound else None
    consent = session.exec(
        select(WhatsAppConsent).where(
            WhatsAppConsent.client_id == conv.client_id,
            WhatsAppConsent.contact_id == conv.contact_id,
        )
    ).first() if conv.contact_id else None
    return {
        "window_open": bool(window_expires_at and window_expires_at > datetime.utcnow()),
        "window_expires_at": _iso(window_expires_at),
        "consent_granted": bool(consent and consent.granted),
        "consent_source": consent.source if consent and consent.granted else "",
    }


@app.get("/conversations/{conversation_id}/whatsapp/status")
def whatsapp_status(
    conversation_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id or conv.channel != "whatsapp":
        raise HTTPException(404, "conversation not found")
    return _whatsapp_channel_status(session, conv)


@app.post("/conversations/{conversation_id}/whatsapp/template")
def send_whatsapp_template(
    conversation_id: int,
    template: str = Body(...),
    language_code: str = Body("it"),
    parameters: list[str] = Body(default=[]),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Send an approved template after explicit opt-in, including outside the 24-hour window."""
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id or conv.channel != "whatsapp":
        raise HTTPException(404, "conversation not found")
    contact = session.get(Contact, conv.contact_id) if conv.contact_id else None
    status = _whatsapp_channel_status(session, conv)
    template_name = (template or "").strip()
    locale = (language_code or "").strip()
    clean_parameters = [(value or "").strip()[:500] for value in parameters[:10]]
    if not re.fullmatch(r"[a-z0-9_]{1,128}", template_name):
        raise HTTPException(400, "invalid template")
    if not re.fullmatch(r"[a-z]{2}(?:_[A-Z]{2})?", locale):
        raise HTTPException(400, "invalid language_code")
    if not status["consent_granted"]:
        raise HTTPException(409, "WhatsApp consent required")
    if not contact:
        raise HTTPException(409, "WhatsApp contact unavailable")
    delivered = whatsapp_service.send_template(
        client_id=operator.client_id,
        to=contact.external_id,
        template=template_name,
        language=locale,
        parameters=clean_parameters,
    )
    if not delivered:
        return {"ok": False, "delivered": False}
    label = f"Template WhatsApp: {template_name}"
    if clean_parameters:
        label += " · " + " · ".join(clean_parameters)
    session.add(Message(conversation_id=conv.id, role="operator", content=label[:MAX_CHAT_MESSAGE_CHARS]))
    conv.updated_at = datetime.utcnow()
    conv.status = "open"
    session.add(conv)
    session.commit()
    _audit(
        session, "operator", operator.email, "whatsapp.template.send",
        target=f"conversation:{conv.id}", client_id=operator.client_id,
        detail={"template": template_name, "language": locale},
    )
    return {"ok": True, "delivered": True}


@app.post("/conversations/{conversation_id}/reply")
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


def _safe_attachment_filename(filename: str | None) -> str:
    """Strip paths/control characters before storing or placing a name in a header."""
    clean = Path(filename or "allegato").name
    clean = re.sub(r"[\x00-\x1f\x7f\r\n\"\\]", "_", clean).strip(" .")
    return clean[:180] or "allegato"


def _attachment_payload(attachment: Attachment) -> dict:
    return {
        "id": attachment.id,
        "message_id": attachment.message_id,
        "filename": attachment.filename,
        "content_type": attachment.content_type,
        "size_bytes": attachment.size_bytes,
        "created_at": _iso(attachment.created_at),
    }


@app.post("/conversations/{conversation_id}/attachments", status_code=201)
async def upload_conversation_attachment(
    conversation_id: int,
    file: UploadFile,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Store a private operator attachment and add it to the conversation atomically."""
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id:
        raise HTTPException(404, "conversation not found")
    if not attachment_service.configured():
        raise HTTPException(503, "attachment storage unavailable")
    content_type = (file.content_type or "").lower().split(";", 1)[0].strip()
    if content_type not in attachment_service.ALLOWED_TYPES:
        raise HTTPException(415, "file type not allowed")
    data = await file.read(attachment_service.MAX_BYTES + 1)
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > attachment_service.MAX_BYTES:
        raise HTTPException(413, "file too large")
    filename = _safe_attachment_filename(file.filename)
    suffix = Path(filename).suffix.lower()[:12]
    object_key = f"tenant/{operator.client_id}/conversation/{conversation_id}/{uuid.uuid4().hex}{suffix}"
    stored = await run_in_threadpool(attachment_service.put, object_key, data, content_type)
    if not stored:
        raise HTTPException(502, "attachment upload failed")
    try:
        message = Message(conversation_id=conversation_id, role="operator", content=f"Allegato: {filename}")
        session.add(message)
        conv.updated_at = datetime.utcnow()
        session.add(conv)
        session.flush()
        attachment = Attachment(
            client_id=operator.client_id,
            conversation_id=conversation_id,
            message_id=message.id,
            object_key=object_key,
            filename=filename,
            content_type=content_type,
            size_bytes=len(data),
        )
        session.add(attachment)
        session.commit()
        session.refresh(attachment)
    except Exception:
        session.rollback()
        await run_in_threadpool(attachment_service.delete, object_key)
        raise
    _audit(
        session, "operator", operator.email, "conversation.attachment.upload",
        target=f"conversation:{conversation_id}", client_id=operator.client_id,
        detail={"attachment_id": attachment.id, "content_type": content_type, "size_bytes": len(data)},
    )
    return _attachment_payload(attachment)


@app.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    attachment = session.get(Attachment, attachment_id)
    if not attachment or attachment.client_id != operator.client_id:
        raise HTTPException(404, "attachment not found")
    stored = await run_in_threadpool(attachment_service.get, attachment.object_key)
    if not stored:
        raise HTTPException(502, "attachment unavailable")
    data, _stored_type = stored
    if len(data) > attachment_service.MAX_BYTES:
        raise HTTPException(502, "invalid stored attachment")
    filename = _safe_attachment_filename(attachment.filename)
    return Response(
        content=data,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.delete("/attachments/{attachment_id}")
async def delete_attachment(
    attachment_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    attachment = session.get(Attachment, attachment_id)
    if not attachment or attachment.client_id != operator.client_id:
        raise HTTPException(404, "attachment not found")
    if not await run_in_threadpool(attachment_service.delete, attachment.object_key):
        raise HTTPException(502, "attachment deletion failed")
    message_id = attachment.message_id
    session.delete(attachment)
    session.flush()
    message = session.get(Message, message_id)
    if message:
        session.delete(message)
    session.commit()
    _audit(
        session, "operator", operator.email, "conversation.attachment.delete",
        target=f"attachment:{attachment_id}", client_id=operator.client_id,
    )
    return {"ok": True}


@app.post("/conversations/{conversation_id}/status")
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


def _erase_conversation(session: Session, conv: Conversation) -> None:
    """Hard-delete a conversation and everything hanging off it (messages, AI logs, tickets),
    respecting FK order. Used by GDPR erasure and the retention purge."""
    for lg in session.exec(select(AiResponseLog).where(AiResponseLog.conversation_id == conv.id)).all():
        session.delete(lg)
    for mention in session.exec(select(NoteMention).where(NoteMention.conversation_id == conv.id)).all():
        session.delete(mention)
    for link in session.exec(select(ConversationTag).where(ConversationTag.conversation_id == conv.id)).all():
        session.delete(link)
    for rating in session.exec(select(ConversationRating).where(ConversationRating.conversation_id == conv.id)).all():
        session.delete(rating)
    # a lead carries what the visitor typed about themselves: erasing the conversation must
    # erase it too, otherwise the "right to be forgotten" would leave the best data behind
    for lead in session.exec(select(Lead).where(Lead.conversation_id == conv.id)).all():
        for crm_sync in session.exec(select(CrmSync).where(CrmSync.lead_id == lead.id)).all():
            session.delete(crm_sync)
        session.delete(lead)
    session.flush()
    for note in session.exec(select(InternalNote).where(InternalNote.conversation_id == conv.id)).all():
        session.delete(note)
    session.flush()
    for attachment in session.exec(select(Attachment).where(Attachment.conversation_id == conv.id)).all():
        if attachment_service.configured() and not attachment_service.delete(attachment.object_key):
            log(
                logger, logging.WARNING, "attachment.retention_delete_failed",
                attachment_id=attachment.id, conversation_id=conv.id,
            )
        session.delete(attachment)
    session.flush()
    for m in session.exec(select(Message).where(Message.conversation_id == conv.id)).all():
        session.delete(m)
    for t in session.exec(select(Ticket).where(Ticket.conversation_id == conv.id)).all():
        session.delete(t)
    session.flush()
    session.delete(conv)


@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """GDPR erasure: permanently delete a conversation and its messages/tickets/AI logs."""
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id:
        raise HTTPException(404, "conversation not found")
    _erase_conversation(session, conv)
    session.commit()
    _audit(session, "operator", operator.email, "conversation.delete", target=f"conversation:{conversation_id}", client_id=operator.client_id)
    return {"ok": True}


@app.post("/gdpr/erase")
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


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


@app.post("/gdpr/export")
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


def purge_old_conversations(session: Session, days: int) -> int:
    """Data-minimization: delete conversations older than `days`. Returns how many were purged."""
    if days <= 0:
        return 0
    cutoff = datetime.utcnow() - timedelta(days=days)
    old = session.exec(select(Conversation).where(Conversation.created_at < cutoff)).all()
    for conv in old:
        _erase_conversation(session, conv)
    session.commit()
    return len(old)


# ---- Operator tools: canned responses + info-field definitions (per client) ----


@app.get("/team/operators")
def list_team_operators(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(Operator).where(Operator.client_id == operator.client_id).order_by(Operator.name, Operator.email)
    ).all()
    return [{"id": row.id, "name": _operator_name(row), "email": row.email} for row in rows]


@app.get("/departments")
def list_departments(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(Department).where(Department.client_id == operator.client_id).order_by(Department.name)
    ).all()
    return [{"id": row.id, "name": row.name} for row in rows]


@app.post("/departments")
def create_department(
    name: str = Body(..., embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    clean = name.strip()[:80]
    if not clean:
        raise HTTPException(400, "name required")
    existing = session.exec(
        select(Department).where(
            Department.client_id == operator.client_id,
            func.lower(Department.name) == clean.lower(),
        )
    ).first()
    if existing:
        raise HTTPException(409, "department already exists")
    department = Department(client_id=operator.client_id, name=clean)
    session.add(department)
    session.commit()
    session.refresh(department)
    _audit(session, "operator", operator.email, "department.create", target=f"department:{department.id}", client_id=operator.client_id)
    return {"id": department.id, "name": department.name}


def _require_department(session: Session, client_id: int, department_id: int) -> Department:
    department = session.get(Department, department_id)
    if not department or department.client_id != client_id:
        raise HTTPException(404, "department not found")
    return department


@app.get("/departments/{department_id}/members")
def list_department_members(
    department_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Operators in the queue's round-robin pool."""
    _require_department(session, operator.client_id, department_id)
    rows = session.exec(
        select(Operator, DepartmentMember)
        .join(DepartmentMember, DepartmentMember.operator_id == Operator.id)
        .where(DepartmentMember.department_id == department_id, DepartmentMember.client_id == operator.client_id)
        .order_by(Operator.id)
    ).all()
    return [{"id": op.id, "name": _operator_name(op), "email": op.email} for op, _ in rows]


@app.post("/departments/{department_id}/members")
def add_department_member(
    department_id: int,
    operator_id: int = Body(..., embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    _require_department(session, operator.client_id, department_id)
    member_operator = session.get(Operator, operator_id)
    if not member_operator or member_operator.client_id != operator.client_id:
        raise HTTPException(404, "operator not found")
    existing = session.exec(
        select(DepartmentMember).where(
            DepartmentMember.department_id == department_id,
            DepartmentMember.operator_id == operator_id,
        )
    ).first()
    if existing:
        return {"ok": True, "id": existing.id}
    row = DepartmentMember(
        client_id=operator.client_id, department_id=department_id, operator_id=operator_id
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    _audit(
        session, "operator", operator.email, "department.member_add",
        target=f"department:{department_id}", client_id=operator.client_id,
        detail={"operator_id": operator_id},
    )
    return {"ok": True, "id": row.id}


@app.delete("/departments/{department_id}/members/{operator_id}")
def remove_department_member(
    department_id: int,
    operator_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    _require_department(session, operator.client_id, department_id)
    row = session.exec(
        select(DepartmentMember).where(
            DepartmentMember.client_id == operator.client_id,
            DepartmentMember.department_id == department_id,
            DepartmentMember.operator_id == operator_id,
        )
    ).first()
    if not row:
        raise HTTPException(404, "member not found")
    session.delete(row)
    session.commit()
    _audit(
        session, "operator", operator.email, "department.member_remove",
        target=f"department:{department_id}", client_id=operator.client_id,
        detail={"operator_id": operator_id},
    )
    return {"ok": True}


@app.delete("/departments/{department_id}")
def delete_department(
    department_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Deleting a queue must never orphan anything hanging off it: its members, the SLA
    policies scoped to it and the routing fallback go away, and its conversations fall back to
    the generic queue (keeping their SLA clock, re-matched against the remaining policies)."""
    department = session.get(Department, department_id)
    if not department or department.client_id != operator.client_id:
        raise HTTPException(404, "department not found")
    for member in session.exec(
        select(DepartmentMember).where(DepartmentMember.department_id == department.id)
    ).all():
        session.delete(member)
    setting = _routing_setting(session, operator.client_id)
    if setting and setting.fallback_department_id == department.id:
        setting.fallback_department_id = None
        session.add(setting)
    scoped_policy_ids = [
        p.id for p in session.exec(select(SlaPolicy).where(SlaPolicy.department_id == department.id)).all()
    ]
    for conv in session.exec(
        select(Conversation).where(
            Conversation.client_id == operator.client_id,
            Conversation.department_id == department.id,
        )
    ).all():
        conv.department_id = None
        conv.sla_policy_id = None
        _apply_sla(session, conv)  # re-match against the policies that remain
        session.add(conv)
    # a policy scoped to this department can still be referenced by conversations that have
    # since moved to another queue: detach those before dropping the policies
    for conv in session.exec(
        select(Conversation).where(
            Conversation.client_id == operator.client_id,
            Conversation.sla_policy_id.in_(scoped_policy_ids),
        )
    ).all() if scoped_policy_ids else []:
        conv.sla_policy_id = None
        _apply_sla(session, conv)
        session.add(conv)
    session.flush()
    for policy_id in scoped_policy_ids:
        policy = session.get(SlaPolicy, policy_id)
        if policy is not None:
            session.delete(policy)
    session.flush()
    session.delete(department)
    session.commit()
    _audit(session, "operator", operator.email, "department.delete", target=f"department:{department_id}", client_id=operator.client_id)
    return {"ok": True}


# ---- SLA policies + routing settings (per client) ----


def _support_schedule_payload(row: SupportSchedule | None) -> dict:
    if row is None:
        return {
            "enabled": False, "weekdays": [1, 2, 3, 4, 5], "start_time": "09:00",
            "end_time": "18:00", "timezone": "Europe/Rome", "source": "panel",
            "closed_dates": [],
            "include_italian_holidays": False,
        }
    return {
        "enabled": row.enabled,
        "weekdays": business_hours.parse_weekdays(row.weekdays),
        "start_time": row.start_time,
        "end_time": row.end_time,
        "timezone": row.timezone,
        "closed_dates": json.loads(row.closed_dates or "[]"),
        "include_italian_holidays": row.include_italian_holidays,
        "source": row.source,
        "updated_at": _iso(row.updated_at),
    }


def _validated_support_schedule(body: dict) -> dict:
    try:
        weekdays = business_hours.parse_weekdays(body.get("weekdays", []))
        start_time = business_hours.parse_time(body.get("start_time", "")).strftime("%H:%M")
        end_time = business_hours.parse_time(body.get("end_time", "")).strftime("%H:%M")
        timezone_name = business_hours.validate_timezone(body.get("timezone", ""))
        closed_dates = business_hours.parse_closed_dates(body.get("closed_dates", []))
        if start_time == end_time:
            raise ValueError("L’orario di apertura e chiusura non può coincidere")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "enabled": bool(body.get("enabled", False)),
        "weekdays": weekdays,
        "start_time": start_time,
        "end_time": end_time,
        "timezone": timezone_name,
        "closed_dates": [item.isoformat() for item in closed_dates],
        "include_italian_holidays": bool(body.get("include_italian_holidays", False)),
    }


def _save_support_schedule(session: Session, client_id: int, body: dict, source: str) -> SupportSchedule:
    clean = _validated_support_schedule(body)
    row = session.exec(select(SupportSchedule).where(SupportSchedule.client_id == client_id)).first()
    if row is None:
        row = SupportSchedule(client_id=client_id)
    row.enabled = clean["enabled"]
    row.weekdays = ",".join(str(day) for day in clean["weekdays"])
    row.start_time = clean["start_time"]
    row.end_time = clean["end_time"]
    row.timezone = clean["timezone"]
    # WordPress owns weekly hours and timezone, while exceptional closures are managed in
    # the panel. Older plugin payloads must never erase them during an automatic sync.
    if "closed_dates" in body or row.id is None:
        row.closed_dates = json.dumps(clean["closed_dates"])
    if "include_italian_holidays" in body or row.id is None:
        row.include_italian_holidays = clean["include_italian_holidays"]
    row.source = source
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    for conversation in session.exec(select(Conversation).where(
        Conversation.client_id == client_id,
        Conversation.sla_started_at.is_not(None),
        Conversation.closed_at.is_(None),
    )).all():
        _apply_sla(session, conversation)
        session.add(conversation)
    session.commit()
    session.refresh(row)
    return row


@app.get("/support-schedule")
def get_support_schedule(
    operator: Operator = Depends(require_operator), session: Session = Depends(get_session),
):
    row = session.exec(select(SupportSchedule).where(
        SupportSchedule.client_id == operator.client_id,
    )).first()
    return _support_schedule_payload(row)


@app.put("/support-schedule")
def set_support_schedule(
    body: dict = Body(...),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    row = _save_support_schedule(session, operator.client_id, body, "panel")
    _audit(session, "operator", operator.email, "support_schedule.update",
           target=f"client:{operator.client_id}", client_id=operator.client_id,
           detail={"enabled": row.enabled, "timezone": row.timezone})
    return _support_schedule_payload(row)


def _plugin_secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _trusted_plugin_proof_url(allowed_origins: str, value: str) -> str:
    """Accept a WordPress REST proof URL only on one of the tenant's allowlisted origins."""
    from urllib.parse import urlparse

    try:
        clean = webhooks.validate_url(str(value or "").strip())
    except ValueError:
        return ""
    parsed = urlparse(clean)
    if parsed.username or parsed.password:
        return ""
    if _normalize_origins(clean) not in set(_split_origins(allowed_origins)):
        return ""
    route = (parsed.path.rstrip("/") + "?" + parsed.query).lower()
    if "wpai/v1/site-proof" not in route:
        return ""
    return clean


def _verify_plugin_site(proof_url: str, secret: str) -> bool:
    """Challenge the allowlisted WordPress site before accepting a server-only sync secret."""
    from urllib.parse import urlencode

    challenge = secrets.token_urlsafe(32)
    proof_url += ("&" if "?" in proof_url else "?") + urlencode({"challenge": challenge})
    try:
        webhooks.validate_url(proof_url)
        if not webhooks._resolves_to_public_address(proof_url):
            return False
        with urllib.request.urlopen(proof_url, timeout=8) as response:
            result = json.loads(response.read(4096).decode("utf-8"))
        expected = hmac.new(secret.encode(), challenge.encode(), hashlib.sha256).hexdigest()
        return secrets.compare_digest(str(result.get("proof", "")), expected)
    except (ValueError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False


def _require_plugin_installation(
    authorization: str = Header(None), session: Session = Depends(get_session),
) -> PluginInstallation:
    secret = _bearer_token(authorization)
    if len(secret) < 32 or len(secret) > 256:
        raise HTTPException(401, "invalid plugin credential")
    row = session.exec(select(PluginInstallation).where(
        PluginInstallation.secret_hash == _plugin_secret_hash(secret),
    )).first()
    if row is None:
        raise HTTPException(401, "invalid plugin credential")
    return row


@app.post("/plugin/register")
def register_plugin_installation(
    request: Request,
    body: dict = Body(...),
    client: Client = Depends(rate_limit_ingest),
    session: Session = Depends(get_session),
):
    secret = str(body.get("secret", ""))
    if len(secret) < 32 or len(secret) > 256:
        raise HTTPException(400, "Credenziale plugin non valida")
    origin = _trusted_callback_origin(client.allowed_origins, body.get("site_url"), request)
    proof_url = _trusted_plugin_proof_url(client.allowed_origins, body.get("proof_url", ""))
    if not origin or not proof_url:
        raise HTTPException(403, "Sito WordPress non presente nelle origini autorizzate")
    if not _verify_plugin_site(proof_url, secret):
        raise HTTPException(422, "Verifica del sito WordPress non riuscita")
    digest = _plugin_secret_hash(secret)
    conflict = session.exec(select(PluginInstallation).where(
        PluginInstallation.secret_hash == digest,
        PluginInstallation.client_id != client.id,
    )).first()
    if conflict:
        raise HTTPException(409, "Credenziale plugin già associata")
    row = session.exec(select(PluginInstallation).where(
        PluginInstallation.client_id == client.id,
        PluginInstallation.site_origin == origin,
    )).first() or PluginInstallation(client_id=client.id, site_origin=origin, secret_hash=digest)
    row.secret_hash = digest
    row.plugin_version = str(body.get("plugin_version", ""))[:32]
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    if isinstance(body.get("support_schedule"), dict):
        _save_support_schedule(session, client.id, body["support_schedule"], "wordpress")
        row.last_sync_at = datetime.utcnow()
        session.add(row)
        session.commit()
    _audit(session, "system", f"wordpress:{origin}", "plugin.register",
           target=f"plugin_installation:{row.id}", client_id=client.id,
           detail={"site_origin": origin, "plugin_version": row.plugin_version})
    return {"ok": True, "site_origin": origin, "schedule": _support_schedule_payload(
        session.exec(select(SupportSchedule).where(SupportSchedule.client_id == client.id)).first()
    )}


@app.put("/plugin/support-schedule")
def sync_plugin_support_schedule(
    body: dict = Body(...),
    installation: PluginInstallation = Depends(_require_plugin_installation),
    session: Session = Depends(get_session),
):
    row = _save_support_schedule(session, installation.client_id, body, "wordpress")
    installation.last_sync_at = datetime.utcnow()
    installation.updated_at = datetime.utcnow()
    session.add(installation)
    session.commit()
    return {"ok": True, "schedule": _support_schedule_payload(row)}


def _sla_policy_payload(policy: SlaPolicy) -> dict:
    return {
        "id": policy.id,
        "name": policy.name,
        "department_id": policy.department_id,
        "priority": policy.priority,
        "first_response_minutes": policy.first_response_minutes,
        "resolution_minutes": policy.resolution_minutes,
        "active": policy.active,
    }


def _clean_minutes(value: int) -> int:
    """0 disables the target; anything above a year is a configuration mistake."""
    return max(0, min(int(value), 525600))


@app.get("/sla-policies")
def list_sla_policies(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(SlaPolicy).where(SlaPolicy.client_id == operator.client_id).order_by(SlaPolicy.id)
    ).all()
    return [_sla_policy_payload(row) for row in rows]


@app.post("/sla-policies")
def create_sla_policy(
    name: str = Body(...),
    first_response_minutes: int = Body(60),
    resolution_minutes: int = Body(480),
    department_id: int | None = Body(None),
    priority: str = Body(""),
    active: bool = Body(True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    clean_name = name.strip()[:80]
    if not clean_name:
        raise HTTPException(400, "name required")
    if priority and priority not in PRIORITIES:
        raise HTTPException(400, "invalid priority")
    if department_id is not None:
        _require_department(session, operator.client_id, department_id)
    policy = SlaPolicy(
        client_id=operator.client_id,
        name=clean_name,
        department_id=department_id,
        priority=priority,
        first_response_minutes=_clean_minutes(first_response_minutes),
        resolution_minutes=_clean_minutes(resolution_minutes),
        active=active,
    )
    session.add(policy)
    session.commit()
    session.refresh(policy)
    _recompute_running_slas(session, operator.client_id)  # a new policy may be the better match
    _audit(
        session, "operator", operator.email, "sla_policy.create",
        target=f"sla_policy:{policy.id}", client_id=operator.client_id,
        detail=_sla_policy_payload(policy),
    )
    return _sla_policy_payload(policy)


@app.patch("/sla-policies/{policy_id}")
def update_sla_policy(
    policy_id: int,
    name: str | None = Body(None),
    first_response_minutes: int | None = Body(None),
    resolution_minutes: int | None = Body(None),
    priority: str | None = Body(None),
    active: bool | None = Body(None),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    policy = session.get(SlaPolicy, policy_id)
    if not policy or policy.client_id != operator.client_id:
        raise HTTPException(404, "sla policy not found")
    if name is not None:
        clean_name = name.strip()[:80]
        if not clean_name:
            raise HTTPException(400, "name required")
        policy.name = clean_name
    if priority is not None:
        if priority and priority not in PRIORITIES:
            raise HTTPException(400, "invalid priority")
        policy.priority = priority
    if first_response_minutes is not None:
        policy.first_response_minutes = _clean_minutes(first_response_minutes)
    if resolution_minutes is not None:
        policy.resolution_minutes = _clean_minutes(resolution_minutes)
    if active is not None:
        policy.active = active
    session.add(policy)
    session.commit()
    _recompute_running_slas(session, operator.client_id)
    _audit(
        session, "operator", operator.email, "sla_policy.update",
        target=f"sla_policy:{policy_id}", client_id=operator.client_id,
        detail=_sla_policy_payload(policy),
    )
    return _sla_policy_payload(policy)


@app.delete("/sla-policies/{policy_id}")
def delete_sla_policy(
    policy_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    policy = session.get(SlaPolicy, policy_id)
    if not policy or policy.client_id != operator.client_id:
        raise HTTPException(404, "sla policy not found")
    for conv in session.exec(
        select(Conversation).where(
            Conversation.client_id == operator.client_id,
            Conversation.sla_policy_id == policy_id,
        )
    ).all():
        conv.sla_policy_id = None
        session.add(conv)
    session.flush()
    session.delete(policy)
    session.commit()
    # the detached conversations now follow whichever policy still matches (possibly none)
    _recompute_running_slas(session, operator.client_id)
    _audit(
        session, "operator", operator.email, "sla_policy.delete",
        target=f"sla_policy:{policy_id}", client_id=operator.client_id,
    )
    return {"ok": True}


def _recompute_running_slas(session: Session, client_id: int) -> None:
    """Re-match every conversation with a running SLA after the policies changed, so the inbox
    never shows a deadline computed from a policy that no longer exists."""
    convs = session.exec(
        select(Conversation).where(
            Conversation.client_id == client_id,
            Conversation.sla_started_at.is_not(None),
            Conversation.closed_at.is_(None),
        )
    ).all()
    for conv in convs:
        _apply_sla(session, conv)
        session.add(conv)
    session.commit()


def _routing_payload(setting: RoutingSetting | None) -> dict:
    return {
        "mode": setting.mode if setting else "off",
        "fallback_department_id": setting.fallback_department_id if setting else None,
        "last_operator_id": setting.last_operator_id if setting else None,
    }


@app.get("/routing-settings")
def get_routing_settings(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    return _routing_payload(_routing_setting(session, operator.client_id))


@app.put("/routing-settings")
def set_routing_settings(
    mode: str = Body(...),
    fallback_department_id: int | None = Body(None),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    if mode not in ROUTING_MODES:
        raise HTTPException(400, "invalid mode")
    if fallback_department_id is not None:
        _require_department(session, operator.client_id, fallback_department_id)
    setting = _routing_setting(session, operator.client_id)
    if setting is None:
        setting = RoutingSetting(client_id=operator.client_id)
    setting.mode = mode
    setting.fallback_department_id = fallback_department_id
    setting.updated_at = datetime.utcnow()
    session.add(setting)
    session.commit()
    session.refresh(setting)
    _audit(
        session, "operator", operator.email, "routing.update",
        target=f"client:{operator.client_id}", client_id=operator.client_id,
        detail={"mode": mode, "fallback_department_id": fallback_department_id},
    )
    return _routing_payload(setting)


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return s or "campo"


@app.get("/canned-responses")
def list_canned(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(CannedResponse).where(CannedResponse.client_id == operator.client_id)
        .order_by(CannedResponse.position, CannedResponse.id)
    ).all()
    return [{"id": r.id, "title": r.title, "body": r.body, "position": r.position} for r in rows]


@app.post("/canned-responses")
def create_canned(
    title: str = Body(...),
    body: str = Body(...),
    position: int = Body(0),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    row = CannedResponse(client_id=operator.client_id, title=title, body=body, position=position)
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"id": row.id, "title": row.title, "body": row.body, "position": row.position}


@app.delete("/canned-responses/{canned_id}")
def delete_canned(canned_id: int, operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    row = session.get(CannedResponse, canned_id)
    if not row or row.client_id != operator.client_id:
        raise HTTPException(404, "not found")
    session.delete(row)
    session.commit()
    return {"ok": True}


@app.get("/info-fields")
def list_info_fields(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(InfoField).where(InfoField.client_id == operator.client_id)
        .order_by(InfoField.position, InfoField.id)
    ).all()
    return [{"id": r.id, "label": r.label, "key": r.key, "position": r.position} for r in rows]


@app.post("/info-fields")
def create_info_field(
    label: str = Body(...),
    key: str | None = Body(None),
    position: int = Body(0),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    slug = _slugify(key or label)
    # ensure the key is unique within the client so placeholder substitution is unambiguous
    existing = {f.key for f in session.exec(select(InfoField).where(InfoField.client_id == operator.client_id)).all()}
    base, n = slug, 2
    while slug in existing:
        slug = f"{base}_{n}"
        n += 1
    row = InfoField(client_id=operator.client_id, label=label, key=slug, position=position)
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"id": row.id, "label": row.label, "key": row.key, "position": row.position}


@app.delete("/info-fields/{field_id}")
def delete_info_field(field_id: int, operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    row = session.get(InfoField, field_id)
    if not row or row.client_id != operator.client_id:
        raise HTTPException(404, "not found")
    session.delete(row)
    session.commit()
    return {"ok": True}


@app.get("/conversations/{conversation_id}/info")
def get_conversation_info(conversation_id: int, operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """Operator-only: the structured info values saved on this conversation (keyed by
    InfoField.key). Kept separate from /messages so it never leaks to the visitor's widget."""
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id:
        raise HTTPException(404, "conversation not found")
    return {"info": json.loads(conv.info) if conv.info else {}}


@app.put("/conversations/{conversation_id}/info")
def set_conversation_info(
    conversation_id: int,
    info: dict = Body(..., embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id:
        raise HTTPException(404, "conversation not found")
    # store only string values, capped, to keep the JSON blob bounded
    clean = {str(k): str(v)[:2000] for k, v in info.items()}
    conv.info = json.dumps(clean)
    conv.updated_at = datetime.utcnow()
    session.add(conv)
    session.commit()
    return {"ok": True, "info": clean}


@app.get("/knowledge-base")
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


# ---- Advanced analytics --------------------------------------------------------------------


@app.get("/analytics/overview")
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


@app.get("/analytics/knowledge-gaps")
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


@app.post("/analytics/knowledge-gaps/review")
def review_knowledge_gap(
    question: str = Body(...),
    status: str = Body("taught"),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Mark a gap as handled or dismissed so it stops coming back in the list."""
    if status not in ("taught", "ignored"):
        raise HTTPException(400, "status must be 'taught' or 'ignored'")
    if not (question or "").strip():
        raise HTTPException(400, "question required")
    review = analytics.review_gap(session, operator.client_id, question, status, operator.email)
    _audit(
        session, "operator", operator.email, "knowledge_gap.review",
        client_id=operator.client_id, detail={"status": status},
    )
    return {"ok": True, "question_hash": review.question_hash, "status": review.status}


# ---- Lead capture ------------------------------------------------------------------------

LEAD_FIELD_TYPES = ("text", "email", "tel", "select")
LEAD_TRIGGERS = ("escalation", "chat_start")
MAX_LEAD_FIELDS = 8
MAX_LEAD_VALUE_CHARS = 500


def _clean_lead_fields(raw) -> list[dict]:
    """A field is {key,label,type,required,points}. Points make the score explainable: it is
    the sum of the points of the fields the visitor actually filled, nothing hidden."""
    if not isinstance(raw, list) or not raw:
        raise HTTPException(400, "serve almeno un campo")
    if len(raw) > MAX_LEAD_FIELDS:
        raise HTTPException(400, f"massimo {MAX_LEAD_FIELDS} campi")
    clean, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(400, "ogni campo deve essere un oggetto")
        label = str(item.get("label", "")).strip()[:80]
        if not label:
            raise HTTPException(400, "ogni campo deve avere un'etichetta")
        key = _slugify(item.get("key") or label)
        if key in seen:
            raise HTTPException(400, f"chiave duplicata: {key}")
        seen.add(key)
        field_type = item.get("type", "text")
        if field_type not in LEAD_FIELD_TYPES:
            raise HTTPException(400, f"tipo campo non valido: {field_type}")
        options = [str(o).strip()[:60] for o in (item.get("options") or []) if str(o).strip()][:10]
        if field_type == "select" and not options:
            raise HTTPException(400, "un campo a scelta richiede almeno un'opzione")
        clean.append({
            "key": key,
            "label": label,
            "type": field_type,
            "required": bool(item.get("required")),
            "points": min(max(int(item.get("points") or 0), 0), 50),
            "options": options,
        })
    return clean


def _lead_form_payload(form: LeadForm, *, public: bool = False) -> dict:
    fields = json.loads(form.fields or "[]")
    if public:
        # the visitor never sees the scoring weights
        fields = [{k: v for k, v in field.items() if k != "points"} for field in fields]
        return {
            "id": form.id,
            "intro": form.intro,
            "consent_text": form.consent_text,
            "fields": fields,
            "trigger": form.trigger,
        }
    return {
        "id": form.id,
        "name": form.name,
        "trigger": form.trigger,
        "intro": form.intro,
        "consent_text": form.consent_text,
        "fields": fields,
        "active": form.active,
        "created_at": _iso(form.created_at),
    }


@app.get("/widget/lead-form")
def widget_lead_form(
    trigger: str = "escalation",
    client: Client = Depends(require_client),
    session: Session = Depends(get_session),
):
    """The active form for this moment, or null. Scoring weights are stripped: they are a
    business decision, not something to ship to the visitor's browser."""
    if trigger not in LEAD_TRIGGERS:
        raise HTTPException(400, "trigger non valido")
    form = session.exec(
        select(LeadForm)
        .where(LeadForm.client_id == client.id, LeadForm.active.is_(True), LeadForm.trigger == trigger)
        .order_by(LeadForm.id)
    ).first()
    return {"form": _lead_form_payload(form, public=True) if form else None}


@app.post("/widget/leads")
def widget_submit_lead(
    form_id: int = Body(...),
    data: dict = Body(...),
    conversation_id: int | None = Body(None),
    conversation_token: str | None = Body(None),
    consent: bool = Body(False),
    client: Client = Depends(rate_limit_chat),
    session: Session = Depends(get_session),
):
    """Store a submission. Consent is enforced server-side when the form asks for it — a
    frontend that forgets the checkbox must not be able to bypass it."""
    form = session.get(LeadForm, form_id)
    if not form or form.client_id != client.id or not form.active:
        raise HTTPException(404, "form not found")
    if form.consent_text and not consent:
        raise HTTPException(400, "consenso richiesto")
    conv = None
    if conversation_id is not None:
        conv = session.get(Conversation, conversation_id)
        if not conv or conv.client_id != client.id:
            raise HTTPException(404, "conversation not found")
        _require_conversation_token(conv, conversation_token)

    fields = json.loads(form.fields or "[]")
    values, score = {}, 0
    for field in fields:
        raw = data.get(field["key"])
        value = "" if raw is None else str(raw).strip()[:MAX_LEAD_VALUE_CHARS]
        if field["required"] and not value:
            raise HTTPException(400, f"campo obbligatorio mancante: {field['label']}")
        if value:
            values[field["key"]] = value
            score += field.get("points", 0)
    lead = Lead(
        client_id=client.id,
        form_id=form.id,
        conversation_id=conv.id if conv else None,
        data=json.dumps(values, ensure_ascii=False),
        score=min(score, 100),
        consent=bool(consent),
        consent_text=form.consent_text,
    )
    session.add(lead)
    session.commit()
    session.refresh(lead)
    log(logger, logging.INFO, "lead.captured", client_id=client.id, lead_id=lead.id, score=lead.score)
    webhooks.emit(session, client.id, "lead.captured", {
        "lead_id": lead.id,
        "conversation_id": lead.conversation_id,
        "score": lead.score,
        "data": values,
    })
    return {"ok": True, "id": lead.id}


@app.get("/lead-forms")
def list_lead_forms(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(LeadForm).where(LeadForm.client_id == operator.client_id).order_by(LeadForm.id)
    ).all()
    return {
        "triggers": list(LEAD_TRIGGERS),
        "field_types": list(LEAD_FIELD_TYPES),
        "forms": [_lead_form_payload(row) for row in rows],
    }


@app.post("/lead-forms")
def create_lead_form(
    name: str = Body(...),
    fields: list = Body(...),
    trigger: str = Body("escalation"),
    intro: str = Body(""),
    consent_text: str = Body(""),
    active: bool = Body(True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    clean_name = name.strip()[:80]
    if not clean_name:
        raise HTTPException(400, "name required")
    if trigger not in LEAD_TRIGGERS:
        raise HTTPException(400, "trigger non valido")
    form = LeadForm(
        client_id=operator.client_id,
        name=clean_name,
        trigger=trigger,
        fields=json.dumps(_clean_lead_fields(fields)),
        intro=intro.strip()[:300],
        consent_text=consent_text.strip()[:500],
        active=active,
    )
    session.add(form)
    session.commit()
    session.refresh(form)
    _audit(
        session, "operator", operator.email, "lead_form.create",
        target=f"lead_form:{form.id}", client_id=operator.client_id,
    )
    return _lead_form_payload(form)


@app.patch("/lead-forms/{form_id}")
def update_lead_form(
    form_id: int,
    name: str | None = Body(None),
    fields: list | None = Body(None),
    trigger: str | None = Body(None),
    intro: str | None = Body(None),
    consent_text: str | None = Body(None),
    active: bool | None = Body(None),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    form = session.get(LeadForm, form_id)
    if not form or form.client_id != operator.client_id:
        raise HTTPException(404, "form not found")
    if name is not None:
        clean = name.strip()[:80]
        if not clean:
            raise HTTPException(400, "name required")
        form.name = clean
    if trigger is not None:
        if trigger not in LEAD_TRIGGERS:
            raise HTTPException(400, "trigger non valido")
        form.trigger = trigger
    if fields is not None:
        form.fields = json.dumps(_clean_lead_fields(fields))
    if intro is not None:
        form.intro = intro.strip()[:300]
    if consent_text is not None:
        form.consent_text = consent_text.strip()[:500]
    if active is not None:
        form.active = active
    form.updated_at = datetime.utcnow()
    session.add(form)
    session.commit()
    _audit(
        session, "operator", operator.email, "lead_form.update",
        target=f"lead_form:{form_id}", client_id=operator.client_id,
    )
    return _lead_form_payload(form)


@app.delete("/lead-forms/{form_id}")
def delete_lead_form(
    form_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """The captured leads survive the form: they are the tenant's data, not the form's."""
    form = session.get(LeadForm, form_id)
    if not form or form.client_id != operator.client_id:
        raise HTTPException(404, "form not found")
    for lead in session.exec(select(Lead).where(Lead.form_id == form.id)).all():
        lead.form_id = None
        session.add(lead)
    session.flush()
    session.delete(form)
    session.commit()
    _audit(
        session, "operator", operator.email, "lead_form.delete",
        target=f"lead_form:{form_id}", client_id=operator.client_id,
    )
    return {"ok": True}


def _lead_query(client_id: int, min_score: int | None, days: int | None):
    query = select(Lead).where(Lead.client_id == client_id)
    if min_score is not None:
        query = query.where(Lead.score >= min_score)
    if days:
        query = query.where(Lead.created_at >= datetime.utcnow() - timedelta(days=days))
    return query


CRM_PROVIDERS = ("brevo", "zoho", "pipedrive")


def _crm_connection_payload(row: CrmConnection) -> dict:
    return {
        "id": row.id,
        "provider": row.provider,
        "external_account_id": row.external_account_id,
        "enabled": row.enabled,
        "updated_at": _iso(row.updated_at),
    }


@app.get("/crm/connections")
def list_crm_connections(
    operator: Operator = Depends(require_operator), session: Session = Depends(get_session),
):
    rows = session.exec(
        select(CrmConnection).where(CrmConnection.client_id == operator.client_id)
        .order_by(CrmConnection.provider)
    ).all()
    return {"providers": list(CRM_PROVIDERS), "connections": [_crm_connection_payload(row) for row in rows]}


@app.put("/crm/connections/{provider}")
def set_crm_connection(
    provider: str,
    body: dict = Body(...),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    provider = provider.strip().lower()
    if provider not in CRM_PROVIDERS:
        raise HTTPException(400, "Provider CRM non supportato")
    account_id = str(body.get("external_account_id", "")).strip()
    if not account_id or len(account_id) > 255 or not re.fullmatch(r"[A-Za-z0-9_.:@/-]+", account_id):
        raise HTTPException(400, "Identificativo account non valido")
    row = session.exec(select(CrmConnection).where(
        CrmConnection.client_id == operator.client_id, CrmConnection.provider == provider,
    )).first()
    if row is None:
        row = CrmConnection(client_id=operator.client_id, provider=provider)
    row.external_account_id = account_id
    row.enabled = bool(body.get("enabled", True))
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    _audit(session, "operator", operator.email, "crm.connection.update",
           target=f"crm:{provider}", client_id=operator.client_id,
           detail={"enabled": row.enabled})
    return _crm_connection_payload(row)


@app.post("/crm/connect/brevo")
def connect_brevo(
    body: dict = Body(...),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    api_key = str(body.get("api_key", "")).strip()
    if len(api_key) < 20 or len(api_key) > 512:
        raise HTTPException(400, "Chiave Brevo non valida")
    connected, account_id, error = crm_service.configure_brevo(client_id=operator.client_id, api_key=api_key)
    if not connected:
        raise HTTPException(422, error or "Collegamento Brevo non riuscito")
    row = session.exec(select(CrmConnection).where(
        CrmConnection.client_id == operator.client_id, CrmConnection.provider == "brevo",
    )).first() or CrmConnection(client_id=operator.client_id, provider="brevo")
    row.external_account_id = account_id
    row.enabled = True
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    _audit(session, "operator", operator.email, "crm.connection.update", target="crm:brevo",
           client_id=operator.client_id, detail={"enabled": True})
    return _crm_connection_payload(row)


@app.delete("/crm/connections/{provider}")
def delete_crm_connection(
    provider: str,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    row = session.exec(select(CrmConnection).where(
        CrmConnection.client_id == operator.client_id,
        CrmConnection.provider == provider.strip().lower(),
    )).first()
    if row is None:
        raise HTTPException(404, "Connessione CRM non trovata")
    if not crm_service.disconnect(client_id=operator.client_id, provider=row.provider):
        raise HTTPException(503, "Impossibile revocare in sicurezza la credenziale CRM")
    for sync in session.exec(select(CrmSync).where(CrmSync.connection_id == row.id)).all():
        session.delete(sync)
    session.delete(row)
    session.commit()
    _audit(session, "operator", operator.email, "crm.connection.delete",
           target=f"crm:{provider}", client_id=operator.client_id)
    return {"ok": True}


@app.post("/leads/{lead_id}/crm-sync")
def sync_lead_to_crm(
    lead_id: int,
    body: dict = Body(...),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    provider = str(body.get("provider", "")).strip().lower()
    lead = session.exec(select(Lead).where(
        Lead.id == lead_id, Lead.client_id == operator.client_id,
    )).first()
    if lead is None:
        raise HTTPException(404, "Lead non trovato")
    connection = session.exec(select(CrmConnection).where(
        CrmConnection.client_id == operator.client_id,
        CrmConnection.provider == provider,
        CrmConnection.enabled == True,  # noqa: E712
    )).first()
    if connection is None:
        raise HTTPException(400, "Connessione CRM non attiva")
    sync = session.exec(select(CrmSync).where(
        CrmSync.connection_id == connection.id, CrmSync.lead_id == lead.id,
    )).first()
    if sync is None:
        sync = CrmSync(client_id=operator.client_id, connection_id=connection.id, lead_id=lead.id)
    sync.status, sync.error, sync.external_id = "pending", "", ""
    sync.updated_at = datetime.utcnow()
    session.add(sync)
    session.commit()
    delivered, external_id, error = crm_service.sync_lead(
        client_id=operator.client_id,
        provider=provider,
        external_account_id=connection.external_account_id,
        lead={
            "id": lead.id,
            "conversation_id": lead.conversation_id,
            "data": json.loads(lead.data or "{}"),
            "score": lead.score,
            "consent": lead.consent,
            "consent_text": lead.consent_text,
            "created_at": _iso(lead.created_at),
        },
    )
    sync.status = "delivered" if delivered else "failed"
    sync.external_id = external_id
    sync.error = error[:255]
    sync.updated_at = datetime.utcnow()
    session.add(sync)
    session.commit()
    _audit(session, "operator", operator.email, "lead.crm_sync",
           target=f"lead:{lead.id}", client_id=operator.client_id,
           detail={"provider": provider, "delivered": delivered})
    return {"ok": delivered, "status": sync.status, "external_id": external_id, "error": error}


@app.get("/leads")
def list_leads(
    min_score: int | None = None,
    days: int | None = None,
    limit: int = 100,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    rows = session.exec(
        _lead_query(operator.client_id, min_score, days)
        .order_by(Lead.id.desc())
        .limit(_bounded_limit(limit))
    ).all()
    syncs = session.exec(select(CrmSync).where(
        CrmSync.client_id == operator.client_id,
        CrmSync.lead_id.in_([row.id for row in rows]),
    )).all() if rows else []
    connections = {row.id: row.provider for row in session.exec(select(CrmConnection).where(
        CrmConnection.client_id == operator.client_id,
    )).all()}
    sync_by_lead: dict[int, dict] = {}
    for sync in syncs:
        sync_by_lead.setdefault(sync.lead_id, {})[connections.get(sync.connection_id, "crm")] = {
            "status": sync.status, "external_id": sync.external_id, "error": sync.error,
        }
    return [
        {
            "id": row.id,
            "conversation_id": row.conversation_id,
            "form_id": row.form_id,
            "score": row.score,
            "consent": row.consent,
            "consent_text": row.consent_text,
            "data": json.loads(row.data or "{}"),
            "created_at": _iso(row.created_at),
            "crm_syncs": sync_by_lead.get(row.id, {}),
        }
        for row in rows
    ]


def _csv_cell(value) -> str:
    """Quote for CSV and neutralise formula injection: a cell starting with = + - @ is executed
    by spreadsheet apps when the export is opened, so prefix it with a quote."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@"):
        text = "'" + text
    return '"' + text.replace('"', '""') + '"'


@app.get("/leads/export")
def export_leads(
    min_score: int | None = None,
    days: int | None = None,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """CSV of the captured leads, one column per field key seen in the period."""
    rows = session.exec(_lead_query(operator.client_id, min_score, days).order_by(Lead.id)).all()
    parsed = [(row, json.loads(row.data or "{}")) for row in rows]
    keys: list[str] = []
    for _, data in parsed:
        for key in data:
            if key not in keys:
                keys.append(key)
    header = ["id", "created_at", "conversation_id", "score", "consent", *keys]
    lines = [",".join(_csv_cell(h) for h in header)]
    for row, data in parsed:
        lines.append(",".join(_csv_cell(v) for v in [
            row.id, _iso(row.created_at), row.conversation_id or "", row.score,
            "sì" if row.consent else "no", *[data.get(key, "") for key in keys],
        ]))
    _audit(
        session, "operator", operator.email, "lead.export",
        client_id=operator.client_id, detail={"leads": len(parsed)},
    )
    return Response(
        content="﻿" + "\n".join(lines),  # BOM: Excel apre l'UTF-8 correttamente
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="lead.csv"'},
    )


# ---- Proactive messages ------------------------------------------------------------------
#
# The rules are evaluated in the widget, so the public endpoint returns exactly what the
# browser needs to decide — nothing more. Frequency capping and the visitor's opt-out live in
# the browser too: they are a courtesy to that person, not a server-side quota.

PROACTIVE_TRIGGERS = ("url", "time_on_page", "exit_intent", "cart")
PROACTIVE_FREQUENCIES = ("once_per_session", "once_per_day", "always")
MAX_PROACTIVE_MESSAGE_CHARS = 300


def _proactive_payload(rule: ProactiveRule, *, public: bool = False) -> dict:
    data = {
        "id": rule.id,
        "trigger_type": rule.trigger_type,
        "url_pattern": rule.url_pattern,
        "delay_seconds": rule.delay_seconds,
        "message": rule.message,
        "frequency": rule.frequency,
    }
    if public:
        return data
    return {
        **data,
        "name": rule.name,
        "active": rule.active,
        "position": rule.position,
        "impressions": rule.impressions,
        "engagements": rule.engagements,
        # share of impressions that opened a chat (null until there's data to divide by)
        "engagement_rate": round(rule.engagements / rule.impressions, 3) if rule.impressions else None,
    }


@app.get("/widget/proactive")
def widget_proactive_rules(
    client: Client = Depends(require_client),
    session: Session = Depends(get_session),
):
    """Active rules for the widget (client api_key). Public content by design: the payload is
    the message and its trigger, never anything internal."""
    rows = session.exec(
        select(ProactiveRule)
        .where(ProactiveRule.client_id == client.id, ProactiveRule.active.is_(True))
        .order_by(ProactiveRule.position, ProactiveRule.id)
    ).all()
    return {"rules": [_proactive_payload(row, public=True) for row in rows]}


@app.post("/widget/proactive/{rule_id}/event")
def widget_proactive_event(
    rule_id: int,
    kind: str = Body(..., embed=True),  # impression | engagement
    client: Client = Depends(rate_limit_chat),
    session: Session = Depends(get_session),
):
    """Counts an impression or an engagement. Rate-limited like the chat: the counters only
    steer a business decision, but they still shouldn't be trivially inflatable."""
    if kind not in ("impression", "engagement"):
        raise HTTPException(400, "kind must be 'impression' or 'engagement'")
    rule = session.get(ProactiveRule, rule_id)
    if not rule or rule.client_id != client.id:
        raise HTTPException(404, "rule not found")
    if kind == "impression":
        rule.impressions += 1
    else:
        rule.engagements += 1
    session.add(rule)
    session.commit()
    return {"ok": True}


@app.get("/proactive-rules")
def list_proactive_rules(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(ProactiveRule).where(ProactiveRule.client_id == operator.client_id)
        .order_by(ProactiveRule.position, ProactiveRule.id)
    ).all()
    return {
        "triggers": list(PROACTIVE_TRIGGERS),
        "frequencies": list(PROACTIVE_FREQUENCIES),
        "rules": [_proactive_payload(row) for row in rows],
    }


@app.post("/proactive-rules")
def create_proactive_rule(
    name: str = Body(...),
    message: str = Body(...),
    trigger_type: str = Body("time_on_page"),
    url_pattern: str = Body(""),
    delay_seconds: int = Body(15),
    frequency: str = Body("once_per_day"),
    active: bool = Body(True),
    position: int = Body(0),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    clean_name = name.strip()[:80]
    clean_message = message.strip()[:MAX_PROACTIVE_MESSAGE_CHARS]
    if not clean_name or not clean_message:
        raise HTTPException(400, "nome e messaggio sono obbligatori")
    if trigger_type not in PROACTIVE_TRIGGERS:
        raise HTTPException(400, "trigger non valido")
    if frequency not in PROACTIVE_FREQUENCIES:
        raise HTTPException(400, "frequenza non valida")
    rule = ProactiveRule(
        client_id=operator.client_id,
        name=clean_name,
        message=clean_message,
        trigger_type=trigger_type,
        url_pattern=url_pattern.strip()[:300],
        delay_seconds=min(max(int(delay_seconds), 0), 3600),
        frequency=frequency,
        active=active,
        position=position,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    _audit(
        session, "operator", operator.email, "proactive.create",
        target=f"proactive:{rule.id}", client_id=operator.client_id,
        detail={"trigger": trigger_type},
    )
    return _proactive_payload(rule)


@app.patch("/proactive-rules/{rule_id}")
def update_proactive_rule(
    rule_id: int,
    name: str | None = Body(None),
    message: str | None = Body(None),
    trigger_type: str | None = Body(None),
    url_pattern: str | None = Body(None),
    delay_seconds: int | None = Body(None),
    frequency: str | None = Body(None),
    active: bool | None = Body(None),
    position: int | None = Body(None),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    rule = session.get(ProactiveRule, rule_id)
    if not rule or rule.client_id != operator.client_id:
        raise HTTPException(404, "rule not found")
    if name is not None:
        clean = name.strip()[:80]
        if not clean:
            raise HTTPException(400, "name required")
        rule.name = clean
    if message is not None:
        clean = message.strip()[:MAX_PROACTIVE_MESSAGE_CHARS]
        if not clean:
            raise HTTPException(400, "message required")
        rule.message = clean
    if trigger_type is not None:
        if trigger_type not in PROACTIVE_TRIGGERS:
            raise HTTPException(400, "trigger non valido")
        rule.trigger_type = trigger_type
    if url_pattern is not None:
        rule.url_pattern = url_pattern.strip()[:300]
    if delay_seconds is not None:
        rule.delay_seconds = min(max(int(delay_seconds), 0), 3600)
    if frequency is not None:
        if frequency not in PROACTIVE_FREQUENCIES:
            raise HTTPException(400, "frequenza non valida")
        rule.frequency = frequency
    if active is not None:
        rule.active = active
    if position is not None:
        rule.position = position
    rule.updated_at = datetime.utcnow()
    session.add(rule)
    session.commit()
    _audit(
        session, "operator", operator.email, "proactive.update",
        target=f"proactive:{rule_id}", client_id=operator.client_id,
    )
    return _proactive_payload(rule)


@app.delete("/proactive-rules/{rule_id}")
def delete_proactive_rule(
    rule_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    rule = session.get(ProactiveRule, rule_id)
    if not rule or rule.client_id != operator.client_id:
        raise HTTPException(404, "rule not found")
    session.delete(rule)
    session.commit()
    _audit(
        session, "operator", operator.email, "proactive.delete",
        target=f"proactive:{rule_id}", client_id=operator.client_id,
    )
    return {"ok": True}


# ---- Workflows (no-code automations) -----------------------------------------------------


def _workflow_payload(workflow: Workflow) -> dict:
    return {
        "id": workflow.id,
        "name": workflow.name,
        "trigger": workflow.trigger,
        "conditions": json.loads(workflow.conditions or "[]"),
        "actions": json.loads(workflow.actions or "[]"),
        "active": workflow.active,
        "position": workflow.position,
        "run_count": workflow.run_count,
        "last_run_at": _iso(workflow.last_run_at),
    }


@app.get("/workflows")
def list_workflows(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """Rules plus the vocabulary the panel needs to build the editor, so triggers, fields,
    operators and actions are never duplicated (and never drift) in the frontend."""
    rows = session.exec(
        select(Workflow).where(Workflow.client_id == operator.client_id)
        .order_by(Workflow.position, Workflow.id)
    ).all()
    return {
        "catalog": {
            "triggers": list(workflows.TRIGGERS),
            "condition_fields": list(workflows.CONDITION_FIELDS),
            "condition_ops": list(workflows.CONDITION_OPS),
            "action_types": list(workflows.ACTION_TYPES),
        },
        "workflows": [_workflow_payload(row) for row in rows],
    }


@app.post("/workflows")
def create_workflow(
    name: str = Body(...),
    trigger: str = Body(...),
    conditions: list = Body([]),
    actions: list = Body([]),
    active: bool = Body(True),
    position: int = Body(0),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    clean_name = name.strip()[:80]
    if not clean_name:
        raise HTTPException(400, "name required")
    if trigger not in workflows.TRIGGERS:
        raise HTTPException(400, "trigger non valido")
    try:
        clean_conditions = workflows.validate_conditions(conditions)
        clean_actions = workflows.validate_actions(session, operator.client_id, actions)
    except workflows.WorkflowConfigError as exc:
        raise HTTPException(400, str(exc)) from exc
    workflow = Workflow(
        client_id=operator.client_id,
        name=clean_name,
        trigger=trigger,
        conditions=json.dumps(clean_conditions),
        actions=json.dumps(clean_actions),
        active=active,
        position=position,
    )
    session.add(workflow)
    session.commit()
    session.refresh(workflow)
    _audit(
        session, "operator", operator.email, "workflow.create",
        target=f"workflow:{workflow.id}", client_id=operator.client_id,
        detail={"trigger": trigger, "actions": [a["type"] for a in clean_actions]},
    )
    return _workflow_payload(workflow)


@app.patch("/workflows/{workflow_id}")
def update_workflow(
    workflow_id: int,
    name: str | None = Body(None),
    trigger: str | None = Body(None),
    conditions: list | None = Body(None),
    actions: list | None = Body(None),
    active: bool | None = Body(None),
    position: int | None = Body(None),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    workflow = session.get(Workflow, workflow_id)
    if not workflow or workflow.client_id != operator.client_id:
        raise HTTPException(404, "workflow not found")
    if name is not None:
        clean_name = name.strip()[:80]
        if not clean_name:
            raise HTTPException(400, "name required")
        workflow.name = clean_name
    if trigger is not None:
        if trigger not in workflows.TRIGGERS:
            raise HTTPException(400, "trigger non valido")
        workflow.trigger = trigger
    try:
        if conditions is not None:
            workflow.conditions = json.dumps(workflows.validate_conditions(conditions))
        if actions is not None:
            workflow.actions = json.dumps(workflows.validate_actions(session, operator.client_id, actions))
    except workflows.WorkflowConfigError as exc:
        raise HTTPException(400, str(exc)) from exc
    if active is not None:
        workflow.active = active
    if position is not None:
        workflow.position = position
    workflow.updated_at = datetime.utcnow()
    session.add(workflow)
    session.commit()
    _audit(
        session, "operator", operator.email, "workflow.update",
        target=f"workflow:{workflow_id}", client_id=operator.client_id,
    )
    return _workflow_payload(workflow)


@app.delete("/workflows/{workflow_id}")
def delete_workflow(
    workflow_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    workflow = session.get(Workflow, workflow_id)
    if not workflow or workflow.client_id != operator.client_id:
        raise HTTPException(404, "workflow not found")
    for run in session.exec(select(WorkflowRun).where(WorkflowRun.workflow_id == workflow.id)).all():
        session.delete(run)
    session.flush()
    session.delete(workflow)
    session.commit()
    _audit(
        session, "operator", operator.email, "workflow.delete",
        target=f"workflow:{workflow_id}", client_id=operator.client_id,
    )
    return {"ok": True}


@app.post("/workflows/{workflow_id}/preview")
def preview_workflow(
    workflow_id: int,
    conversation_id: int = Body(..., embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Dry run against a real conversation: says whether the rule would match and what it would
    do, without applying anything."""
    workflow = session.get(Workflow, workflow_id)
    if not workflow or workflow.client_id != operator.client_id:
        raise HTTPException(404, "workflow not found")
    conv = _require_conversation(session, operator.client_id, conversation_id)
    return workflows.preview(session, workflow, conv)


@app.get("/workflows/{workflow_id}/runs")
def list_workflow_runs(
    workflow_id: int,
    limit: int = 50,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    workflow = session.get(Workflow, workflow_id)
    if not workflow or workflow.client_id != operator.client_id:
        raise HTTPException(404, "workflow not found")
    rows = session.exec(
        select(WorkflowRun)
        .where(WorkflowRun.workflow_id == workflow.id)
        .order_by(WorkflowRun.id.desc())
        .limit(_bounded_limit(limit, default=50))
    ).all()
    return [
        {
            "id": row.id,
            "conversation_id": row.conversation_id,
            "event": row.event,
            "matched": row.matched,
            "applied": json.loads(row.applied or "[]"),
            "error": row.error,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


# ---- Public API: scoped keys ------------------------------------------------------------
#
# Distinct from the widget `Client.api_key`, which is embedded in a public page and only
# identifies the tenant. These keys are server-side credentials: scoped, revocable, stored as
# a digest, and rate-limited on their own bucket.

API_SCOPES = (
    "conversations:read",
    "conversations:write",
    "knowledge:write",
    "stats:read",
    "channels:write",
)
API_KEY_PREFIX = "wpa"
api_limiter = make_limiter(int(os.getenv("PUBLIC_API_RATE_LIMIT", "120")), 60)
# don't write last_used_at on every call: one update per minute per key is enough to answer
# "is this key still in use?" without a write on the hot path
API_KEY_TOUCH_SECONDS = 60


def _hash_api_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _generate_api_key() -> tuple[str, str]:
    """Returns (full token, public prefix). The full token is shown once and never stored."""
    prefix = f"{API_KEY_PREFIX}_{secrets.token_hex(4)}"
    return f"{prefix}_{secrets.token_urlsafe(32)}", prefix


def _api_key_scopes(key: ApiKey) -> list[str]:
    return [s for s in (key.scopes or "").split(",") if s]


def _resolve_api_key(session: Session, token: str) -> ApiKey | None:
    key = session.exec(select(ApiKey).where(ApiKey.token_hash == _hash_api_key(token))).first()
    if key is None or key.revoked_at is not None:
        return None
    return key


def require_api_scope(scope: str):
    """Dependency factory for the /v1 endpoints: validates the bearer key, checks the scope and
    applies the public-API rate limit. Returns the ApiKey (which carries the tenant)."""

    def dependency(
        authorization: str = Header(None),
        session: Session = Depends(get_session),
    ) -> ApiKey:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "missing bearer token")
        key = _resolve_api_key(session, authorization[7:].strip())
        if key is None:
            raise HTTPException(401, "invalid api key")
        if scope not in _api_key_scopes(key):
            raise HTTPException(403, f"scope richiesto: {scope}")
        api_limiter.check(f"api:{key.id}")
        now = datetime.utcnow()
        if key.last_used_at is None or (now - key.last_used_at).total_seconds() > API_KEY_TOUCH_SECONDS:
            key.last_used_at = now
            session.add(key)
            session.commit()
        return key

    return dependency


def _api_key_payload(key: ApiKey) -> dict:
    return {
        "id": key.id,
        "name": key.name,
        "prefix": key.prefix,
        "scopes": _api_key_scopes(key),
        "created_by": key.created_by,
        "created_at": _iso(key.created_at),
        "last_used_at": _iso(key.last_used_at),
        "revoked_at": _iso(key.revoked_at),
    }


@app.get("/api-keys")
def list_api_keys(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(ApiKey).where(ApiKey.client_id == operator.client_id).order_by(ApiKey.id.desc())
    ).all()
    return [_api_key_payload(row) for row in rows]


@app.post("/api-keys")
def create_api_key(
    name: str = Body(""),
    scopes: list[str] = Body([]),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Creates a key and returns it **once**: only its digest is stored, so a lost key can
    only be replaced, never recovered."""
    unknown = [s for s in scopes if s not in API_SCOPES]
    if unknown:
        raise HTTPException(400, f"scope non valido: {unknown[0]}")
    if not scopes:
        raise HTTPException(400, "almeno uno scope è richiesto")
    token, prefix = _generate_api_key()
    key = ApiKey(
        client_id=operator.client_id,
        name=name.strip()[:80],
        prefix=prefix,
        token_hash=_hash_api_key(token),
        scopes=",".join(scopes),
        created_by=operator.email,
    )
    session.add(key)
    session.commit()
    session.refresh(key)
    _audit(
        session, "operator", operator.email, "api_key.create",
        target=f"api_key:{key.id}", client_id=operator.client_id,
        detail={"prefix": prefix, "scopes": scopes},
    )
    return {**_api_key_payload(key), "token": token}


@app.delete("/api-keys/{key_id}")
def revoke_api_key(
    key_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    key = session.get(ApiKey, key_id)
    if not key or key.client_id != operator.client_id:
        raise HTTPException(404, "api key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.utcnow()
        session.add(key)
        session.commit()
    _audit(
        session, "operator", operator.email, "api_key.revoke",
        target=f"api_key:{key_id}", client_id=operator.client_id, detail={"prefix": key.prefix},
    )
    return {"ok": True}


# ---- Public API v1 -----------------------------------------------------------------------
#
# Versioned on purpose: /v1 is a contract with third-party integrations, so its shapes change
# only by adding fields. The panel keeps using the unversioned operator endpoints.


def _v1_conversation(session: Session, conv: Conversation, now: datetime) -> dict:
    tags = tagging.conversation_tags(session, [conv.id], conv.client_id).get(conv.id, [])
    rating = session.exec(
        select(ConversationRating).where(ConversationRating.conversation_id == conv.id)
    ).first()
    return {
        "id": conv.id,
        "visitor_id": conv.visitor_id,
        "channel": conv.channel,
        "contact_id": conv.contact_id,
        "external_thread_id": conv.external_thread_id,
        "status": conv.status,
        "priority": conv.priority,
        "department_id": conv.department_id,
        "assigned_operator_id": conv.assigned_operator_id,
        "created_at": _iso(conv.created_at),
        "updated_at": _iso(conv.updated_at),
        "closed_at": _iso(conv.closed_at),
        "tags": [t["name"] for t in tags],
        "classification": tagging.classification_payload(conv),
        "sla": _sla_view(conv, now),
        "rating": _rating_payload(rating),
    }


@app.get("/v1/conversations")
def v1_list_conversations(
    status: str | None = None,
    priority: str | None = None,
    tag_id: int | None = None,
    before_id: int | None = None,
    limit: int = 50,
    key: ApiKey = Depends(require_api_scope("conversations:read")),
    session: Session = Depends(get_session),
):
    query = select(Conversation).where(Conversation.client_id == key.client_id)
    if status:
        if status not in ("open", "escalated", "closed"):
            raise HTTPException(400, "invalid status")
        query = query.where(Conversation.status == status)
    if priority:
        if priority not in PRIORITIES:
            raise HTTPException(400, "invalid priority")
        query = query.where(Conversation.priority == priority)
    if tag_id is not None:
        tag = session.get(Tag, tag_id)
        if not tag or tag.client_id != key.client_id:
            raise HTTPException(404, "tag not found")
        query = query.where(
            Conversation.id.in_(
                select(ConversationTag.conversation_id).where(ConversationTag.tag_id == tag_id)
            )
        )
    if before_id:
        query = query.where(Conversation.id < before_id)
    convs = session.exec(
        query.order_by(Conversation.id.desc()).limit(_bounded_limit(limit, default=50, maximum=200))
    ).all()
    now = datetime.utcnow()
    return {
        "data": [_v1_conversation(session, conv, now) for conv in convs],
        "next_before_id": convs[-1].id if convs else None,
    }


@app.get("/v1/conversations/{conversation_id}")
def v1_get_conversation(
    conversation_id: int,
    key: ApiKey = Depends(require_api_scope("conversations:read")),
    session: Session = Depends(get_session),
):
    conv = _require_conversation(session, key.client_id, conversation_id)
    messages = session.exec(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)
    ).all()
    payload = _v1_conversation(session, conv, datetime.utcnow())
    # internal notes are deliberately absent: they are not part of the public contract
    payload["messages"] = [
        {"id": m.id, "role": m.role, "content": m.content, "created_at": _iso(m.created_at)}
        for m in messages
    ]
    return payload


@app.post("/v1/conversations/{conversation_id}/reply")
def v1_reply(
    conversation_id: int,
    reply: str = Body(..., embed=True),
    key: ApiKey = Depends(require_api_scope("conversations:write")),
    session: Session = Depends(get_session),
):
    """Reply as the team from an external system (CRM, automation). Behaves like an operator
    reply: reopens the conversation, closes open tickets, stops the first-response SLA and
    notifies the visitor by email if they left one."""
    conv = _require_conversation(session, key.client_id, conversation_id)
    if conv.channel == "whatsapp" and not _whatsapp_channel_status(session, conv)["window_open"]:
        raise HTTPException(409, "WhatsApp 24-hour window expired; use an approved template")
    text = (reply or "").strip()
    if not text:
        raise HTTPException(400, "reply required")
    now = datetime.utcnow()
    session.add(Message(conversation_id=conv.id, role="operator", content=text[:MAX_CHAT_MESSAGE_CHARS]))
    if conv.first_response_at is None:
        conv.first_response_at = now
    conv.status = "open"
    conv.updated_at = now
    session.add(conv)
    for ticket in session.exec(
        select(Ticket).where(Ticket.conversation_id == conv.id, Ticket.status == "open")
    ).all():
        ticket.status = "answered"
        ticket.updated_at = now
        session.add(ticket)
    session.commit()
    _audit(
        session, "api", key.prefix, "conversation.reply",
        target=f"conversation:{conversation_id}", client_id=key.client_id,
    )
    _notify_visitor_reply(session, key.client_id, conv)
    events.emit(session, key.client_id, "conversation.replied", {"conversation_id": conv.id, "via": "api"}, conv=conv)
    return {"ok": True}


@app.post("/v1/conversations/{conversation_id}/status")
def v1_set_status(
    conversation_id: int,
    status: str = Body(..., embed=True),
    key: ApiKey = Depends(require_api_scope("conversations:write")),
    session: Session = Depends(get_session),
):
    if status not in ("open", "closed"):
        raise HTTPException(400, "status must be 'open' or 'closed'")
    conv = _require_conversation(session, key.client_id, conversation_id)
    now = datetime.utcnow()
    conv.status = status
    conv.updated_at = now
    conv.closed_at = now if status == "closed" else None
    session.add(conv)
    session.commit()
    _audit(
        session, "api", key.prefix, f"conversation.{status}",
        target=f"conversation:{conversation_id}", client_id=key.client_id,
    )
    if status == "closed":
        events.emit(session, key.client_id, "conversation.closed", {"conversation_id": conv.id}, conv=conv)
    return {"ok": True, "status": status}


@app.post("/v1/conversations/{conversation_id}/tags")
def v1_tag(
    conversation_id: int,
    name: str = Body(..., embed=True),
    key: ApiKey = Depends(require_api_scope("conversations:write")),
    session: Session = Depends(get_session),
):
    conv = _require_conversation(session, key.client_id, conversation_id)
    tag = tagging.get_or_create_tag(session, key.client_id, name, source="manual")
    if tag is None:
        raise HTTPException(400, "nome tag non valido o limite raggiunto")
    tagging.attach_tag(session, conv, tag, source="manual")
    return {"id": tag.id, "name": tag.name}


@app.get("/v1/stats")
def v1_stats(
    key: ApiKey = Depends(require_api_scope("stats:read")),
    session: Session = Depends(get_session),
):
    return _build_stats(session, key.client_id)


@app.post("/v1/knowledge/documents")
def v1_ingest_document(
    title: str = Body(...),
    text: str = Body(...),
    key: ApiKey = Depends(require_api_scope("knowledge:write")),
    session: Session = Depends(get_session),
):
    """Queue a text document into the knowledge base. Returns the job id to poll on
    /ingest/jobs/{id} with the same key."""
    clean_title = (title or "").strip()[:200]
    body = (text or "").strip()
    if not clean_title or not body:
        raise HTTPException(400, "title and text required")
    if len(body) > MAX_INGEST_TEXT_CHARS:
        raise HTTPException(413, "text too large")
    job = _enqueue(session, key.client_id, "document", {"source_ref": clean_title, "text": body})
    _audit(
        session, "api", key.prefix, "knowledge.ingest",
        target=f"job:{job.id}", client_id=key.client_id, detail={"title": clean_title},
    )
    return {"job_id": job.id, "status": job.status}


# ---- Webhooks (tenant-managed, signed) ---------------------------------------------------


def _webhook_payload(endpoint: WebhookEndpoint, *, with_secret: bool = False) -> dict:
    data = {
        "id": endpoint.id,
        "url": endpoint.url,
        "events": [e for e in (endpoint.events or "").split(",") if e],
        "description": endpoint.description,
        "active": endpoint.active,
        "created_at": _iso(endpoint.created_at),
    }
    if with_secret:
        data["secret"] = endpoint.secret  # shown once, at creation
    return data


@app.get("/webhooks")
def list_webhooks(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(WebhookEndpoint).where(WebhookEndpoint.client_id == operator.client_id).order_by(WebhookEndpoint.id)
    ).all()
    return {"events": list(webhooks.EVENTS), "endpoints": [_webhook_payload(row) for row in rows]}


@app.post("/webhooks")
def create_webhook(
    url: str = Body(...),
    events: list[str] = Body([]),
    description: str = Body(""),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    unknown = [e for e in events if e not in webhooks.EVENTS]
    if unknown:
        raise HTTPException(400, f"evento non valido: {unknown[0]}")
    try:
        clean_url = webhooks.validate_url(url)
    except webhooks.WebhookUrlError as exc:
        raise HTTPException(400, str(exc)) from exc
    endpoint = WebhookEndpoint(
        client_id=operator.client_id,
        url=clean_url,
        secret=webhooks.new_secret(),
        events=",".join(events),
        description=description.strip()[:200],
    )
    session.add(endpoint)
    session.commit()
    session.refresh(endpoint)
    _audit(
        session, "operator", operator.email, "webhook.create",
        target=f"webhook:{endpoint.id}", client_id=operator.client_id,
        detail={"url": clean_url, "events": events},
    )
    return _webhook_payload(endpoint, with_secret=True)


@app.patch("/webhooks/{endpoint_id}")
def update_webhook(
    endpoint_id: int,
    url: str | None = Body(None),
    events: list[str] | None = Body(None),
    description: str | None = Body(None),
    active: bool | None = Body(None),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    endpoint = session.get(WebhookEndpoint, endpoint_id)
    if not endpoint or endpoint.client_id != operator.client_id:
        raise HTTPException(404, "webhook not found")
    if url is not None:
        try:
            endpoint.url = webhooks.validate_url(url)
        except webhooks.WebhookUrlError as exc:
            raise HTTPException(400, str(exc)) from exc
    if events is not None:
        unknown = [e for e in events if e not in webhooks.EVENTS]
        if unknown:
            raise HTTPException(400, f"evento non valido: {unknown[0]}")
        endpoint.events = ",".join(events)
    if description is not None:
        endpoint.description = description.strip()[:200]
    if active is not None:
        endpoint.active = active
    endpoint.updated_at = datetime.utcnow()
    session.add(endpoint)
    session.commit()
    _audit(
        session, "operator", operator.email, "webhook.update",
        target=f"webhook:{endpoint_id}", client_id=operator.client_id,
    )
    return _webhook_payload(endpoint)


@app.delete("/webhooks/{endpoint_id}")
def delete_webhook(
    endpoint_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    endpoint = session.get(WebhookEndpoint, endpoint_id)
    if not endpoint or endpoint.client_id != operator.client_id:
        raise HTTPException(404, "webhook not found")
    for delivery in session.exec(
        select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint.id)
    ).all():
        session.delete(delivery)
    session.flush()
    session.delete(endpoint)
    session.commit()
    _audit(
        session, "operator", operator.email, "webhook.delete",
        target=f"webhook:{endpoint_id}", client_id=operator.client_id,
    )
    return {"ok": True}


@app.post("/webhooks/{endpoint_id}/test")
def test_webhook(
    endpoint_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Queue a real (signed) delivery and send it immediately, reporting the actual outcome —
    no optimistic 'inviato' when the endpoint refused it."""
    endpoint = session.get(WebhookEndpoint, endpoint_id)
    if not endpoint or endpoint.client_id != operator.client_id:
        raise HTTPException(404, "webhook not found")
    now = datetime.utcnow()
    delivery = WebhookDelivery(
        client_id=operator.client_id,
        endpoint_id=endpoint.id,
        event="conversation.created",
        payload=json.dumps({
            "event": "conversation.created",
            "created_at": _iso(now),
            "test": True,
            "data": {"conversation_id": 0, "visitor_id": "test"},
        }),
        max_attempts=1,
        next_attempt_at=now,
    )
    session.add(delivery)
    session.commit()
    session.refresh(delivery)
    ok = webhooks.deliver(session, delivery)
    return {
        "ok": ok,
        "delivery_id": delivery.id,
        "response_status": delivery.response_status,
        "error": delivery.error,
    }


@app.get("/webhooks/{endpoint_id}/deliveries")
def list_webhook_deliveries(
    endpoint_id: int,
    limit: int = 50,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    endpoint = session.get(WebhookEndpoint, endpoint_id)
    if not endpoint or endpoint.client_id != operator.client_id:
        raise HTTPException(404, "webhook not found")
    rows = session.exec(
        select(WebhookDelivery)
        .where(WebhookDelivery.endpoint_id == endpoint.id)
        .order_by(WebhookDelivery.id.desc())
        .limit(_bounded_limit(limit, default=50))
    ).all()
    return [
        {
            "id": row.id,
            "event": row.event,
            "status": row.status,
            "attempts": row.attempts,
            "response_status": row.response_status,
            "error": row.error,
            "created_at": _iso(row.created_at),
            "delivered_at": _iso(row.delivered_at),
            "next_attempt_at": _iso(row.next_attempt_at) if row.status == "pending" else None,
        }
        for row in rows
    ]


@app.post("/webhooks/{endpoint_id}/deliveries/{delivery_id}/replay")
def replay_webhook_delivery(
    endpoint_id: int,
    delivery_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Create a new signed attempt from a failed delivery, preserving the original audit log."""
    endpoint = session.get(WebhookEndpoint, endpoint_id)
    if not endpoint or endpoint.client_id != operator.client_id:
        raise HTTPException(404, "webhook not found")
    original = session.get(WebhookDelivery, delivery_id)
    if (
        not original
        or original.endpoint_id != endpoint.id
        or original.client_id != operator.client_id
    ):
        raise HTTPException(404, "delivery not found")
    if original.status != "failed":
        raise HTTPException(409, "solo una consegna fallita può essere riprovata")
    if not endpoint.active:
        raise HTTPException(409, "riattiva il webhook prima di riprovare")
    replay = WebhookDelivery(
        client_id=operator.client_id,
        endpoint_id=endpoint.id,
        event=original.event,
        payload=original.payload,
        max_attempts=webhooks.MAX_ATTEMPTS,
        next_attempt_at=datetime.utcnow(),
    )
    session.add(replay)
    session.commit()
    session.refresh(replay)
    ok = webhooks.deliver(session, replay)
    _audit(
        session, "operator", operator.email, "webhook.delivery_replay",
        target=f"webhook-delivery:{replay.id}", client_id=operator.client_id,
        detail={"original_delivery_id": original.id, "ok": ok},
    )
    return {
        "ok": ok,
        "delivery_id": replay.id,
        "original_delivery_id": original.id,
        "status": replay.status,
        "response_status": replay.response_status,
        "error": replay.error,
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
    breached = _count(_sla_breached_clause(now))
    at_risk = _count(~_sla_breached_clause(now), _sla_warning_clause(now))
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


def _csat_summary(session: Session, client_id: int | None, since: datetime | None = None) -> dict:
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


def _language_stats(session: Session, client_id: int | None) -> dict:
    """How many conversations in each language — the signal that says whether translating the
    knowledge base is worth it."""
    q = select(Conversation.language, func.count()).group_by(Conversation.language)
    if client_id is not None:
        q = q.where(Conversation.client_id == client_id)
    return {code: int(n) for code, n in session.exec(q).all() if code}


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
        "sla": _sla_stats(session, client_id),
        "tags": _tag_stats(session, client_id),
        "classification": _classification_stats(session, client_id),
        "csat": _csat_summary(session, client_id),
        "languages": _language_stats(session, client_id),
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


@app.get("/csat")
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
        "production_config": {
            "strict": os.getenv("STRICT_PRODUCTION_CONFIG", "false").lower() == "true",
            "warnings": production_warnings(os.environ),
        },
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
    monthly_message_limit: int = Body(0),
    yearly_price_cents: int = Body(0),
    stripe_price_id: str = Body(""),
    stripe_yearly_price_id: str = Body(""),
    session: Session = Depends(get_session),
):
    if session.exec(select(Plan).where(Plan.name == name)).first():
        raise HTTPException(409, "a plan with this name already exists")
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


@app.post("/admin/plans/{plan_id}", dependencies=[Depends(require_admin)])
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
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


# ---- Billing (Stripe) ----


def _stripe_price_for_interval(plan: Plan, billing_interval: str) -> str:
    if billing_interval == "month":
        return plan.stripe_price_id
    if billing_interval == "year":
        return plan.stripe_yearly_price_id
    raise HTTPException(400, "billing_interval must be 'month' or 'year'")


@app.post("/billing/checkout")
def billing_checkout(
    plan_id: int = Body(..., embed=True),
    billing_interval: str = Body("month", embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Start a Stripe Checkout session for the operator's client to subscribe to `plan_id`.
    Returns the hosted checkout URL to redirect the browser to."""
    if not billing.enabled():
        raise HTTPException(503, "billing not configured")
    plan = session.get(Plan, plan_id)
    if not plan:
        raise HTTPException(404, "plan not found")
    stripe_price_id = _stripe_price_for_interval(plan, billing_interval)
    if not stripe_price_id:
        raise HTTPException(400, f"plan has no {billing_interval}ly Stripe price")
    client = session.get(Client, operator.client_id)

    params = {
        "mode": "subscription",
        "line_items": [{"price": stripe_price_id, "quantity": 1}],
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
            "yearly_price_cents": p.yearly_price_cents, "currency": p.currency,
            "purchasable": bool(p.stripe_price_id),
            "yearly_purchasable": bool(p.stripe_yearly_price_id),
        }
        for p in session.exec(select(Plan).order_by(Plan.price_cents, Plan.id)).all()
    ]


@app.get("/public/plans")
def public_plans(session: Session = Depends(get_session)):
    """Purchasable plans for the public signup page (no auth). Free/priceless plans are hidden."""
    return [
        {
            "id": p.id, "name": p.name, "price_cents": p.price_cents,
            "yearly_price_cents": p.yearly_price_cents, "currency": p.currency,
        }
        for p in session.exec(select(Plan).order_by(Plan.price_cents, Plan.id)).all()
        if p.stripe_price_id
    ]


@app.post("/signup")
def signup(
    request: Request,
    company_name: str = Body(...),
    email: str = Body(...),
    password: str = Body(...),
    plan_id: int = Body(...),
    billing_interval: str = Body("month"),
    session: Session = Depends(get_session),
):
    """Self-serve registration: create the account (on the Free plan, 'incomplete' until paid)
    and start a Stripe Checkout subscription with a free trial + card capture. The chosen plan is
    applied by the webhook once checkout completes. Returns the hosted checkout URL."""
    _rate_limit_auth(request, "signup", email)
    if not billing.enabled():
        raise HTTPException(503, "billing not configured")
    plan = session.get(Plan, plan_id)
    if not plan:
        raise HTTPException(400, "invalid plan")
    stripe_price_id = _stripe_price_for_interval(plan, billing_interval)
    if not stripe_price_id:
        raise HTTPException(400, f"plan has no {billing_interval}ly Stripe price")

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
        line_items=[{"price": stripe_price_id, "quantity": 1}],
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
        "name": operator.name,
        "client_name": client.name,
        "api_key": client.api_key,
        "plan_id": client.plan_id,
        "plan_name": plan.name if plan else None,
        "billing_status": client.billing_status,
    }


@app.get("/push/config")
def push_config(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(PushSubscription).where(PushSubscription.operator_id == operator.id)
    ).all()
    first = rows[0] if rows else None
    return {
        "configured": push_service.configured(),
        "public_key": push_service.VAPID_PUBLIC_KEY if push_service.configured() else "",
        "subscriptions": len(rows),
        "preferences": {
            "escalations": first.escalations if first else True,
            "assignments": first.assignments if first else True,
            "mentions": first.mentions if first else True,
            "sla_breaches": first.sla_breaches if first else True,
        },
    }


@app.post("/push/subscriptions")
def save_push_subscription(
    endpoint: str = Body(...),
    keys: dict = Body(...),
    preferences: dict = Body(default={}),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    clean_endpoint = (endpoint or "").strip()[:2000]
    p256dh = str(keys.get("p256dh", "")).strip()[:500]
    auth = str(keys.get("auth", "")).strip()[:500]
    if not clean_endpoint.startswith("https://") or not p256dh or not auth:
        raise HTTPException(400, "invalid push subscription")
    row = session.exec(select(PushSubscription).where(PushSubscription.endpoint == clean_endpoint)).first()
    if row is not None and (row.client_id != operator.client_id or row.operator_id != operator.id):
        raise HTTPException(409, "push subscription already belongs to another operator")
    if row is None:
        row = PushSubscription(
            client_id=operator.client_id, operator_id=operator.id,
            endpoint=clean_endpoint, p256dh=p256dh, auth=auth,
        )
    row.client_id = operator.client_id
    row.operator_id = operator.id
    row.p256dh = p256dh
    row.auth = auth
    for field in ("escalations", "assignments", "mentions", "sla_breaches"):
        if field in preferences:
            setattr(row, field, bool(preferences[field]))
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    return {"ok": True}


@app.patch("/push/preferences")
def update_push_preferences(
    preferences: dict = Body(..., embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    rows = session.exec(select(PushSubscription).where(PushSubscription.operator_id == operator.id)).all()
    for row in rows:
        for field in ("escalations", "assignments", "mentions", "sla_breaches"):
            if field in preferences:
                setattr(row, field, bool(preferences[field]))
        row.updated_at = datetime.utcnow()
        session.add(row)
    session.commit()
    return {"ok": True}


@app.delete("/push/subscriptions")
def delete_push_subscription(
    endpoint: str = Body(..., embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    row = session.exec(
        select(PushSubscription).where(
            PushSubscription.operator_id == operator.id,
            PushSubscription.endpoint == (endpoint or "").strip(),
        )
    ).first()
    if row:
        session.delete(row)
        session.commit()
    return {"ok": True}


@app.get("/onboarding/status")
def onboarding_status(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """Self-service activation checklist derived from real tenant data, never client flags."""
    client = session.get(Client, operator.client_id)
    knowledge_count = session.exec(
        select(func.count()).select_from(Chunk).where(Chunk.client_id == operator.client_id)
    ).one()
    product_count = session.exec(
        select(func.count()).select_from(Product).where(Product.client_id == operator.client_id)
    ).one()
    conversation_count = session.exec(
        select(func.count()).select_from(Conversation).where(Conversation.client_id == operator.client_id)
    ).one()
    steps = [
        {"key": "account", "label": "Account creato", "complete": True},
        {
            "key": "billing",
            "label": "Piano attivo",
            "complete": client.billing_status in ("active", "trialing"),
        },
        {
            "key": "origin",
            "label": "Sito WordPress collegato",
            "complete": bool(client.allowed_origins.strip()),
        },
        {
            "key": "knowledge",
            "label": "Prima sincronizzazione completata",
            "complete": int(knowledge_count) + int(product_count) > 0,
        },
        {
            "key": "chat",
            "label": "Prima conversazione verificata",
            "complete": int(conversation_count) > 0,
        },
    ]
    completed = sum(step["complete"] for step in steps)
    return {
        "complete": completed == len(steps),
        "completed_steps": completed,
        "total_steps": len(steps),
        "steps": steps,
    }


@app.post("/me/name")
def set_my_name(name: str = Body(..., embed=True), operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """Operator sets their own display name (shown to visitors in the typing indicator)."""
    operator.name = name.strip()[:80]
    session.add(operator)
    session.commit()
    return {"ok": True, "name": operator.name}


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
def verify_email(
    request: Request,
    token: str = Body(..., embed=True),
    session: Session = Depends(get_session),
):
    """Confirm an operator's email from the link sent at signup. Idempotent-ish: a used or
    expired token 400s, but an already-verified operator re-clicking simply succeeds again
    only while the token is fresh — after that they can just log in."""
    _rate_limit_auth(request, "verify")
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
def resend_verification(
    request: Request,
    email: str = Body(..., embed=True),
    session: Session = Depends(get_session),
):
    """Re-send the verification email. Like /auth/forgot, always returns ok to avoid leaking
    which emails are registered; only actually sends for an existing, still-unverified account."""
    _rate_limit_auth(request, "resend", email)
    operator = session.exec(select(Operator).where(Operator.email == email)).first()
    if operator and not operator.email_verified:
        token = _issue_token(session, operator.id, "verify_email", VERIFY_TOKEN_TTL)
        email_service.send_verification(operator.email, token)
    return {"ok": True}


@app.post("/auth/forgot")
def forgot_password(
    request: Request,
    email: str = Body(..., embed=True),
    session: Session = Depends(get_session),
):
    """Start a password reset. Always returns ok (no user enumeration); when the email maps
    to an operator, issue a single-use token and email the reset link."""
    _rate_limit_auth(request, "forgot", email)
    operator = session.exec(select(Operator).where(Operator.email == email)).first()
    if operator:
        token = _issue_token(session, operator.id, "reset", RESET_TOKEN_TTL)
        email_service.send_password_reset(operator.email, token)
        log(logger, logging.INFO, "auth.reset_requested", operator_id=operator.id)
    return {"ok": True}


@app.post("/auth/reset")
def reset_password(
    request: Request,
    token: str = Body(...),
    new_password: str = Body(...),
    session: Session = Depends(get_session),
):
    """Complete a password reset. Consumes the token, sets the new password, and revokes all
    of the operator's active sessions so a leaked/old login can't survive the reset."""
    _rate_limit_auth(request, "reset")
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
def operator_login(
    request: Request,
    email: str = Body(...),
    password: str = Body(...),
    session: Session = Depends(get_session),
):
    _rate_limit_auth(request, "login", email)
    operator = session.exec(select(Operator).where(Operator.email == email)).first()
    if not operator or not verify_password(password, operator.password_hash):
        raise HTTPException(401, "invalid credentials")
    if not operator.email_verified:
        # signup created the account but the mailbox was never confirmed; the panel maps this
        # 403 to a "verify your email / resend" prompt
        raise HTTPException(403, "email not verified")
    if password_needs_rehash(operator.password_hash):
        operator.password_hash = hash_password(password)
        session.add(operator)
        session.commit()
    token = secrets.token_urlsafe(32)
    session.add(OperatorSession(
        operator_id=operator.id,
        client_id=operator.client_id,
        token_hash=_hash_session_token(token),
        expires_at=datetime.utcnow() + OPERATOR_SESSION_TTL,
    ))
    session.commit()
    return {"token": token, "client_id": operator.client_id, "email": operator.email}


@app.post("/operator/logout")
def operator_logout(authorization: str = Header(None), operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    op_session = _get_operator_session(session, _bearer_token(authorization))
    if op_session:
        session.delete(op_session)
        session.commit()
    return {"ok": True}

import hashlib
import json
import hmac
import ipaddress
import logging
import math
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
from .routers import (
    automations, channels, commercial, developers, helpdesk_config, inbox, insights, public_api, widget,
)
from .util import (
    bounded_limit as _bounded_limit, iso as _iso,
    normalize_origins as _normalize_origins, slugify as _slugify, split_origins as _split_origins,
)
from .analytics import (
    build_stats as _build_stats,
    csat_summary as _csat_summary,
    sla_breached_clause as _sla_breached_clause,
    sla_warning_clause as _sla_warning_clause,
)
from .worker import enqueue as _enqueue
from .crm import CRM_PROVIDERS
from .helpdesk import HELPDESK_PROVIDERS, export_payload as _helpdesk_export_payload
from .routing import (
    ROUTING_MODES,
    SLA_WARN_RATIO,
    require_department as _require_department,
    save_support_schedule as _save_support_schedule,
    support_schedule_payload as _support_schedule_payload,
    validated_support_schedule as _validated_support_schedule,
    apply_sla as _apply_sla,
    assignable_operators as _assignable_operators,
    auto_assign as _auto_assign,
    match_sla_policy as _match_sla_policy,
    routing_setting as _routing_setting,
)
from .leads import LEAD_FIELD_TYPES, LEAD_TRIGGERS, MAX_LEAD_FIELDS, MAX_LEAD_VALUE_CHARS, form_payload as _lead_form_payload
from .proactive import (
    MAX_PROACTIVE_MESSAGE_CHARS,
    PROACTIVE_AB_MIN_IMPRESSIONS,
    PROACTIVE_AB_Z_THRESHOLD,
    PROACTIVE_FREQUENCIES,
    PROACTIVE_TRIGGERS,
    ab_result as _proactive_ab_result,
    rule_payload as _proactive_payload,
)
from .limits import MAX_CHAT_MESSAGE_CHARS, MAX_INGEST_TEXT_CHARS, MAX_UPLOAD_BYTES
from .conversations import (
    PRIORITIES,
    erase_conversation as _erase_conversation,
    require_conversation_token as _require_conversation_token,
    operator_name as _operator_name,
    emit_visitor_message as _emit_visitor_message,
    get_or_create_contact as _get_or_create_contact,
    SLA_STATES,
    notify_visitor_reply as _notify_visitor_reply,
    rating_payload as _rating_payload,
    sla_view as _sla_view,
    target_state as _target_state,
    require_conversation as _require_conversation,
    whatsapp_channel_status as _whatsapp_channel_status,
)
from .apikeys import API_SCOPES, generate as _generate_api_key, scopes_of as _api_key_scopes
from .deps import (
    chat_limiter,
    ingest_limiter,
    plan_limit as _plan_limit,
    rate_limit_chat,
    rate_limit_ingest,
    hash_api_key as _hash_api_key,
    ADMIN_API_KEY,
    audit as _audit,
    bearer_token as _bearer_token,
    get_client,
    get_operator_session as _get_operator_session,
    hash_conversation_token as _hash_conversation_token,
    hash_session_token as _hash_session_token,
    require_admin,
    require_channel_write_key,
    require_client,
    require_operator,
    resolve_client_id,
)
from . import costs as costs_service
from . import growth

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
    KnowledgeDraft,
    Lead,
    LeadForm,
    Message,
    ModelPrice,
    NoteMention,
    Operator,
    OperatorSession,
    Plan,
    PluginInstallation,
    ProactiveRule,
    ProactiveExperiment,
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
    WorkflowScheduledAction,
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


# Routers by area. main.py still holds the rest; areas move out one at a time (see
# docs/handoff.md). Paths and methods are unchanged by the move — test_routes.py proves it.
app.include_router(commercial.router)
app.include_router(developers.router)
app.include_router(public_api.router)
app.include_router(channels.router)
app.include_router(insights.router)
app.include_router(automations.router)
app.include_router(helpdesk_config.router)
app.include_router(inbox.router)
app.include_router(widget.router)


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

# TTLs for single-use email tokens (app/email.py sends the links)
RESET_TOKEN_TTL = timedelta(hours=int(os.getenv("RESET_TOKEN_TTL_HOURS", "1")))
VERIFY_TOKEN_TTL = timedelta(hours=int(os.getenv("VERIFY_TOKEN_TTL_HOURS", "48")))
OPERATOR_SESSION_TTL = timedelta(hours=int(os.getenv("OPERATOR_SESSION_TTL_HOURS", str(24 * 30))))

# /chat hits the LLM on every call, so it's the main abuse/cost surface — limit per client+IP.
# Ingest is limited per client. Windows are 60s; override the counts via env.
auth_limiter = make_limiter(int(os.getenv("AUTH_RATE_LIMIT", "10")), 60)


def _rate_limit_auth(request: Request, scope: str, identity: str = "") -> None:
    ip = request.client.host if request.client else "unknown"
    identity_digest = hashlib.sha256(identity.strip().lower().encode()).hexdigest()[:16]
    auth_limiter.check(f"auth:{scope}:{ip}:{identity_digest}")

# ponytail: deterministic safety net for categories that must always reach a human —
# small local LLMs don't reliably follow "always escalate refunds" instructions
# A substantive question must have at least one reasonably close knowledge-base result.
# This is stricter than the retrieval cutoff so loose context cannot enable general chat.
# ponytail: same deterministic-safety-net pattern as ALWAYS_ESCALATE_KEYWORDS — the small model
# doesn't reliably combine "order number" (turn 1) and "identifier" (turn 2) into a single
# ORDER_LOOKUP marker across turns, and answering an order question straight from the LLM risks
# hallucinated order data. Scan the *whole* conversation (not just the latest message) so the
# two slots can land in different turns, same as a human support agent would track them.
# a bare identifier turn (e.g. "Prova Prova" answering "what's your surname?") — short, no
# digits, no obvious question — not a strict name validator, just "doesn't look like something
# else". Reused for the last user message, not run against normal free-text messages.
# ---- Dynamic CORS ----
# CORS preflight (OPTIONS) doesn't carry the api_key, so it can't be scoped per-client at the
# CORS layer. Instead we reflect an Origin only if it's in a dynamic allowlist (panel origins +
# every client's configured widget origins). The enforceable per-client key<->site binding lives
# in rate_limit_chat, which can see the api_key. CORS_ALLOW_ALL keeps the permissive default
# until origins are configured; set it false to enforce the allowlist strictly.
CORS_ALLOW_ALL = os.getenv("CORS_ALLOW_ALL", "true").lower() == "true"
PANEL_ORIGINS = [o.strip() for o in os.getenv("PANEL_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
_ALLOWED_ORIGINS: set[str] = set(PANEL_ORIGINS)


def rebuild_allowed_origins(session: Session) -> None:
    """Recompute the browser-layer allowlist: panel origins + every client's widget origins."""
    origins = set(PANEL_ORIGINS)
    for c in session.exec(select(Client)).all():
        origins.update(_split_origins(c.allowed_origins))
    global _ALLOWED_ORIGINS
    _ALLOWED_ORIGINS = origins


def _cors_headers(origin: str) -> dict:
    # Every method the app actually routes must be listed, or the browser blocks the request
    # before it is ever sent: the panel updates settings with PUT and removes rows with DELETE,
    # and omitting them made 36 routes unreachable cross-origin while the server looked healthy.
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
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


# transient "operator is typing" state: {conversation_id: (operator_name, monotonic_ts)}.
# In-memory (ephemeral, fine to lose on restart). ponytail: per-process — with multiple workers a
# typing ping and the widget's poll can land on different workers; back with Redis if we scale out.
# ---- SLA & routing ----------------------------------------------------------------------
#
# The SLA clock starts when a conversation actually needs a human (escalation): the AI answers
# in seconds, so a "first response" target on every conversation would measure nothing. From
# that moment two targets run — first operator reply and resolution (close) — each with a
# deadline and a warning threshold, so the inbox can show ok / in scadenza / violato.

# share of the window after which a still-pending target is flagged "in scadenza"
SLA_WARN_RATIO = min(max(float(os.getenv("SLA_WARN_RATIO", "0.8")), 0.0), 1.0)
SLA_CHECK_INTERVAL_SECONDS = int(os.getenv("SLA_CHECK_INTERVAL_SECONDS", "300"))
SLA_MONITOR_ENABLED = os.getenv("SLA_MONITOR_ENABLED", "true").lower() == "true"
WEBHOOK_DISPATCHER_ENABLED = os.getenv("WEBHOOK_DISPATCHER_ENABLED", "true").lower() == "true"


# ---- Tags & AI classification -----------------------------------------------------------


# ---- Collaboration: internal notes, mentions, presence ----------------------------------

# how long an operator counts as "on this conversation" after their last heartbeat
# {conversation_id: {operator_id: (name, last_seen_monotonic, composing)}}
# In-memory like the typing indicator: presence is a live hint, not data worth persisting.
# With several uvicorn workers each process sees its own heartbeats, so collision detection is
# best-effort — it warns, it never blocks a reply.
# conversations tracked at once before a full sweep runs; presence entries are tiny, this only
# stops the dict from growing forever in a long-running process
# ---- Inbox ordering & saved views ----

# how urgent each priority is when sorting (higher = shown first)
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


# ---- SLA policies + routing settings (per client) ----


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


# ---- Lead capture ------------------------------------------------------------------------

# ---- Proactive messages ------------------------------------------------------------------
#
# The rules are evaluated in the widget, so the public endpoint returns exactly what the
# browser needs to decide — nothing more. Frequency capping and the visitor's opt-out live in
# the browser too: they are a courtesy to that person, not a server-side quota.

# ---- Workflows (no-code automations) -----------------------------------------------------


# ---- Public API: scoped keys ------------------------------------------------------------
#
# Distinct from the widget `Client.api_key`, which is embedded in a public page and only
# identifies the tenant. These keys are server-side credentials: scoped, revocable, stored as
# a digest, and rate-limited on their own bucket.

# don't write last_used_at on every call: one update per minute per key is enough to answer
# "is this key still in use?" without a write on the hot path


# ---- Public API v1 -----------------------------------------------------------------------
#
# Versioned on purpose: /v1 is a contract with third-party integrations, so its shapes change
# only by adding fields. The panel keeps using the unversioned operator endpoints.


# ---- Webhooks (tenant-managed, signed) ---------------------------------------------------


# ---- Analytics helpers (shared by operator /stats and admin /admin/stats) ----


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
    stripe_price_id = billing.price_for_interval(plan, billing_interval)
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

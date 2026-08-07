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
from . import cors
from .billing import default_plan_id as _default_plan_id
from .routers import (
    automations, channels, commercial, developers, accounts, admin, helpdesk_config, inbox, insights, knowledge, public_api, widget,
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
        cors.rebuild_allowed_origins(session)
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
app.include_router(knowledge.router)
app.include_router(accounts.router)
app.include_router(admin.router)


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
# /chat hits the LLM on every call, so it's the main abuse/cost surface — limit per client+IP.
# Ingest is limited per client. Windows are 60s; override the counts via env.
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
@app.middleware("http")
async def dynamic_cors(request: Request, call_next):
    origin = request.headers.get("origin")
    allowed = cors.is_allowed(origin)
    # answer preflight before routing (routes don't declare OPTIONS handlers)
    if request.method == "OPTIONS" and origin and request.headers.get("access-control-request-method"):
        return Response(status_code=204 if allowed else 403, headers=cors.headers(origin) if allowed else {})
    response = await call_next(request)
    if allowed:
        response.headers.update(cors.headers(origin))
    return response


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


# ---- Admin: client onboarding (guarded by ADMIN_API_KEY) ----


# ---- Billing (Stripe) ----


# ---- Operator self-service (own account + own client's widget key) ----


# ---- Auth: email verification + password reset ----


# ---- Operator auth (panel login) ----


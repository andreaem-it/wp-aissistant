"""The visitor surface: the chat widget itself.

Where a visitor talks to the assistant — retrieval, the grounded answer, streaming, escalation
to a human, the WooCommerce cart and the verified order lookup — plus the lead forms and
proactive messages the widget renders, and the plugin installation that authorises a site.

Two rules hold this area together. The assistant answers **only from retrieved context**, and
when it cannot it escalates rather than inventing. And anything the visitor can reach is treated
as public: no internal state, no scoring weights, no keys ever cross into a response here.

Ninth area extracted from main.py — see `docs/handoff.md` for the pattern.
"""
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta

from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlmodel import Session, select

from ..billing import service_suspended as _service_suspended
from .. import cors, events, language, i18n, metrics, origins, push as push_service, tagging, webhooks
from .. import email as email_service
from ..conversations import (
    emit_visitor_message as _emit_visitor_message,
    get_or_create_contact as _get_or_create_contact,
    operator_name as _operator_name,
    require_conversation as _require_conversation,
    require_conversation_token as _require_conversation_token,
)
from ..db import (
    AiResponseLog, Client, Contact, Conversation, ConversationRating, InfoField, Lead, LeadForm,
    Message, Operator, Plan, PluginInstallation, ProactiveExperiment, ProactiveRule, SupportSchedule,
    Ticket, engine, get_session,
)
from ..deps import (
    audit as _audit, get_client, hash_conversation_token as _hash_conversation_token,
    bearer_token as _bearer_token, plugin_secret_hash as _plugin_secret_hash,
    require_plugin_installation as _require_plugin_installation, rate_limit_chat, rate_limit_ingest, require_client,
    require_operator, resolve_client_id,
)
from ..leads import LEAD_TRIGGERS, MAX_LEAD_VALUE_CHARS, form_payload as _lead_form_payload
from ..limits import MAX_CHAT_MESSAGE_CHARS
from ..llm import (
    ESCALATE_PREFIX, LLMUnavailableError, ORDER_LOOKUP_RE, chat as llm_chat,
    chat_stream as llm_chat_stream,
)
from ..logging_config import log
from ..notify import notify_new_ticket
from ..worker import enqueue as _enqueue
from ..proactive import PROACTIVE_AB_MIN_IMPRESSIONS, rule_payload as _proactive_payload
from ..rag import (
    SCOPE_MAX_DISTANCE, build_system as _build_system, is_small_talk as _is_small_talk,
    retrieval_is_in_scope as _retrieval_is_in_scope, retrieve, retrieve_products, retrieve_with_meta,
)
from ..routing import (
    apply_sla as _apply_sla, auto_assign as _auto_assign,
    save_support_schedule as _save_support_schedule,
    support_schedule_payload as _support_schedule_payload,
)
from ..util import iso as _iso, normalize_origins as _normalize_origins, split_origins as _split_origins

logger = logging.getLogger("wpai")

router = APIRouter()


ALWAYS_ESCALATE_KEYWORDS = [
    "rimborso", "refund", "reclamo", "complaint", "denuncia",
    "cambio password account", "eliminare il mio account", "delete my account",
]


_ORDER_NUMBER_RE = re.compile(r"ordine\D{0,15}(\d{2,})|order\D{0,15}#?\s*(\d{2,})|#(\d{2,})", re.I)


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


_ASKED_IDENTIFIER_RE = re.compile(r"cognome|email|e-mail", re.I)


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


def _matching_products(session, client_id: int, message: str) -> list[dict]:
    """I prodotti a catalogo che corrispondono alla domanda, o nessuno.

    Recuperati **prima** del guardiano di scope, per due motivi. Il primo è che un prodotto che
    corrisponde è di per sé la prova che la domanda riguarda questo negozio: il guardiano legge
    solo i chunk di testo, quindi «avete la felpa con zip?» finiva fuori ambito se le schede
    prodotto non erano anche indicizzate come pagine — e quel percorso risponde senza card. La
    soglia dei prodotti (0.45) è più severa di quella di scope (0.62), quindi ammettere una
    corrispondenza di catalogo non allarga la porta, la apre dove era chiusa per omissione.

    Il secondo è che il recupero avveniva comunque, solo dopo la risposta: spostarlo qui non
    aggiunge una chiamata di embedding, la anticipa.

    Se il fornitore di embedding è irraggiungibile non c'è motivo di perdere la risposta: si
    resta senza card.
    """
    try:
        return retrieve_products(session, client_id, message)
    except LLMUnavailableError:
        return []


def _out_of_scope_reply(language: str | None = None) -> str:
    return i18n.t("scope.out_of_scope", language)


def _trusted_callback_origin(allowed_origins: list[str], site_url, request, *,
                             bootstrap: bool = False) -> str:
    """The origin to call back for an order lookup — ONLY if it's one of the tenant's registered
    domains. `site_url` is an attacker-controllable body param, so validating the chosen origin
    against the allowlist prevents SSRF (a spoofed site_url making the backend POST to an
    arbitrary/internal URL). Returns "" when nothing trusted matches (order lookup then fails
    gracefully instead of hitting an untrusted host).

    `bootstrap` accetta un candidato che non è ancora registrato, e serve al **solo** flusso di
    registrazione del plugin: là la fiducia non viene dall'elenco ma dal challenge HMAC, che
    prova il possesso del sito. Le protezioni SSRF restano tutte — indirizzi non pubblici
    rifiutati qui, `webhooks.validate_url` e la risoluzione DNS controllata a valle."""
    allowed = set(allowed_origins)
    if not allowed and not bootstrap:
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
        if not norm:
            continue
        if norm in allowed:
            return norm
        if bootstrap and norm.startswith("https://"):
            # Solo HTTPS: un sito in chiaro non è un posto dove mandare la richiesta di un ordine.
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
    # the subscription period is mirrored into the row by the Stripe webhook (app/billing.py):
    # this endpoint is polled by the WordPress plugin, so it must never call Stripe inline.
    period_end = client.subscription_period_end if client else None
    return {
        "plan": plan.name if plan else None,
        "billing_status": client.billing_status if client else "",
        "subscription_expires_at": period_end.isoformat() + "Z" if period_end else None,
        "cancel_at_period_end": bool(client.subscription_cancel_at_period_end) if client else False,
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
    visitor_message = Message(conversation_id=conv.id, role="user", content=message)
    session.add(visitor_message)
    # Re-detected every turn: a visitor can switch language mid-conversation, and the browser
    # locale is only a hint — what they actually type wins when it says something.
    conv.language = language.detect(message, hint=locale, default=conv.language or language.DEFAULT)
    conv.updated_at = datetime.utcnow()
    if conv.status == "closed":
        conv.status = "open"
        conv.closed_at = None
    session.add(conv)
    session.commit()
    session.refresh(visitor_message)
    _emit_visitor_message(session, conv, visitor_message)
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
    if _service_suspended(session.get(Client, client_id)):
        return "suspended"
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


@router.post("/chat/stream")
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
            # abbonamento assente o disdetto: l'assistente non risponde. Stato distinto dalla
            # quota perché il visitatore non c'entra e il rimedio è del titolare del sito.
            if early_action == "suspended":
                yield _sse({"type": "suspended", "conversation_id": conv.id})
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
                origin = _trusted_callback_origin(origins.registered(session, client.id), site_url, request)
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
                products = _matching_products(s, client_id, message)
                if not _is_small_talk(message) and not products and not _retrieval_is_in_scope(retrieval_meta):
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
                system = _build_system(context, conv.language, client.name)
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
                origin = _trusted_callback_origin(origins.registered(session, client.id), site_url, request)
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
            yield _sse({"type": "done", "conversation_id": conv.id, "message_id": reply_msg.id, "products": products})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat")
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
    if early_action == "suspended":
        return {"conversation_id": conv.id, "conversation_token": access_token, "status": "suspended", "reply": None}
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
        origin = _trusted_callback_origin(origins.registered(session, client.id), site_url, request)
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
        products = _matching_products(session, client.id, message)
        if not _is_small_talk(message) and not products and not _retrieval_is_in_scope(retrieval_meta):
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
        system = _build_system(context, conv.language, client.name)
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
        origin = _trusted_callback_origin(origins.registered(session, client.id), site_url, request)
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
    return {"conversation_id": conv.id, "conversation_token": access_token, "status": "open", "reply": result["reply"], "products": products, "message_id": reply_msg.id}


@router.post("/chat/feedback")
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


@router.post("/chat/contact")
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


@router.post("/chat/ticket")
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


@router.post("/chat/rating")
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


@router.get("/usage")
def usage(client_id: int = Depends(resolve_client_id), session: Session = Depends(get_session)):
    """Current month's chat-message usage vs the plan quota. Dual auth: the WP plugin (client
    api_key) and the panel (operator token) both read it. remaining=null means unlimited."""
    return _usage(session, client_id)


@router.get("/team/operators")
def list_team_operators(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(Operator).where(Operator.client_id == operator.client_id).order_by(Operator.name, Operator.email)
    ).all()
    return [{"id": row.id, "name": _operator_name(row), "email": row.email} for row in rows]


def _trusted_plugin_proof_url(allowed_origins: list[str], value: str) -> str:
    """Accept a WordPress REST proof URL only on one of the tenant's registered origins.

    In bootstrap l'elenco è il solo dominio candidato, non l'insieme vuoto: la prova deve stare
    **sullo stesso sito** che si sta registrando, altrimenti il challenge dimostrerebbe il
    possesso di un server diverso da quello che finisce nella licenza."""
    from urllib.parse import urlparse

    try:
        clean = webhooks.validate_url(str(value or "").strip())
    except ValueError:
        return ""
    parsed = urlparse(clean)
    if parsed.username or parsed.password:
        return ""
    if _normalize_origins(clean) not in set(allowed_origins):
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


@router.post("/plugin/register")
def register_plugin_installation(
    request: Request,
    body: dict = Body(...),
    client: Client = Depends(rate_limit_ingest),
    session: Session = Depends(get_session),
):
    secret = str(body.get("secret", ""))
    if len(secret) < 32 or len(secret) > 256:
        raise HTTPException(400, "Credenziale plugin non valida")
    allowed = origins.registered(session, client.id)
    origin = _trusted_callback_origin(allowed, body.get("site_url"), request)
    proof_url = _trusted_plugin_proof_url(allowed, body.get("proof_url", ""))

    # Bootstrap dell'onboarding. Con la licenza legata al dominio un cliente nuovo non ha ancora
    # registrato niente, e senza questo ramo l'installazione del plugin — cioè il primo passo di
    # ogni cliente WordPress — sarebbe impossibile senza un intervento del superadmin.
    #
    # Ci si può fidare perché la fiducia non viene dall'elenco ma dal **challenge**: il backend
    # genera un nonce e pretende `HMAC(secret, nonce)` da una rotta di quel sito. Rispondere
    # richiede di controllare il server di quel dominio, che è una prova più forte di un campo
    # compilato in un form. Vale solo con uno slot libero: a slot pieno il dominio non viene
    # sostituito di nascosto, si dice al cliente di cambiarlo dal pannello.
    bootstrap = False
    if (not origin or not proof_url) and not allowed and origins.slots(session, client)["live_available"] != 0:
        candidate = _trusted_callback_origin([], body.get("site_url"), request, bootstrap=True)
        candidate_proof = _trusted_plugin_proof_url([candidate] if candidate else [],
                                                    body.get("proof_url", ""))
        if candidate and candidate_proof:
            origin, proof_url, bootstrap = candidate, candidate_proof, True

    if not origin or not proof_url:
        raise HTTPException(403, "Sito WordPress non presente nelle origini autorizzate")
    if not _verify_plugin_site(proof_url, secret):
        raise HTTPException(422, "Verifica del sito WordPress non riuscita")
    if bootstrap:
        try:
            origins.register(session, client, origin, "live", source="plugin",
                             enforce_cooldown=False)
        except origins.OriginError as exc:
            raise HTTPException(409, str(exc))
        cors.rebuild_allowed_origins(session)
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


@router.put("/plugin/support-schedule")
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


@router.get("/widget/lead-form")
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


@router.post("/widget/leads")
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


@router.get("/widget/proactive")
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


@router.post("/widget/proactive/{rule_id}/event")
def widget_proactive_event(
    rule_id: int,
    kind: str = Body(..., embed=True),  # impression | engagement
    variant: str = Body("a", embed=True),
    client: Client = Depends(rate_limit_chat),
    session: Session = Depends(get_session),
):
    """Counts an impression or an engagement. Rate-limited like the chat: the counters only
    steer a business decision, but they still shouldn't be trivially inflatable."""
    if kind not in ("impression", "engagement"):
        raise HTTPException(400, "kind must be 'impression' or 'engagement'")
    if variant not in ("a", "b"):
        raise HTTPException(400, "variant must be 'a' or 'b'")
    rule = session.get(ProactiveRule, rule_id)
    if not rule or rule.client_id != client.id:
        raise HTTPException(404, "rule not found")
    if variant == "b" and not rule.message_b:
        raise HTTPException(400, "variant b is not configured")
    field = f"{kind}s" + ("_b" if variant == "b" else "")
    setattr(rule, field, getattr(rule, field) + 1)
    session.add(rule)
    session.commit()
    return {"ok": True}

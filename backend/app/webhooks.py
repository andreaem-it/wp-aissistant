"""Signed outbound webhooks.

Two halves:

- `emit()` writes one WebhookDelivery per active endpoint subscribed to the event. It never
  performs I/O, so emitting from a request path can't slow it down or fail it.
- `dispatch_pending()` sends the due deliveries and applies the retry policy. It runs in a
  background thread (see main.lifespan) and is called directly by the tests.

Every request carries `X-WPAI-Signature: t=<unix>,v1=<hex>` where the HMAC-SHA256 is computed
over `"<t>.<raw body>"` with the endpoint secret — the receiver recomputes it and compares in
constant time, and rejects a timestamp too far from now to stop replays.

SSRF: the destination is tenant-controlled, so a webhook could otherwise be pointed at the
internal network. URLs are validated on creation (scheme + literal IPs) and again at delivery
time, when the hostname is resolved and private/loopback/link-local targets are refused unless
WEBHOOK_ALLOW_PRIVATE is set (used by tests and local development).
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from sqlmodel import Session, select

from .db import WebhookDelivery, WebhookEndpoint, engine
from .logging_config import log

logger = logging.getLogger("wpai.webhooks")

# The events a tenant can subscribe to. Closed set: an unknown event in a subscription is a
# typo that would silently deliver nothing.
EVENTS = (
    "conversation.created",
    "conversation.escalated",
    "conversation.replied",
    "conversation.closed",
    "conversation.rated",
    "sla.breached",
    "lead.captured",
)

TIMEOUT_SECONDS = float(os.getenv("WEBHOOK_TIMEOUT_SECONDS", "5"))
MAX_ATTEMPTS = int(os.getenv("WEBHOOK_MAX_ATTEMPTS", "5"))
DISPATCH_INTERVAL_SECONDS = float(os.getenv("WEBHOOK_DISPATCH_INTERVAL_SECONDS", "15"))
DISPATCH_BATCH = int(os.getenv("WEBHOOK_DISPATCH_BATCH", "50"))
ALLOW_PRIVATE = os.getenv("WEBHOOK_ALLOW_PRIVATE", "false").lower() == "true"
# tolerance the receiver should apply to the signature timestamp (documented, not enforced here)
SIGNATURE_TOLERANCE_SECONDS = 300


class WebhookUrlError(ValueError):
    """The destination URL is malformed or points somewhere we refuse to call."""


def _is_private(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def validate_url(url: str) -> str:
    """Check what can be checked without a DNS lookup, so creating an endpoint never depends on
    name resolution. The resolved check happens again before each delivery."""
    clean = (url or "").strip()
    parsed = urllib.parse.urlparse(clean)
    if parsed.scheme not in ("http", "https"):
        raise WebhookUrlError("l'URL deve iniziare con http:// o https://")
    if not parsed.hostname:
        raise WebhookUrlError("URL senza host")
    if not ALLOW_PRIVATE:
        if parsed.hostname in ("localhost", "127.0.0.1", "::1") or _is_private(parsed.hostname):
            raise WebhookUrlError("indirizzi interni o locali non sono ammessi")
        if parsed.scheme != "https":
            raise WebhookUrlError("è richiesto HTTPS")
    if len(clean) > 2000:
        raise WebhookUrlError("URL troppo lungo")
    return clean


def _resolves_to_public_address(url: str) -> bool:
    if ALLOW_PRIVATE:
        return True
    host = urllib.parse.urlparse(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    return all(not _is_private(info[4][0]) for info in infos)


def new_secret() -> str:
    import secrets  # local: only needed when an endpoint is created

    return "whsec_" + secrets.token_urlsafe(32)


def sign(secret: str, timestamp: int, body: bytes) -> str:
    payload = f"{timestamp}.".encode() + body
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def subscribed(endpoint: WebhookEndpoint, event: str) -> bool:
    """An endpoint with no explicit event list receives everything."""
    wanted = [e.strip() for e in (endpoint.events or "").split(",") if e.strip()]
    return not wanted or event in wanted


def emit(session: Session, client_id: int, event: str, data: dict) -> int:
    """Queue the event for every active subscribed endpoint of the tenant. Returns how many
    deliveries were queued. Best-effort: never raises into the caller's request."""
    if event not in EVENTS:
        log(logger, logging.WARNING, "webhook.unknown_event", event=event)
        return 0
    try:
        endpoints = session.exec(
            select(WebhookEndpoint).where(
                WebhookEndpoint.client_id == client_id, WebhookEndpoint.active.is_(True)
            )
        ).all()
        targets = [e for e in endpoints if subscribed(e, event)]
        if not targets:
            return 0
        now = datetime.utcnow()
        for endpoint in targets:
            session.add(
                WebhookDelivery(
                    client_id=client_id,
                    endpoint_id=endpoint.id,
                    event=event,
                    payload=json.dumps({"event": event, "created_at": now.isoformat() + "Z", "data": data}),
                    max_attempts=MAX_ATTEMPTS,
                    next_attempt_at=now,
                )
            )
        session.commit()
        return len(targets)
    except Exception as exc:  # noqa: BLE001 — emitting must never break the action it follows
        session.rollback()
        log(logger, logging.WARNING, "webhook.emit_failed", event=event, error=str(exc)[:200])
        return 0


def _post(url: str, body: bytes, headers: dict) -> int:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return int(response.status)


def _backoff(attempts: int) -> timedelta:
    """30s, 1m, 2m, 4m… capped at an hour."""
    return timedelta(seconds=min(30 * (2 ** max(attempts - 1, 0)), 3600))


def deliver(session: Session, delivery: WebhookDelivery) -> bool:
    """Send one delivery and record the outcome. Returns True when it succeeded."""
    endpoint = session.get(WebhookEndpoint, delivery.endpoint_id)
    now = datetime.utcnow()
    delivery.attempts += 1
    delivery.updated_at = now
    if endpoint is None or not endpoint.active:
        delivery.status = "failed"
        delivery.error = "endpoint non disponibile"
        session.add(delivery)
        session.commit()
        return False

    body = delivery.payload.encode()
    timestamp = int(now.timestamp())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "wp-aissistant-webhooks/1",
        "X-WPAI-Event": delivery.event,
        "X-WPAI-Delivery": str(delivery.id),
        "X-WPAI-Signature": sign(endpoint.secret, timestamp, body),
    }
    error = ""
    status = 0
    try:
        if not _resolves_to_public_address(endpoint.url):
            raise WebhookUrlError("l'host non è raggiungibile o è un indirizzo interno")
        status = _post(endpoint.url, body, headers)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        error = f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 — any transport error is a failed attempt
        error = str(exc)[:300]

    delivery.response_status = status
    if 200 <= status < 300:
        delivery.status = "success"
        delivery.error = ""
        delivery.delivered_at = now
    elif delivery.attempts >= (delivery.max_attempts or MAX_ATTEMPTS):
        delivery.status = "failed"
        delivery.error = error or f"HTTP {status}"
    else:
        delivery.status = "pending"
        delivery.error = error or f"HTTP {status}"
        delivery.next_attempt_at = now + _backoff(delivery.attempts)
    session.add(delivery)
    session.commit()
    if delivery.status != "success":
        log(
            logger, logging.WARNING, "webhook.delivery_failed",
            delivery_id=delivery.id, client_id=delivery.client_id, event=delivery.event,
            attempts=delivery.attempts, status=delivery.status, error=delivery.error[:200],
        )
    return delivery.status == "success"


def dispatch_pending(session: Session, limit: int = DISPATCH_BATCH) -> int:
    """Send every delivery whose retry time has come. Returns how many were attempted."""
    due = session.exec(
        select(WebhookDelivery)
        .where(
            WebhookDelivery.status == "pending",
            WebhookDelivery.next_attempt_at <= datetime.utcnow(),
        )
        .order_by(WebhookDelivery.id)
        .limit(limit)
    ).all()
    for delivery in due:
        deliver(session, delivery)
    return len(due)


def run_dispatcher(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            with Session(engine) as session:
                sent = dispatch_pending(session)
                if sent:
                    log(logger, logging.INFO, "webhook.dispatched", deliveries=sent)
        except Exception as exc:  # noqa: BLE001 — never let the dispatcher die
            log(logger, logging.WARNING, "webhook.dispatcher_failed", error=str(exc)[:200])
        stop.wait(DISPATCH_INTERVAL_SECONDS)

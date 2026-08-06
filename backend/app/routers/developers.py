"""Developer surface: server-side API keys and outgoing webhooks.

What a tenant's own systems use to integrate: minting and revoking scoped keys, registering
webhook endpoints, and inspecting or replaying what was delivered.

Second area extracted from main.py — see `docs/handoff.md` for the pattern.
"""
import json
import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlmodel import Session, select

from .. import webhooks
from ..apikeys import API_SCOPES, generate as _generate_api_key, scopes_of as _api_key_scopes
from ..db import ApiKey, Operator, WebhookDelivery, WebhookEndpoint, get_session
from ..deps import audit as _audit, hash_api_key as _hash_api_key, require_operator
from ..util import bounded_limit as _bounded_limit, iso as _iso

logger = logging.getLogger("wpai")

router = APIRouter()


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


@router.get("/api-keys")
def list_api_keys(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(ApiKey).where(ApiKey.client_id == operator.client_id).order_by(ApiKey.id.desc())
    ).all()
    return [_api_key_payload(row) for row in rows]


@router.post("/api-keys")
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


@router.delete("/api-keys/{key_id}")
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


@router.get("/webhooks")
def list_webhooks(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(WebhookEndpoint).where(WebhookEndpoint.client_id == operator.client_id).order_by(WebhookEndpoint.id)
    ).all()
    return {"events": list(webhooks.EVENTS), "endpoints": [_webhook_payload(row) for row in rows]}


@router.post("/webhooks")
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


@router.patch("/webhooks/{endpoint_id}")
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


@router.delete("/webhooks/{endpoint_id}")
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


@router.post("/webhooks/{endpoint_id}/test")
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
            "schema_version": webhooks.SCHEMA_VERSION,
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


@router.get("/webhooks/{endpoint_id}/deliveries")
def list_webhook_deliveries(
    endpoint_id: int,
    limit: int = 50,
    status: str = "",
    event: str = "",
    before_id: int | None = None,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    endpoint = session.get(WebhookEndpoint, endpoint_id)
    if not endpoint or endpoint.client_id != operator.client_id:
        raise HTTPException(404, "webhook not found")
    if status and status not in {"pending", "success", "failed"}:
        raise HTTPException(400, "stato consegna non valido")
    if event and event not in webhooks.EVENTS:
        raise HTTPException(400, "evento webhook non valido")
    query = select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint.id)
    if status:
        query = query.where(WebhookDelivery.status == status)
    if event:
        query = query.where(WebhookDelivery.event == event)
    if before_id is not None:
        if before_id <= 0:
            raise HTTPException(400, "cursore consegna non valido")
        query = query.where(WebhookDelivery.id < before_id)
    rows = session.exec(
        query
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
            "payload": json.loads(row.payload),
        }
        for row in rows
    ]


@router.get("/webhooks/{endpoint_id}/stats")
def webhook_delivery_stats(
    endpoint_id: int,
    days: int = 30,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    endpoint = session.get(WebhookEndpoint, endpoint_id)
    if not endpoint or endpoint.client_id != operator.client_id:
        raise HTTPException(404, "webhook not found")
    window = max(1, min(days, 365))
    since = datetime.utcnow() - timedelta(days=window)
    rows = session.exec(select(WebhookDelivery).where(
        WebhookDelivery.endpoint_id == endpoint.id,
        WebhookDelivery.created_at >= since,
    )).all()
    counts = {"success": 0, "pending": 0, "failed": 0}
    attempts = 0
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
        attempts += row.attempts
    total = len(rows)
    success_rate = round(counts["success"] * 100 / total, 1) if total else None
    degraded = total >= 5 and (counts["failed"] >= 3 or success_rate < 95)
    return {
        "days": window,
        "total": total,
        "success": counts["success"],
        "pending": counts["pending"],
        "failed": counts["failed"],
        "success_rate": success_rate,
        "average_attempts": round(attempts / total, 2) if total else 0,
        "degraded": degraded,
        "alert": (
            "Affidabilità webhook ridotta: verifica endpoint e ultime consegne fallite."
            if degraded else ""
        ),
    }


@router.post("/webhooks/{endpoint_id}/deliveries/{delivery_id}/replay")
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

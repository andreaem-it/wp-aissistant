"""Shared FastAPI dependencies and the audit helper.

These are the pieces every area of the API needs — who is calling, on behalf of which tenant,
and how a privileged action gets recorded. They live here so a router can be moved out of
`main.py` without importing it, which would be circular.

Nothing in this module knows about any particular feature: if a helper only serves one area, it
belongs with that area, not here.
"""
import hashlib
import json
import logging
import os
import secrets
from datetime import datetime

from fastapi import Depends, Header, HTTPException, Request
from sqlmodel import Session, or_, select

from . import origins
from .db import ApiKey, AuditLog, Client, Operator, OperatorSession, Plan, PluginInstallation, get_session
from .ratelimit import make_limiter
from .util import split_origins
from .logging_config import log

logger = logging.getLogger("wpai")

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")


# ---- Token helpers ---------------------------------------------------------------------------


def bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    return authorization[7:].strip()


def hash_conversation_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---- Callers ---------------------------------------------------------------------------------


def hash_api_key(token: str) -> str:
    """Server-side API keys are stored as a digest: a leaked database must not yield the keys."""
    return hashlib.sha256(token.encode()).hexdigest()


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
    digest = hash_api_key(authorization[7:].strip())
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


def get_operator_session(session: Session, token: str) -> OperatorSession | None:
    """Resolve an active session and eagerly remove it when its absolute TTL has elapsed."""
    digest = hash_session_token(token)
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
    op_session = get_operator_session(session, bearer_token(authorization))
    operator = session.get(Operator, op_session.operator_id) if op_session else None
    if not operator:
        raise HTTPException(401, "invalid or expired session")
    return operator


def resolve_client_id(
    authorization: str = Header(None), session: Session = Depends(get_session)
) -> int:
    """Dual auth for endpoints shared by the widget (client api_key) and the panel
    (operator session token). Returns the owning client_id from whichever matches."""
    token = bearer_token(authorization)
    op_session = get_operator_session(session, token)
    if op_session:
        return op_session.client_id
    client = session.exec(select(Client).where(Client.api_key == token)).first()
    if client:
        return client.id
    raise HTTPException(401, "invalid credentials")


# ---- Trusted WordPress installation ----------------------------------------------------------
#
# A verified installation, not the widget api_key: that key sits in every public page of the
# site, so it must never authorise anything a stranger could regret. This credential is issued
# once per site through a challenge and can act on the tenant's own content.


def plugin_secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def require_plugin_installation(
    authorization: str = Header(None), session: Session = Depends(get_session),
) -> PluginInstallation:
    secret = bearer_token(authorization)
    if len(secret) < 32 or len(secret) > 256:
        raise HTTPException(401, "invalid plugin credential")
    row = session.exec(select(PluginInstallation).where(
        PluginInstallation.secret_hash == plugin_secret_hash(secret),
    )).first()
    if row is None:
        raise HTTPException(401, "invalid plugin credential")
    return row


# ---- Audit -----------------------------------------------------------------------------------


def audit(session, actor_type, actor_id, action, target="", client_id=None, detail=None):
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

# ---- Rate limits ------------------------------------------------------------------------------
#
# Process-wide limiters. The per-plan budget is read from the caller's plan, so a paying tenant
# is never throttled by the free tier's ceiling.

chat_limiter = make_limiter(int(os.getenv("CHAT_RATE_LIMIT", "30")), 60)
ingest_limiter = make_limiter(int(os.getenv("INGEST_RATE_LIMIT", "60")), 60)


def plan_limit(session: Session, client: Client, attr: str, fallback: int) -> int:
    """The client's plan limit for `attr` (chat_rate_limit/ingest_rate_limit), or the
    global default if the client has no plan (shouldn't happen post-migration, but a
    missing/deleted plan must degrade to *some* limit rather than 500)."""
    plan = session.get(Plan, client.plan_id) if client.plan_id else None
    return getattr(plan, attr) if plan else fallback


def rate_limit_chat(request: Request, client: Client = Depends(require_client), session: Session = Depends(get_session)) -> Client:
    # La licenza è legata al dominio: questa chiave vale sui siti che il tenant ha registrato,
    # più gli indirizzi locali. È il punto in cui il vincolo è **applicabile** — qui si vede la
    # chiave, cosa che il livello CORS non può fare — e fallisce chiuso: senza domini registrati
    # o senza header Origin non si passa. Vedi `origins.licence_rejection`.
    allowed = origins.registered(session, client.id)
    origin = request.headers.get("origin")
    origins.observe(session, client.id, origin, allowed)
    rejection = origins.licence_rejection(origin, allowed)
    if rejection:
        raise HTTPException(403, rejection)
    ip = request.client.host if request.client else "unknown"
    limit = plan_limit(session, client, "chat_rate_limit", chat_limiter.limit)
    chat_limiter.check(f"chat:{client.id}:{ip}", limit=limit)
    return client


def rate_limit_ingest(client: Client = Depends(require_client), session: Session = Depends(get_session)) -> Client:
    limit = plan_limit(session, client, "ingest_rate_limit", ingest_limiter.limit)
    ingest_limiter.check(f"ingest:{client.id}", limit=limit)
    return client

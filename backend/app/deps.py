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

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session, or_, select

from .db import ApiKey, AuditLog, Client, Operator, OperatorSession, get_session
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

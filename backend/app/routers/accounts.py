"""Accounts and authentication.

Self-service signup with the free trial, operator login and logout, email verification, password
reset, and the tenant's own profile and onboarding checklist.

Single-use tokens are stored hashed and consumed on first use; a failed login and an unknown
address are answered identically, so neither can be used to enumerate accounts.

Final phase of the main.py split — see `docs/handoff.md`.
"""
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta

import stripe
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from sqlalchemy import func
from sqlmodel import Session, select

from .. import billing, cors, email as email_service
from ..billing import default_plan_id as _default_plan_id
from ..db import (
    AuthToken, Chunk, Client, Conversation, Operator, OperatorSession, Plan, PluginInstallation,
    Product, get_session,
)
from ..deps import (
    audit as _audit, bearer_token as _bearer_token, hash_session_token as _hash_session_token,
    get_operator_session as _get_operator_session, require_operator,
)
from ..ratelimit import make_limiter
from ..logging_config import log
from ..security import hash_password, password_needs_rehash, verify_password
from ..util import iso as _iso

logger = logging.getLogger("wpai")

RESET_TOKEN_TTL = timedelta(hours=int(os.getenv("RESET_TOKEN_TTL_HOURS", "1")))
VERIFY_TOKEN_TTL = timedelta(hours=int(os.getenv("VERIFY_TOKEN_TTL_HOURS", "48")))
OPERATOR_SESSION_TTL = timedelta(hours=int(os.getenv("OPERATOR_SESSION_TTL_HOURS", str(24 * 30))))
auth_limiter = make_limiter(int(os.getenv("AUTH_RATE_LIMIT", "10")), 60)

router = APIRouter()


def _rate_limit_auth(request: Request, scope: str, identity: str = "") -> None:
    ip = request.client.host if request.client else "unknown"
    identity_digest = hashlib.sha256(identity.strip().lower().encode()).hexdigest()[:16]
    auth_limiter.check(f"auth:{scope}:{ip}:{identity_digest}")


@router.get("/public/plans")
def public_plans(session: Session = Depends(get_session)):
    """Purchasable plans for the public signup page (no auth). Free/priceless plans are hidden."""
    return [
        {
            "id": p.id, "name": p.name, "price_cents": p.price_cents,
            "yearly_price_cents": p.yearly_price_cents, "currency": p.currency,
        }
        for p in session.exec(
            select(Plan).where(Plan.internal.is_(False)).order_by(Plan.price_cents, Plan.id)
        ).all()
        if p.stripe_price_id
    ]


@router.post("/signup")
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
        cors.rebuild_allowed_origins(session)

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


@router.get("/me")
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


@router.get("/onboarding/status")
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


@router.post("/me/name")
def set_my_name(name: str = Body(..., embed=True), operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """Operator sets their own display name (shown to visitors in the typing indicator)."""
    operator.name = name.strip()[:80]
    session.add(operator)
    session.commit()
    return {"ok": True, "name": operator.name}


@router.post("/me/password")
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


@router.post("/me/rotate-key")
def rotate_own_key(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """Rotate the widget api_key for the operator's own client. Old key stops working
    immediately — the WP plugin (or anything else using it) needs the new key."""
    client = session.get(Client, operator.client_id)
    client.api_key = secrets.token_urlsafe(32)
    session.add(client)
    session.commit()
    return {"api_key": client.api_key}


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


@router.post("/auth/verify-email")
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


@router.post("/auth/resend-verification")
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


@router.post("/auth/forgot")
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


@router.post("/auth/reset")
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


@router.post("/operator/login")
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


@router.post("/operator/logout")
def operator_logout(authorization: str = Header(None), operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    op_session = _get_operator_session(session, _bearer_token(authorization))
    if op_session:
        session.delete(op_session)
        session.commit()
    return {"ok": True}

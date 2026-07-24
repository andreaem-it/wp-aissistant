"""Stripe billing: config + webhook event handling.

Checkout session creation lives in main.py (it needs request context); this module holds
the Stripe config, subscription-status mapping, and the webhook handler that keeps a
Client's plan/billing fields in sync. Everything is a no-op unless both STRIPE_SECRET_KEY
and STRIPE_WEBHOOK_SECRET are set (enabled()), so the app runs fine without Stripe.
"""

import os

import stripe
from sqlmodel import Session, select

from .db import Client, Plan

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
SUCCESS_URL = os.getenv("BILLING_SUCCESS_URL", "http://localhost:5173/billing?status=success")
CANCEL_URL = os.getenv("BILLING_CANCEL_URL", "http://localhost:5173/billing?status=cancel")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# Stripe subscription.status -> our client.billing_status
_STATUS_MAP = {
    "active": "active",
    "trialing": "trialing",
    "past_due": "past_due",
    "unpaid": "past_due",
    "incomplete": "past_due",
    "canceled": "canceled",
    "incomplete_expired": "canceled",
}


def enabled() -> bool:
    return bool(STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET)


def map_status(stripe_status: str) -> str:
    return _STATUS_MAP.get(stripe_status, "active")


def _client_by_id(session: Session, client_id) -> "Client | None":
    try:
        return session.get(Client, int(client_id)) if client_id else None
    except (TypeError, ValueError):
        return None


def _client_by_subscription(session: Session, sub_id) -> "Client | None":
    if not sub_id:
        return None
    return session.exec(select(Client).where(Client.stripe_subscription_id == sub_id)).first()


def _free_plan_id(session: Session) -> "int | None":
    """The plan to fall back to on cancellation: the one named 'Free', else the oldest."""
    plan = (
        session.exec(select(Plan).where(Plan.name == "Free")).first()
        or session.exec(select(Plan).order_by(Plan.id)).first()
    )
    return plan.id if plan else None


def handle_event(session: Session, event) -> None:
    """Apply a verified Stripe event to the owning client. Unknown event types are ignored."""
    etype = event["type"]
    obj = event["data"]["object"]
    metadata = obj.get("metadata") or {}

    if etype == "checkout.session.completed":
        client = _client_by_id(session, metadata.get("client_id"))
        if not client:
            return
        client.stripe_customer_id = obj.get("customer") or client.stripe_customer_id
        client.stripe_subscription_id = obj.get("subscription") or client.stripe_subscription_id
        plan_id = metadata.get("plan_id")
        if plan_id and session.get(Plan, int(plan_id)):
            client.plan_id = int(plan_id)
        client.billing_status = "active"
        session.add(client)
        session.commit()

    elif etype in ("customer.subscription.updated", "customer.subscription.deleted"):
        client = _client_by_subscription(session, obj.get("id")) or _client_by_id(session, metadata.get("client_id"))
        if not client:
            return
        if etype == "customer.subscription.deleted":
            client.billing_status = "canceled"
        else:
            client.billing_status = map_status(obj.get("status", "active"))
        # policy: canceled -> downgrade to Free (its limits apply via plan_id). past_due keeps
        # the paid plan as a grace period while Stripe retries the payment.
        if client.billing_status == "canceled":
            free_id = _free_plan_id(session)
            if free_id:
                client.plan_id = free_id
        session.add(client)
        session.commit()

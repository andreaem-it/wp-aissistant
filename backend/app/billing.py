"""Stripe billing: config + webhook event handling.

Checkout and billing-portal session creation live in main.py (they need request context);
this module holds the Stripe config, subscription-status mapping, and the webhook handler
that keeps a Client's plan/billing fields in sync. Everything is a no-op unless both
STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET are set (enabled()), so the app runs fine
without Stripe.
"""

import logging
import os
from datetime import datetime

import stripe
from sqlmodel import Session, select

from . import email as email_service
from .db import Client, Operator, Plan
from .logging_config import log

logger = logging.getLogger("wpai.billing")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
SUCCESS_URL = os.getenv("BILLING_SUCCESS_URL", "http://localhost:5173/billing?status=success")
CANCEL_URL = os.getenv("BILLING_CANCEL_URL", "http://localhost:5173/billing?status=cancel")
# where Stripe sends the customer back after they close the billing portal
PORTAL_RETURN_URL = os.getenv("BILLING_PORTAL_RETURN_URL", "") or SUCCESS_URL
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "14"))  # free trial length for self-serve signup

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


def _apply_plan(session: Session, client: "Client", plan_id) -> None:
    if plan_id and session.get(Plan, int(plan_id)):
        client.plan_id = int(plan_id)


def _period_end(value) -> "datetime | None":
    """Stripe sends unix seconds; anything else means "unknown", never a wrong date."""
    try:
        return datetime.utcfromtimestamp(int(value)) if value else None
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _notify(session: Session, client: "Client", send) -> None:
    """Send one billing notice to every verified operator of the tenant.

    Billing news must reach a human who can act on it, so this fans out to the whole team
    rather than to a single stored address. Delivery problems are logged: a failed email must
    never abort the webhook, or Stripe would retry an event we already applied.
    """
    recipients = session.exec(
        select(Operator)
        .where(Operator.client_id == client.id, Operator.email_verified.is_(True))
        .order_by(Operator.id)
    ).all()
    for operator in recipients:
        if not operator.email:
            continue
        try:
            send(operator.email)
        except Exception:  # noqa: BLE001 — notification is best-effort, sync is not
            log(logger, logging.WARNING, "billing.notify_failed", client_id=client.id)


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
        _apply_plan(session, client, metadata.get("plan_id"))
        # activate only if a subscription.* event hasn't already set a precise status (e.g.
        # "trialing" for a signup) — avoids overwriting the trial status regardless of order.
        if client.billing_status in ("incomplete", ""):
            client.billing_status = "active"
        session.add(client)
        session.commit()

    elif etype in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
        client = _client_by_subscription(session, obj.get("id")) or _client_by_id(session, metadata.get("client_id"))
        if not client:
            return
        client.stripe_subscription_id = obj.get("id") or client.stripe_subscription_id
        was_scheduled_to_cancel = client.subscription_cancel_at_period_end
        if etype == "customer.subscription.deleted":
            client.billing_status = "canceled"
            client.subscription_cancel_at_period_end = False
        else:
            client.billing_status = map_status(obj.get("status", "active"))  # active | trialing | past_due | ...
            _apply_plan(session, client, metadata.get("plan_id"))
            client.subscription_cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
        # mirror the paid-through date so /usage can answer without calling Stripe
        client.subscription_period_end = _period_end(obj.get("current_period_end")) or client.subscription_period_end
        # policy: canceled -> downgrade to Free (its limits apply via plan_id). past_due keeps
        # the paid plan as a grace period while Stripe retries the payment.
        if client.billing_status == "canceled":
            free_id = _free_plan_id(session)
            if free_id:
                client.plan_id = free_id
        session.add(client)
        session.commit()
        # tell the customer only about the transitions they need to act on, and only once:
        # a cancellation already announced at period end must not mail them twice.
        if etype == "customer.subscription.deleted":
            _notify(session, client, email_service.send_subscription_canceled)
        elif client.subscription_cancel_at_period_end and not was_scheduled_to_cancel:
            ends_on = client.subscription_period_end
            _notify(session, client, lambda to: email_service.send_cancellation_scheduled(to, ends_on))

    elif etype == "customer.subscription.trial_will_end":
        client = _client_by_subscription(session, obj.get("id")) or _client_by_id(session, metadata.get("client_id"))
        if not client:
            return
        trial_end = _period_end(obj.get("trial_end"))
        _notify(session, client, lambda to: email_service.send_trial_ending(to, trial_end))

    elif etype == "invoice.payment_failed":
        client = (
            _client_by_subscription(session, obj.get("subscription"))
            or _client_by_id(session, metadata.get("client_id"))
        )
        if not client:
            return
        # the status itself arrives on subscription.updated; here we only warn the customer,
        # while Stripe keeps retrying the charge (the plan stays active as a grace period).
        _notify(session, client, email_service.send_payment_failed)

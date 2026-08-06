"""Billing and the superadmin's commercial views.

Everything a paying relationship needs: checkout, the customer's Stripe portal, the webhook
that is the single writer of billing state, and the superadmin's revenue, cost, activation and
retention reporting plus the actions that change a subscription.

First area extracted from main.py. It was chosen because it needs no helper from there — see
`docs/handoff.md` for the pattern and the order of the remaining areas.
"""
import logging
from datetime import datetime

import stripe
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlmodel import Session, select

from .. import billing
from .. import costs as costs_service
from .. import growth
from ..db import Client, ModelPrice, Operator, Plan, get_session
from ..deps import audit as _audit, require_admin, require_operator
from ..logging_config import log

logger = logging.getLogger("wpai")

router = APIRouter()


@router.post("/billing/checkout")
def billing_checkout(
    plan_id: int = Body(..., embed=True),
    billing_interval: str = Body("month", embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Start a Stripe Checkout session for the operator's client to subscribe to `plan_id`.
    Returns the hosted checkout URL to redirect the browser to."""
    if not billing.enabled():
        raise HTTPException(503, "billing not configured")
    plan = session.get(Plan, plan_id)
    if not plan:
        raise HTTPException(404, "plan not found")
    stripe_price_id = billing.price_for_interval(plan, billing_interval)
    if not stripe_price_id:
        raise HTTPException(400, f"plan has no {billing_interval}ly Stripe price")
    client = session.get(Client, operator.client_id)

    params = {
        "mode": "subscription",
        "line_items": [{"price": stripe_price_id, "quantity": 1}],
        "success_url": billing.SUCCESS_URL,
        "cancel_url": billing.CANCEL_URL,
        "client_reference_id": str(client.id),
        # the interval rides along so revenue reporting can tell a yearly subscriber from a
        # monthly one even before the first subscription.* event arrives
        "metadata": {
            "client_id": str(client.id),
            "plan_id": str(plan.id),
            "billing_interval": billing_interval,
        },
        # carry ids onto the subscription too, so later subscription.* events map back to the client
        "subscription_data": {"metadata": {
            "client_id": str(client.id),
            "plan_id": str(plan.id),
            "billing_interval": billing_interval,
        }},
    }
    if client.stripe_customer_id:
        params["customer"] = client.stripe_customer_id
    checkout = stripe.checkout.Session.create(**params)
    return {"checkout_url": checkout.url, "id": checkout.id}


@router.post("/billing/portal")
def billing_portal(
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Open the Stripe billing portal for the operator's client.

    This is where the customer updates the payment method, downloads invoices, switches plan
    and cancels — all of it hosted by Stripe, so no card data ever reaches us. The resulting
    changes come back as subscription.* webhooks, which is what actually updates our records.
    """
    if not billing.enabled():
        raise HTTPException(503, "billing not configured")
    client = session.get(Client, operator.client_id)
    if not client or not client.stripe_customer_id:
        # no Stripe customer yet: the tenant has never checked out, so there is nothing to
        # manage. Say so explicitly instead of opening an empty portal.
        raise HTTPException(409, "no active subscription to manage")
    try:
        portal = stripe.billing_portal.Session.create(
            customer=client.stripe_customer_id,
            return_url=billing.PORTAL_RETURN_URL,
        )
    except Exception:  # noqa: BLE001 — Stripe outage or unconfigured portal
        log(logger, logging.WARNING, "billing.portal_failed", client_id=client.id)
        raise HTTPException(502, "billing portal temporarily unavailable")
    return {"portal_url": portal.url}


@router.post("/billing/webhook")
async def billing_webhook(request: Request, session: Session = Depends(get_session)):
    """Stripe webhook: verifies the signature, then syncs the client's plan/billing status."""
    if not billing.enabled():
        raise HTTPException(503, "billing not configured")
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, signature, billing.STRIPE_WEBHOOK_SECRET)
    except Exception:  # noqa: BLE001 — bad signature or malformed payload
        raise HTTPException(400, "invalid signature")
    billing.handle_event(session, event)
    return {"received": True}


@router.get("/billing/plans")
def billing_plans(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """Plans visible to an operator for self-serve upgrades (purchasable = has a Stripe price)."""
    return [
        {
            "id": p.id, "name": p.name, "price_cents": p.price_cents,
            "yearly_price_cents": p.yearly_price_cents, "currency": p.currency,
            "purchasable": bool(p.stripe_price_id),
            "yearly_purchasable": bool(p.stripe_yearly_price_id),
        }
        for p in session.exec(select(Plan).order_by(Plan.price_cents, Plan.id)).all()
    ]


@router.get("/admin/revenue", dependencies=[Depends(require_admin)])
def admin_revenue(days: int = 30, session: Session = Depends(get_session)):
    """Recurring revenue across every tenant, plus the accounts that need commercial attention.

    Rebuilt from the plans and subscriptions as they stand: we keep no historical snapshots of
    the customer base, so this reports cancellation *counts* over the window rather than a churn
    rate that would have to be invented. See billing.revenue_summary().
    """
    if days < 1 or days > 365:
        raise HTTPException(400, "days must be between 1 and 365")
    return billing.revenue_summary(session, days=days)


@router.get("/admin/costs", dependencies=[Depends(require_admin)])
def admin_costs(days: int = 30, session: Session = Depends(get_session)):
    """AI spend per tenant and the margin it leaves, priced from the recorded token usage.

    Inference only: embeddings, storage and channel fees are not recorded per turn, so the
    margin here is a ceiling. Models without a price are listed in `unpriced_models` and kept
    out of the totals — see app/costs.py.
    """
    if days < 1 or days > 365:
        raise HTTPException(400, "days must be between 1 and 365")
    return costs_service.cost_summary(session, days=days)


@router.get("/admin/activation", dependencies=[Depends(require_admin)])
def admin_activation(days: int = 90, session: Session = Depends(get_session)):
    """How far the accounts created in the window got: plugin, prima chat, risposta utile, pagamento.

    Clients created before migration 0049 with no operator to backfill from have no known date;
    they are excluded from the cohort and counted in `undated_clients` instead of dragging the
    conversion rates down. See app/growth.py.
    """
    if days < 1 or days > 365:
        raise HTTPException(400, "days must be between 1 and 365")
    return growth.activation_funnel(session, days=days)


@router.get("/admin/at-risk", dependencies=[Depends(require_admin)])
def admin_at_risk(days: int = 14, session: Session = Depends(get_session)):
    """Clients with a concrete reason for concern, each spelled out rather than scored."""
    if days < 1 or days > 180:
        raise HTTPException(400, "days must be between 1 and 180")
    return growth.at_risk_clients(session, days=days)


def _model_price_payload(row: ModelPrice) -> dict:
    """Prices go back out in the provider's own unit, so the panel shows what was pasted in."""
    return {
        "id": row.id,
        "model": row.model,
        "input_price_per_million": costs_service.price_per_million(row.input_millicents_per_million),
        "output_price_per_million": costs_service.price_per_million(row.output_millicents_per_million),
        "currency": row.currency,
    }


@router.get("/admin/model-prices", dependencies=[Depends(require_admin)])
def list_model_prices(session: Session = Depends(get_session)):
    rows = session.exec(select(ModelPrice).order_by(ModelPrice.model)).all()
    return [_model_price_payload(row) for row in rows]


@router.put("/admin/model-prices", dependencies=[Depends(require_admin)])
def upsert_model_price(
    model: str = Body(...),
    input_price_per_million: float = Body(0),
    output_price_per_million: float = Body(0),
    currency: str = Body("eur"),
    session: Session = Depends(get_session),
):
    """Set the price of one model, **per million tokens in the provider's own currency** — the
    figure as published (0.152), not a converted one. Upsert by model name so the superadmin can
    paste a whole price list without deleting rows first.
    """
    name = (model or "").strip()[:255]
    if not name:
        raise HTTPException(400, "model required")
    if input_price_per_million < 0 or output_price_per_million < 0:
        raise HTTPException(400, "prices cannot be negative")
    clean_currency = (currency or "eur").strip().lower()
    if len(clean_currency) != 3:
        raise HTTPException(400, "currency must be a 3-letter ISO code")
    row = session.exec(select(ModelPrice).where(ModelPrice.model == name)).first()
    if row is None:
        row = ModelPrice(model=name)
    row.input_millicents_per_million = costs_service.to_millicents(input_price_per_million)
    row.output_millicents_per_million = costs_service.to_millicents(output_price_per_million)
    row.currency = clean_currency
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    payload = _model_price_payload(row)  # read before _audit commits and expires the row
    _audit(session, "admin", "admin", "model_price.set", target=f"model:{name}",
           detail={"input": input_price_per_million, "output": output_price_per_million,
                   "currency": clean_currency})
    return payload


@router.delete("/admin/model-prices/{price_id}", dependencies=[Depends(require_admin)])
def delete_model_price(price_id: int, session: Session = Depends(get_session)):
    row = session.get(ModelPrice, price_id)
    if not row:
        raise HTTPException(404, "model price not found")
    session.delete(row)
    session.commit()
    _audit(session, "admin", "admin", "model_price.deleted", target=f"model:{row.model}")
    return {"deleted": True}


@router.post("/admin/clients/{client_id}/plan", dependencies=[Depends(require_admin)])
def set_client_plan(
    client_id: int,
    plan_id: int = Body(..., embed=True),
    billing_interval: str = Body("month", embed=True),
    session: Session = Depends(get_session),
):
    """Move a client onto another plan.

    With a live Stripe subscription the change goes **through Stripe** and the row is left to
    the webhook: writing `plan_id` here directly used to leave the database claiming one plan
    while Stripe billed another, until the next event silently overwrote it. Clients without a
    subscription (free, manually provisioned) are still set directly — there is nothing to sync.
    """
    client = session.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")
    plan = session.get(Plan, plan_id)
    if not plan:
        raise HTTPException(404, "plan not found")

    if client.stripe_subscription_id and billing.enabled():
        price_id = billing.price_for_interval(plan, billing_interval)
        if not price_id:
            raise HTTPException(400, f"plan has no {billing_interval}ly Stripe price")
        try:
            billing.change_plan(client, price_id)
        except billing.BillingActionError as exc:
            raise HTTPException(502, str(exc))
        _audit(session, "admin", "admin", "client.set_plan", target=f"client:{client_id}",
               client_id=client_id, detail={"plan_id": plan_id, "via": "stripe"})
        # the row still shows the old plan until the webhook lands; say so instead of implying
        # the change is already reflected here
        return {"id": client.id, "plan_id": client.plan_id, "pending_plan_id": plan_id, "via": "stripe"}

    client.plan_id = plan_id
    session.add(client)
    session.commit()
    _audit(session, "admin", "admin", "client.set_plan", target=f"client:{client_id}", client_id=client_id, detail={"plan_id": plan_id, "via": "direct"})
    return {"id": client.id, "plan_id": client.plan_id, "via": "direct"}


def _subscription_action(client_id: int, session: Session, action, *, name: str, detail: dict | None = None):
    """Run one Stripe-side action on a client's subscription and record it.

    Nothing is written to the client row: the subscription.* webhook is the only thing that
    updates billing state, so there is never a moment when we and Stripe disagree.
    """
    if not billing.enabled():
        raise HTTPException(503, "billing not configured")
    client = session.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")
    try:
        action(client)
    except billing.BillingActionError as exc:
        raise HTTPException(409, str(exc))
    _audit(session, "admin", "admin", f"subscription.{name}", target=f"client:{client_id}",
           client_id=client_id, detail=detail or {})
    return {"ok": True, "applied": name, "note": "Lo stato si aggiorna quando arriva il webhook Stripe."}


@router.post("/admin/clients/{client_id}/subscription/trial", dependencies=[Depends(require_admin)])
def extend_client_trial(client_id: int, days: int = Body(..., embed=True), session: Session = Depends(get_session)):
    """Extend the free trial by `days` counted from today (see billing.extend_trial)."""
    return _subscription_action(
        client_id, session, lambda c: billing.extend_trial(c, days),
        name="trial_extended", detail={"days": days},
    )


@router.post("/admin/clients/{client_id}/subscription/discount", dependencies=[Depends(require_admin)])
def apply_client_discount(client_id: int, coupon: str = Body(..., embed=True), session: Session = Depends(get_session)):
    """Attach an existing Stripe coupon; coupons are created in the Stripe dashboard."""
    return _subscription_action(
        client_id, session, lambda c: billing.apply_discount(c, coupon),
        name="discount_applied", detail={"coupon": (coupon or "").strip()[:100]},
    )


@router.delete("/admin/clients/{client_id}/subscription/discount", dependencies=[Depends(require_admin)])
def remove_client_discount(client_id: int, session: Session = Depends(get_session)):
    return _subscription_action(
        client_id, session, billing.remove_discount, name="discount_removed",
    )


@router.post("/admin/clients/{client_id}/subscription/pause", dependencies=[Depends(require_admin)])
def pause_client_subscription(client_id: int, paused: bool = Body(..., embed=True), session: Session = Depends(get_session)):
    """Stop or resume collection without cancelling: the plan stays, the charges stop."""
    return _subscription_action(
        client_id, session,
        billing.pause_collection if paused else billing.resume_collection,
        name="paused" if paused else "resumed",
    )


@router.post("/admin/clients/{client_id}/subscription/cancel", dependencies=[Depends(require_admin)])
def cancel_client_subscription(client_id: int, cancel: bool = Body(True, embed=True), session: Session = Depends(get_session)):
    """Schedule, or call off, a cancellation at the end of the paid period — never immediate."""
    return _subscription_action(
        client_id, session, lambda c: billing.set_cancellation(c, cancel),
        name="cancellation_scheduled" if cancel else "cancellation_revoked",
    )

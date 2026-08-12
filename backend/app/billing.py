"""Stripe billing: config + webhook event handling.

Checkout and billing-portal session creation live in main.py (they need request context);
this module holds the Stripe config, subscription-status mapping, and the webhook handler
that keeps a Client's plan/billing fields in sync. Everything is a no-op unless both
STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET are set (enabled()), so the app runs fine
without Stripe.
"""

import logging
import os
from datetime import datetime, timedelta

import stripe
from fastapi import HTTPException
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


def price_for_interval(plan: "Plan", billing_interval: str) -> str:
    """The Stripe price id for a plan on a given interval.

    Shared by signup, checkout and the superadmin plan change, so it lives here rather than in
    any one caller: the router that used to own it is not something main.py should import.
    """
    if billing_interval == "month":
        return plan.stripe_price_id
    if billing_interval == "year":
        return plan.stripe_yearly_price_id
    raise HTTPException(400, "billing_interval must be 'month' or 'year'")


def enabled() -> bool:
    return bool(STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET)


# Gli stati in cui il servizio viene erogato. `past_due` è dentro di proposito: è il periodo di
# grazia mentre Stripe ritenta il pagamento, e spegnere l'assistente a un cliente per una carta
# scaduta gli farebbe perdere conversazioni vere. Fuori restano `incomplete` (mai pagato) e
# `canceled` (sospeso): non esiste un piano gratuito che li copra.
SERVING_STATUSES = ("active", "trialing", "past_due")


def service_suspended(client: "Client | None") -> bool:
    """Se il servizio è sospeso per questo tenant."""
    return bool(client) and client.billing_status not in SERVING_STATUSES


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


def _apply_plan(session: Session, client: "Client", plan_id) -> None:
    if plan_id and session.get(Plan, int(plan_id)):
        client.plan_id = int(plan_id)


def _interval(obj) -> str:
    """"month"/"year" from a Stripe subscription payload; "" when the shape is unfamiliar."""
    try:
        items = (obj.get("items") or {}).get("data") or []
        recurring = (items[0].get("price") or {}).get("recurring") or {} if items else {}
        found = recurring.get("interval") or ""
    except (AttributeError, IndexError, TypeError):
        return ""
    return found if found in ("month", "year") else ""


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
        if metadata.get("billing_interval") in ("month", "year"):
            client.subscription_interval = metadata["billing_interval"]
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
            client.subscription_canceled_at = datetime.utcnow()
        else:
            client.billing_status = map_status(obj.get("status", "active"))  # active | trialing | past_due | ...
            _apply_plan(session, client, metadata.get("plan_id"))
            client.subscription_cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
            client.subscription_canceled_at = None  # a live subscription is not churn
        # keep the last known interval when Stripe sends a payload we cannot read: guessing
        # "month" for a yearly subscriber would inflate the MRR by twelve.
        client.subscription_interval = (
            _interval(obj) or metadata.get("billing_interval") or client.subscription_interval
        )
        # mirror the paid-through date so /usage can answer without calling Stripe
        client.subscription_period_end = _period_end(obj.get("current_period_end")) or client.subscription_period_end
        # Non esiste un piano gratuito a cui retrocedere: alla disdetta il servizio si sospende
        # e parte il conto alla rovescia per la cancellazione dei dati. Il `plan_id` resta quello
        # che il cliente aveva — serve a sapere cosa riattivare, non a dargli accesso.
        # past_due tiene il piano come periodo di grazia mentre Stripe ritenta il pagamento.
        if client.billing_status == "canceled":
            client.data_deletion_due_at = _deletion_due_from(client)
        elif client.billing_status in ("active", "trialing"):
            # riattivazione: il conto alla rovescia si annulla, non si mette in pausa
            client.data_deletion_due_at = None
        session.add(client)
        session.commit()
        # tell the customer only about the transitions they need to act on, and only once:
        # a cancellation already announced at period end must not mail them twice.
        if etype == "customer.subscription.deleted":
            deletion_on = client.data_deletion_due_at
            _notify(session, client, lambda to: email_service.send_subscription_canceled(
                to, deletion_on, DATA_RETENTION_DAYS))
        elif client.subscription_cancel_at_period_end and not was_scheduled_to_cancel:
            ends_on = client.subscription_period_end
            _notify(session, client, lambda to: email_service.send_cancellation_scheduled(
                to, ends_on, DATA_RETENTION_DAYS))

    elif etype == "customer.subscription.trial_will_end":
        client = _client_by_subscription(session, obj.get("id")) or _client_by_id(session, metadata.get("client_id"))
        if not client:
            return
        trial_end = _period_end(obj.get("trial_end"))
        _notify(session, client, lambda to: email_service.send_trial_ending(to, trial_end))

    elif etype == "invoice.payment_succeeded":
        client = (
            _client_by_subscription(session, obj.get("subscription"))
            or _client_by_id(session, metadata.get("client_id"))
        )
        # only the *first* collected invoice is recorded: it marks the moment a trial became
        # revenue, and later renewals must not keep pushing that date forward. A zero-amount
        # invoice (a fully discounted trial) is not a payment.
        if client and client.first_paid_at is None and int(obj.get("amount_paid") or 0) > 0:
            client.first_paid_at = datetime.utcnow()
            session.add(client)
            session.commit()

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


# ---- Revenue reporting ----------------------------------------------------------------------
#
# Everything below is derived from the current rows: we keep no historical snapshots of the
# customer base. That bounds what can honestly be reported — see revenue_summary().


def monthly_value_cents(plan: "Plan | None", interval: str) -> int:
    """What one subscriber on this plan contributes per month, normalised across intervals.

    A yearly subscriber pays yearly_price_cents once a year, so it is divided by twelve. When a
    plan has no yearly price the yearly subscription cannot be priced, and this returns 0 rather
    than silently charging them the monthly rate.
    """
    if not plan:
        return 0
    if interval == "year":
        return round(plan.yearly_price_cents / 12) if plan.yearly_price_cents else 0
    return plan.price_cents


# statuses that represent a contracted subscription, split by what they mean commercially
_EARNING = ("active",)
_AT_RISK = ("past_due",)
_TRIALING = ("trialing",)


# I due piani che il codice deve saper trovare. I nomi sono modificabili dal pannello, i codici no.
BOOTSTRAP_PLAN_CODE = "bootstrap"
UNLIMITED_PLAN_CODE = "internal_unlimited"


def platform_client_ids(session: Session) -> set[int]:
    """I tenant che **siamo noi**, non clienti: quelli su un piano interno che eroga servizio.

    Servono a tenerli fuori dalle viste commerciali. Il nostro tenant — quello che serve il
    widget sul sito e l'assistenza dentro il pannello dei clienti — genera costo di inferenza,
    embedding e storage con ricavo zero: lasciato negli aggregati comparirebbe come il cliente
    più in perdita del parco e nel funnel di attivazione come un cliente vero con numeri fuori
    scala.

    Non è "contarlo gratis": la sua spesa esiste ed è **costo di piattaforma**, dichiarato a parte
    da `costs.cost_summary`. È la stessa regola dei canali senza prezzo — ciò che non entra in un
    totale va detto, non nascosto.

    Il segnaposto `bootstrap` resta **fuori** da questo insieme, e la distinzione è tutt'altro che
    formale: sul segnaposto ci sta chi si è registrato e non ha ancora pagato, cioè esattamente
    la popolazione che il funnel di attivazione esiste per misurare. Escludere ogni piano
    `internal` svuoterebbe la vista invece di ripulirla.
    """
    ours = [
        plan.id
        for plan in session.exec(
            select(Plan).where(Plan.internal.is_(True), Plan.code != BOOTSTRAP_PLAN_CODE)
        ).all()
    ]
    if not ours:
        return set()
    return {
        client.id
        for client in session.exec(select(Client).where(Client.plan_id.in_(ours))).all()
    }


def revenue_summary(session: Session, days: int = 30) -> dict:
    """Recurring revenue rebuilt from the plans and subscriptions as they stand right now.

    Three buckets, deliberately kept apart instead of folded into one headline number:
      - `mrr_cents`     — subscriptions that are actually being paid (`active`)
      - `at_risk_cents` — `past_due`: contracted, charged, but the last payment failed
      - `trial_cents`   — `trialing`: not revenue yet, only what it would become

    Churn is reported as a **count of cancellations** in the window, not as a rate: without
    snapshots of the past customer base a rate would be invented, not measured.
    """
    plans = {plan.id: plan for plan in session.exec(select(Plan)).all()}
    # I nostri tenant non sono ricavo e non sono churn: un piano interno non è un prodotto.
    internal = platform_client_ids(session)
    clients = [c for c in session.exec(select(Client)).all() if c.id not in internal]
    since = datetime.utcnow() - timedelta(days=max(days, 1))
    soon = datetime.utcnow() + timedelta(days=7)

    buckets = {"mrr_cents": 0, "at_risk_cents": 0, "trial_cents": 0}
    by_plan: dict[str, dict] = {}
    currencies: set[str] = set()
    paying = 0
    trials_ending, past_due, scheduled_cancellations, recent_cancellations = [], [], [], []

    for client in clients:
        plan = plans.get(client.plan_id)
        value = monthly_value_cents(plan, client.subscription_interval)
        status = client.billing_status
        row = {
            "client_id": client.id,
            "name": client.name,
            "plan": plan.name if plan else None,
            "monthly_value_cents": value,
        }

        if status in _EARNING:
            buckets["mrr_cents"] += value
        elif status in _AT_RISK:
            buckets["at_risk_cents"] += value
            past_due.append(row)
        elif status in _TRIALING:
            buckets["trial_cents"] += value
            if client.subscription_period_end and client.subscription_period_end <= soon:
                trials_ending.append({**row, "ends_at": client.subscription_period_end})

        if value and status in (*_EARNING, *_AT_RISK):
            paying += 1
            if plan:
                currencies.add(plan.currency)
                entry = by_plan.setdefault(plan.name, {"clients": 0, "mrr_cents": 0})
                entry["clients"] += 1
                entry["mrr_cents"] += value

        if client.subscription_cancel_at_period_end:
            scheduled_cancellations.append({**row, "ends_at": client.subscription_period_end})
        if client.subscription_canceled_at and client.subscription_canceled_at >= since:
            recent_cancellations.append({**row, "canceled_at": client.subscription_canceled_at})

    return {
        **buckets,
        "arr_cents": buckets["mrr_cents"] * 12,
        "paying_clients": paying,
        "arpa_cents": round(buckets["mrr_cents"] / paying) if paying else 0,
        # a single total is meaningless across currencies; say so instead of summing anyway
        "currency": next(iter(currencies), "eur") if len(currencies) <= 1 else None,
        "mixed_currencies": len(currencies) > 1,
        "by_plan": by_plan,
        "window_days": max(days, 1),
        "trials_ending": sorted(trials_ending, key=lambda r: r["ends_at"]),
        "past_due": past_due,
        "scheduled_cancellations": scheduled_cancellations,
        "recent_cancellations": sorted(
            recent_cancellations, key=lambda r: r["canceled_at"], reverse=True
        ),
    }


# ---- Commercial actions ---------------------------------------------------------------------
#
# All of these change the subscription **at Stripe** and return without touching the database.
# The resulting subscription.* webhook is what updates our rows, so there is exactly one path
# by which billing state changes and no window in which the two disagree.


class BillingActionError(RuntimeError):
    """A commercial action could not be carried out; the message is safe to show an admin."""


def _subscription_id(client: "Client") -> str:
    if not client.stripe_subscription_id:
        raise BillingActionError("Il cliente non ha un abbonamento Stripe attivo")
    return client.stripe_subscription_id


def _modify(subscription_id: str, **changes):
    try:
        return stripe.Subscription.modify(subscription_id, **changes)
    except Exception as exc:  # noqa: BLE001 — Stripe rejects for many reasons; report, never crash
        log(logger, logging.WARNING, "billing.action_failed", subscription=subscription_id,
            error=type(exc).__name__)
        raise BillingActionError("Stripe ha rifiutato l'operazione") from exc


def extend_trial(client: "Client", days: int, now: "datetime | None" = None):
    """Push the trial end out by `days` from today.

    Counted from now rather than from the current trial end: extending an *expired* trial by
    three days has to mean three days from today, not three days from a date already past.
    """
    if days < 1 or days > 90:
        raise BillingActionError("La proroga deve essere fra 1 e 90 giorni")
    until = (now or datetime.utcnow()) + timedelta(days=days)
    return _modify(_subscription_id(client), trial_end=int(until.timestamp()), proration_behavior="none")


def apply_discount(client: "Client", coupon: str):
    """Attach an existing Stripe coupon. The coupon itself is created in the Stripe dashboard:
    inventing discount rules here would put the commercial policy in two places."""
    code = (coupon or "").strip()
    if not code:
        raise BillingActionError("Codice sconto mancante")
    return _modify(_subscription_id(client), coupon=code)


def remove_discount(client: "Client"):
    return _modify(_subscription_id(client), coupon="")


def pause_collection(client: "Client"):
    """Stop charging without cancelling: the customer keeps the plan, Stripe stops collecting."""
    return _modify(_subscription_id(client), pause_collection={"behavior": "void"})


def resume_collection(client: "Client"):
    return _modify(_subscription_id(client), pause_collection="")


def set_cancellation(client: "Client", cancel: bool):
    """Schedule (or call off) a cancellation at the end of the paid period.

    Never cancels immediately: the customer has paid through the period, and taking the service
    away early would be a refundable dispute waiting to happen.
    """
    return _modify(_subscription_id(client), cancel_at_period_end=bool(cancel))


def change_plan(client: "Client", price_id: str):
    """Swap the subscription onto another price, prorating the difference.

    Reads the current item id first: replacing `items` without it would add a second line
    instead of moving the existing one, and the customer would be billed twice.
    """
    subscription_id = _subscription_id(client)
    try:
        current = stripe.Subscription.retrieve(subscription_id)
        items = (current.get("items") or {}).get("data") or []
        item_id = items[0]["id"] if items else None
    except Exception as exc:  # noqa: BLE001
        raise BillingActionError("Abbonamento non leggibile da Stripe") from exc
    if not item_id:
        raise BillingActionError("L'abbonamento non ha una linea da aggiornare")
    return _modify(
        subscription_id,
        items=[{"id": item_id, "price": price_id}],
        proration_behavior="create_prorations",
    )


# Quanto restano i dati dopo la disdetta prima di essere eliminati, e quando avvisare.
DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS_AFTER_CANCEL", "90"))
DELETION_REMINDER_DAYS = (30, 14, 7, 3)


def _deletion_due_from(client: "Client") -> datetime:
    """Da quando contare i 90 giorni: la fine del periodo pagato, non il momento della disdetta.

    Chi disdice a inizio mese ha già pagato fino a fine mese: far partire il conto alla rovescia
    subito gli toglierebbe giorni che ha comprato.
    """
    start = client.subscription_period_end or datetime.utcnow()
    return start + timedelta(days=DATA_RETENTION_DAYS)


def default_plan_id(session: Session) -> int:
    """Il piano assegnato a un account che non ha ancora pagato.

    Serve solo a dare dei limiti di frequenza a una riga che esiste prima del pagamento: non
    concede il servizio, che dipende da `billing_status` (`incomplete` non eroga). Prima qui
    veniva creato un piano chiamato "Free", che di fatto era una versione gratuita del prodotto
    a cui si finiva anche disdicendo.

    Su un database senza piani ne crea uno **interno**: non è un prodotto, non compare in nessun
    elenco rivolto a un cliente e non è acquistabile. Esiste perché `Client.plan_id` non è
    nullable e un'installazione nuova deve poter creare un account prima che il listino sia
    compilato.

    Si cerca per `code`, non per id più basso. La vecchia regola — "il primo piano che c'è" —
    funzionava finché il segnaposto era l'unico piano interno: da quando esiste anche
    «Interno — Illimitato», su un database dove quello nasce per primo ogni nuovo iscritto
    riceverebbe accesso illimitato. Un piano che concede tutto non deve poter diventare il
    default per un incidente di ordinamento.
    """
    plan = session.exec(select(Plan).where(Plan.code == BOOTSTRAP_PLAN_CODE)).first()
    if not plan:
        # Database precedenti alla 0055: il segnaposto c'è ma non ha ancora un codice. Si ripiega
        # sull'ordine di prima, **escludendo** i piani che concedono accesso illimitato.
        plan = session.exec(
            select(Plan).where(Plan.code != UNLIMITED_PLAN_CODE).order_by(Plan.id)
        ).first()
    if not plan:
        # `monthly_message_limit` resta 0 (illimitato) di proposito: non è questo piano a
        # concedere il servizio — lo decide `billing_status` — e un tetto qui taglierebbe le
        # gambe a un cliente creato a mano dal superadmin, che finisce su questa riga.
        plan = Plan(name="Nessun abbonamento", code=BOOTSTRAP_PLAN_CODE, internal=True,
                    price_cents=0, chat_rate_limit=30, ingest_rate_limit=60)
        session.add(plan)
        session.commit()
        session.refresh(plan)
    return plan.id

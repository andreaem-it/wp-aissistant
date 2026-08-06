"""Activation and retention: does a new account reach value, and is an existing one slipping?

Both answers are derived from rows we already keep — conversations, AI turns, ratings, plugin
installations, billing state — plus the two lifecycle dates added in migration 0049.

Two rules shape everything here:

- **An unknown is reported as unknown.** Clients with no `created_at` (they predate the field
  and had no operator to backfill from) are excluded from the funnel and counted separately,
  rather than silently dragging the conversion rates down.
- **Risk is a list of reasons, not a score.** A number between 0 and 100 tells nobody what to
  do; "uso calato del 70%, nessuna attività da 12 giorni" does.
"""
import logging
from datetime import datetime, timedelta

from sqlmodel import Session, func, select

from .db import (
    AiResponseLog,
    Client,
    Conversation,
    ConversationRating,
    PluginInstallation,
    Plan,
)
from .logging_config import log

logger = logging.getLogger("wpai.growth")

# a client counts as activated once the AI has actually answered someone: an account that only
# ever opened an empty chat has not reached value, however many conversations it created
ACTIVATION_OUTCOME = "answered"


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def activation_funnel(session: Session, days: int = 90) -> dict:
    """How far the accounts created in the window got, step by step.

    Steps are cumulative and ordered: plugin collegato → prima conversazione → prima risposta
    utile → primo pagamento. Each is counted independently against the same cohort, so a client
    that skipped a step still counts for the later ones it did reach.
    """
    since = datetime.utcnow() - timedelta(days=max(days, 1))
    clients = session.exec(select(Client)).all()
    cohort = [c for c in clients if c.created_at and c.created_at >= since]
    undated = sum(1 for c in clients if not c.created_at)

    if not cohort:
        return {
            "window_days": max(days, 1), "cohort": 0, "undated_clients": undated,
            "steps": [], "median_hours_to_activation": None, "stuck": [],
        }

    ids = [c.id for c in cohort]
    # a single-column select comes back as scalars, not one-tuples
    installed = set(session.exec(
        select(PluginInstallation.client_id).where(PluginInstallation.client_id.in_(ids)).distinct()
    ).all())
    first_conversation = dict(session.exec(
        select(Conversation.client_id, func.min(Conversation.created_at))
        .where(Conversation.client_id.in_(ids)).group_by(Conversation.client_id)
    ).all())
    first_answer = dict(session.exec(
        select(AiResponseLog.client_id, func.min(AiResponseLog.created_at))
        .where(AiResponseLog.client_id.in_(ids), AiResponseLog.outcome == ACTIVATION_OUTCOME)
        .group_by(AiResponseLog.client_id)
    ).all())

    activated_ids = set(first_answer)
    paid_ids = {c.id for c in cohort if c.first_paid_at}
    steps = [
        {"key": "created", "label": "Account creato", "clients": len(cohort)},
        {"key": "installed", "label": "Plugin collegato", "clients": len(installed)},
        {"key": "chatted", "label": "Prima conversazione", "clients": len(first_conversation)},
        {"key": "activated", "label": "Prima risposta utile", "clients": len(activated_ids)},
        {"key": "paid", "label": "Primo pagamento", "clients": len(paid_ids)},
    ]
    for step in steps:
        step["pct"] = round(step["clients"] / len(cohort) * 100, 1)

    hours = [
        (first_answer[c.id] - c.created_at).total_seconds() / 3600
        for c in cohort
        if c.id in first_answer and first_answer[c.id] >= c.created_at
    ]

    # the actionable part of a funnel is who is stuck in it, not the percentage
    stuck = [
        {
            "client_id": c.id,
            "name": c.name,
            "created_at": c.created_at,
            "reached": "chatted" if c.id in first_conversation else ("installed" if c.id in installed else "created"),
        }
        for c in cohort if c.id not in activated_ids
    ]
    stuck.sort(key=lambda r: r["created_at"])

    return {
        "window_days": max(days, 1),
        "cohort": len(cohort),
        # said out loud so nobody reads a smaller cohort as a drop in signups
        "undated_clients": undated,
        "steps": steps,
        "median_hours_to_activation": round(_median(hours), 1) if hours else None,
        "stuck": stuck,
    }


def at_risk_clients(session: Session, days: int = 14) -> dict:
    """Clients showing a concrete reason for concern, each spelled out.

    The window is compared against the one immediately before it, so "in calo" means measured
    against that client's own recent normal — not against other tenants, who may be far larger.
    """
    now = datetime.utcnow()
    window = max(days, 1)
    current_start = now - timedelta(days=window)
    previous_start = now - timedelta(days=window * 2)

    clients = {c.id: c for c in session.exec(select(Client)).all()}
    plans = {p.id: p for p in session.exec(select(Plan)).all()}
    if not clients:
        return {"window_days": window, "clients": []}

    def _counts(start, end):
        rows = session.exec(
            select(Conversation.client_id, func.count())
            .where(Conversation.created_at >= start, Conversation.created_at < end)
            .group_by(Conversation.client_id)
        ).all()
        return {cid: int(n) for cid, n in rows}

    current = _counts(current_start, now)
    previous = _counts(previous_start, current_start)
    last_seen = dict(session.exec(
        select(Conversation.client_id, func.max(Conversation.created_at)).group_by(Conversation.client_id)
    ).all())
    ratings = dict(session.exec(
        select(ConversationRating.client_id, func.avg(ConversationRating.score))
        .where(ConversationRating.created_at >= current_start)
        .group_by(ConversationRating.client_id)
    ).all())

    at_risk = []
    for cid, client in clients.items():
        reasons = []
        now_count, before_count = current.get(cid, 0), previous.get(cid, 0)

        if client.billing_status == "past_due":
            reasons.append("pagamento non riuscito")
        if client.subscription_cancel_at_period_end:
            reasons.append("disdetta programmata")
        if before_count >= 5 and now_count < before_count * 0.5:
            drop = round((1 - now_count / before_count) * 100)
            reasons.append(f"uso calato del {drop}%")
        seen = last_seen.get(cid)
        if seen and (now - seen).days >= window:
            reasons.append(f"nessuna conversazione da {(now - seen).days} giorni")
        if seen is None and client.created_at and (now - client.created_at).days >= 7:
            reasons.append("mai usato dopo la registrazione")
        score = ratings.get(cid)
        if score is not None and float(score) < 3:
            reasons.append(f"CSAT medio {float(score):.1f}")

        plan = plans.get(client.plan_id)
        if reasons:
            at_risk.append({
                "client_id": cid,
                "name": client.name,
                "plan": plan.name if plan else None,
                "billing_status": client.billing_status,
                "conversations_now": now_count,
                "conversations_before": before_count,
                "last_seen": seen,
                "reasons": reasons,
            })

    # most reasons first: a client failing on several fronts deserves the call before one that
    # merely went quiet
    at_risk.sort(key=lambda r: (len(r["reasons"]), r["conversations_before"]), reverse=True)
    if at_risk:
        log(logger, logging.INFO, "growth.at_risk", clients=len(at_risk))
    return {"window_days": window, "clients": at_risk}

"""What it costs us to serve each tenant, and what margin that leaves.

The token counts were already there: `AiResponseLog` records model, prompt tokens and
completion tokens for every `/chat` turn. This module only prices them and puts the result next
to the recurring revenue of the tenant's plan.

Two boundaries are deliberate, and both are reported rather than hidden:

- **A model without a price is not free.** Its turns are counted and its name is returned in
  `unpriced_models`, but its cost is left out of the total — an unpriced model must make the
  number look *incomplete*, never small.
- **This is inference cost only.** Embeddings (ingest), storage, email and channel fees are not
  in `AiResponseLog` and are therefore not here. The margin is a ceiling, not the final one.
"""
import logging
from datetime import datetime, timedelta

from sqlmodel import Session, func, select

from . import billing
from .db import AiResponseLog, Client, ModelPrice, Plan
from .logging_config import log

logger = logging.getLogger("wpai.costs")

TOKENS_PER_UNIT = 1_000_000  # providers quote prices per million tokens
MILLICENTS_PER_CENT = 1000


def price_per_million(millicents: int) -> float:
    """Stored price back to the provider's own figure, e.g. 15200 -> 0.152 per million."""
    return millicents / MILLICENTS_PER_CENT / 100


def to_millicents(price_per_million_units: float) -> int:
    """The provider's figure into storage: 0.152 per million -> 15200 thousandths of a cent."""
    return round(price_per_million_units * 100 * MILLICENTS_PER_CENT)


def turn_cost_cents(price: "ModelPrice | None", tokens_prompt: int, tokens_completion: int) -> float:
    """Cost of one AI turn in cents. Kept as a float: a single turn is worth a fraction of a
    cent, and rounding here instead of at the total would erase most of the spend."""
    if not price:
        return 0.0
    millicents = (
        tokens_prompt * price.input_millicents_per_million
        + tokens_completion * price.output_millicents_per_million
    ) / TOKENS_PER_UNIT
    return millicents / MILLICENTS_PER_CENT


def cost_summary(session: Session, days: int = 30) -> dict:
    """Per-tenant AI spend over the window, with the margin against recurring revenue.

    The window cost is also normalised to a monthly rate, because the revenue it is compared
    against is monthly: comparing 90 days of cost with one month of revenue would show a loss
    that does not exist.
    """
    since = datetime.utcnow() - timedelta(days=max(days, 1))
    prices = {row.model: row for row in session.exec(select(ModelPrice)).all()}
    plans = {plan.id: plan for plan in session.exec(select(Plan)).all()}
    clients = {client.id: client for client in session.exec(select(Client)).all()}

    usage = session.exec(
        select(
            AiResponseLog.client_id,
            AiResponseLog.model,
            func.count().label("turns"),
            func.sum(AiResponseLog.tokens_prompt).label("tokens_in"),
            func.sum(AiResponseLog.tokens_completion).label("tokens_out"),
        )
        .where(AiResponseLog.created_at >= since)
        .group_by(AiResponseLog.client_id, AiResponseLog.model)
    ).all()

    per_client: dict[int, dict] = {}
    unpriced: set[str] = set()
    currencies: set[str] = set()
    for client_id, model, turns, tokens_in, tokens_out in usage:
        tokens_in, tokens_out = int(tokens_in or 0), int(tokens_out or 0)
        price = prices.get(model or "")
        if not price and (tokens_in or tokens_out):
            unpriced.add(model or "(sconosciuto)")
        if price:
            currencies.add(price.currency)
        entry = per_client.setdefault(
            client_id,
            {"turns": 0, "tokens_in": 0, "tokens_out": 0, "cost": 0.0, "priced": True},
        )
        entry["turns"] += int(turns or 0)
        entry["tokens_in"] += tokens_in
        entry["tokens_out"] += tokens_out
        entry["cost"] += turn_cost_cents(price, tokens_in, tokens_out)
        if not price:
            entry["priced"] = False

    window = max(days, 1)
    rows, total_cost, total_revenue = [], 0.0, 0
    for client_id, entry in per_client.items():
        client = clients.get(client_id)
        if not client:
            continue  # a deleted tenant leaves logs behind; it has no revenue to compare
        plan = plans.get(client.plan_id)
        revenue = billing.monthly_value_cents(plan, client.subscription_interval)
        monthly_cost = entry["cost"] * 30 / window
        # only tenants whose spend is fully priced can be summed into a trustworthy total
        if entry["priced"]:
            total_cost += monthly_cost
        if client.billing_status in ("active", "past_due"):
            total_revenue += revenue
            if plan:
                currencies.add(plan.currency)
        rows.append({
            "client_id": client_id,
            "name": client.name,
            "plan": plan.name if plan else None,
            "billing_status": client.billing_status,
            "turns": entry["turns"],
            "tokens_in": entry["tokens_in"],
            "tokens_out": entry["tokens_out"],
            "cost_cents": round(entry["cost"], 2),
            "monthly_cost_cents": round(monthly_cost, 2),
            "monthly_revenue_cents": revenue,
            "monthly_margin_cents": round(revenue - monthly_cost, 2),
            "fully_priced": entry["priced"],
        })

    rows.sort(key=lambda r: r["monthly_cost_cents"], reverse=True)
    margin = total_revenue - total_cost
    if unpriced:
        log(logger, logging.INFO, "costs.unpriced_models", models=sorted(unpriced))
    # a provider billing in USD against plans priced in EUR is not a margin, it is two numbers
    # in different units. Say so rather than convert at a rate nobody chose.
    mixed = len(currencies) > 1
    return {
        "window_days": window,
        "monthly_cost_cents": round(total_cost, 2),
        "monthly_revenue_cents": total_revenue,
        "monthly_margin_cents": round(margin, 2),
        "margin_pct": round(margin / total_revenue * 100, 1) if total_revenue and not mixed else None,
        "currency": next(iter(currencies), "eur") if not mixed else None,
        "mixed_currencies": mixed,
        "currencies": sorted(currencies),
        # names, not a boolean: the superadmin has to know *which* price to add
        "unpriced_models": sorted(unpriced),
        "clients": rows,
    }

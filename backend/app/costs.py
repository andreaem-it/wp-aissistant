"""What it costs us to serve each tenant, and what margin that leaves.

The token counts were already there: `AiResponseLog` records model, prompt tokens and
completion tokens for every `/chat` turn. This module only prices them and puts the result next
to the recurring revenue of the tenant's plan.

Two boundaries are deliberate, and both are reported rather than hidden:

- **A model without a price is not free.** Its turns are counted and its name is returned in
  `unpriced_models`, but its cost is left out of the total — an unpriced model must make the
  number look *incomplete*, never small.
- **Measured and estimated stay apart.** Chat tokens and stored bytes are measured. Embedding
  tokens are not: Cloudflare returns only the vector, so they are derived from the exact
  character count with a declared ratio, and any tenant priced that way is flagged.
- **Email and channel fees are still not counted**, so the margin remains a ceiling — a smaller
  gap than before, but say so rather than imply completeness.
"""
import logging
import os
from datetime import datetime, timedelta

from sqlmodel import Session, func, select

from . import billing
from .db import AiResponseLog, Attachment, Client, EmbeddingUsage, MessagingUsage, ModelPrice, Plan
from .logging_config import log

logger = logging.getLogger("wpai.costs")

TOKENS_PER_UNIT = 1_000_000  # providers quote prices per million tokens

# Embedding providers bill per token but Cloudflare Workers AI returns only the vector, so what
# we can measure exactly is characters. This divisor turns them into tokens; it is an average,
# not a measurement, which is why any cost derived from it is reported as an estimate.
CHARS_PER_TOKEN = float(os.getenv("EMBEDDING_CHARS_PER_TOKEN", "4"))
# Object storage is billed per GB-month. Left unset the storage cost is *unknown*, not zero:
# reporting it as free would understate the margin exactly like an unpriced model would.
_STORAGE_PRICE = os.getenv("STORAGE_PRICE_PER_GB_MONTH_MILLICENTS", "").strip()
STORAGE_MILLICENTS_PER_GB_MONTH = int(_STORAGE_PRICE) if _STORAGE_PRICE.isdigit() else None
BYTES_PER_GB = 1024 ** 3
# Email e messaggi sui canali si pagano a messaggio, non a token. Come per lo storage, un canale
# senza prezzo ha costo **ignoto**, non zero: WhatsApp in particolare fattura per conversazione e
# per paese, quindi una tariffa piatta è un'approssimazione che va scelta da chi la conosce, non
# indovinata qui.
_MESSAGE_PRICE_ENV = {
    "email": "EMAIL_PRICE_PER_MESSAGE_MILLICENTS",
    "whatsapp": "WHATSAPP_PRICE_PER_MESSAGE_MILLICENTS",
}


def message_price_millicents(channel: str) -> "int | None":
    raw = os.getenv(_MESSAGE_PRICE_ENV.get(channel, ""), "").strip()
    return int(raw) if raw.isdigit() else None
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


def embedding_cost_cents(price: "ModelPrice | None", chars: int, tokens: int) -> tuple[float, bool]:
    """Cost of embedded text, and whether it had to be estimated.

    Embeddings are billed as input tokens. When the provider reported them we use them; when it
    did not, the characters we actually sent are divided by CHARS_PER_TOKEN. The caller is told
    which of the two happened so an approximation is never presented as a measurement.
    """
    if not price:
        return 0.0, False
    estimated = tokens <= 0
    effective = tokens if tokens > 0 else round(chars / CHARS_PER_TOKEN)
    millicents = effective * price.input_millicents_per_million / TOKENS_PER_UNIT
    return millicents / MILLICENTS_PER_CENT, estimated


def storage_cost_cents(size_bytes: int) -> "float | None":
    """Monthly cost of the bytes a tenant keeps stored, or None when no price is configured.

    None rather than zero: an unpriced resource must make the total look incomplete, exactly
    like a model without a price.
    """
    if STORAGE_MILLICENTS_PER_GB_MONTH is None:
        return None
    gigabytes = size_bytes / BYTES_PER_GB
    return gigabytes * STORAGE_MILLICENTS_PER_GB_MONTH / MILLICENTS_PER_CENT


def messaging_cost_cents(channel: str, messages: int) -> "float | None":
    """Costo dei messaggi usciti su un canale, o None se quel canale non ha un prezzo.

    None non è zero: significa che il totale è incompleto e va detto, come per lo storage.
    """
    price = message_price_millicents(channel)
    if price is None:
        return None
    return messages * price / MILLICENTS_PER_CENT


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
    unpriced_channels: set[str] = set()
    currencies: set[str] = set()

    def _entry(store, cid):
        return store.setdefault(cid, {
            "turns": 0, "tokens_in": 0, "tokens_out": 0, "cost": 0.0, "priced": True,
            "embedding_chars": 0, "embedding_cost": 0.0, "embedding_estimated": False,
            "storage_bytes": 0, "messages": {}, "messaging_cost": 0.0, "messaging_priced": True,
        })
    for client_id, model, turns, tokens_in, tokens_out in usage:
        tokens_in, tokens_out = int(tokens_in or 0), int(tokens_out or 0)
        price = prices.get(model or "")
        if not price and (tokens_in or tokens_out):
            unpriced.add(model or "(sconosciuto)")
        if price:
            currencies.add(price.currency)
        entry = _entry(per_client, client_id)
        entry["turns"] += int(turns or 0)
        entry["tokens_in"] += tokens_in
        entry["tokens_out"] += tokens_out
        entry["cost"] += turn_cost_cents(price, tokens_in, tokens_out)
        if not price:
            entry["priced"] = False

    # Embeddings: billed on ingest *and* on every question asked, so both are counted.
    since_day = since.date()
    for cid, model, ing, qry, tokens in session.exec(
        select(
            EmbeddingUsage.client_id, EmbeddingUsage.model,
            func.sum(EmbeddingUsage.ingest_chars), func.sum(EmbeddingUsage.query_chars),
            func.sum(EmbeddingUsage.tokens),
        )
        .where(EmbeddingUsage.day >= since_day)
        .group_by(EmbeddingUsage.client_id, EmbeddingUsage.model)
    ).all():
        chars = int(ing or 0) + int(qry or 0)
        price = prices.get(model or "")
        entry = _entry(per_client, cid)
        entry["embedding_chars"] += chars
        if not price and chars:
            unpriced.add(model or "(sconosciuto)")
            entry["priced"] = False
            continue
        if price:
            currencies.add(price.currency)
        cost, estimated = embedding_cost_cents(price, chars, int(tokens or 0))
        entry["embedding_cost"] += cost
        entry["embedding_estimated"] = entry["embedding_estimated"] or estimated

    # Storage is a stock, not a flow: what the tenant keeps, priced per GB-month. It is not
    # scaled by the window like the other costs — it is already a monthly figure.
    for cid, size in session.exec(
        select(Attachment.client_id, func.sum(Attachment.size_bytes)).group_by(Attachment.client_id)
    ).all():
        _entry(per_client, cid)["storage_bytes"] += int(size or 0)

    # Messaggi usciti per il traffico del tenant: email di supporto e messaggi sui canali. È un
    # flusso come l'inferenza, quindi si conta nella finestra e si normalizza a mese più sotto.
    for cid, channel, sent in session.exec(
        select(
            MessagingUsage.client_id,
            MessagingUsage.channel,
            func.sum(MessagingUsage.sent).label("sent"),
        )
        .where(MessagingUsage.day >= since_day)
        .group_by(MessagingUsage.client_id, MessagingUsage.channel)
    ).all():
        sent = int(sent or 0)
        if not sent:
            continue
        entry = _entry(per_client, cid)
        entry["messages"][channel] = entry["messages"].get(channel, 0) + sent
        cost = messaging_cost_cents(channel, sent)
        if cost is None:
            entry["messaging_priced"] = False
            unpriced_channels.add(channel)
        else:
            entry["messaging_cost"] += cost

    window = max(days, 1)
    rows, total_cost, total_revenue = [], 0.0, 0
    total_storage_bytes = 0
    any_estimated = False
    # I nostri tenant (piano interno) hanno spesa reale e ricavo zero. Non vanno nel margine —
    # ci comparirebbero come il cliente più in perdita del parco — ma nemmeno spariscono: la
    # loro spesa è **costo di piattaforma** e si dichiara a parte, come i canali senza prezzo.
    internal = billing.platform_client_ids(session)
    internal_cost = 0.0
    internal_rows = []
    for client_id, entry in per_client.items():
        client = clients.get(client_id)
        if not client:
            continue  # a deleted tenant leaves logs behind; it has no revenue to compare
        plan = plans.get(client.plan_id)
        revenue = billing.monthly_value_cents(plan, client.subscription_interval)
        storage_cost = storage_cost_cents(entry["storage_bytes"])
        total_storage_bytes += entry["storage_bytes"]
        any_estimated = any_estimated or entry["embedding_estimated"]
        # inference and embeddings are flows measured over the window; storage is already monthly
        monthly_cost = (
            (entry["cost"] + entry["embedding_cost"] + entry["messaging_cost"]) * 30 / window
            + (storage_cost or 0.0)
        )
        fully_priced = entry["priced"] and entry["messaging_priced"]
        if client_id in internal:
            if fully_priced:
                internal_cost += monthly_cost
            internal_rows.append({
                "client_id": client_id,
                "name": client.name,
                "plan": plan.name if plan else None,
                "monthly_cost_cents": round(monthly_cost, 2),
                "fully_priced": fully_priced,
            })
            continue
        # only tenants whose spend is fully priced can be summed into a trustworthy total
        if fully_priced:
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
            "cost_cents": round(entry["cost"] + entry["embedding_cost"] + entry["messaging_cost"], 2),
            "inference_cost_cents": round(entry["cost"], 2),
            "embedding_cost_cents": round(entry["embedding_cost"], 2),
            "embedding_chars": entry["embedding_chars"],
            "embedding_estimated": entry["embedding_estimated"],
            "storage_bytes": entry["storage_bytes"],
            "storage_cost_cents": round(storage_cost, 2) if storage_cost is not None else None,
            "messages": dict(sorted(entry["messages"].items())),
            "messaging_cost_cents": round(entry["messaging_cost"], 2),
            "messaging_priced": entry["messaging_priced"],
            "monthly_cost_cents": round(monthly_cost, 2),
            "monthly_revenue_cents": revenue,
            "monthly_margin_cents": round(revenue - monthly_cost, 2),
            "fully_priced": entry["priced"] and entry["messaging_priced"],
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
        # stessa logica dei modelli: i nomi, perché il superadmin deve sapere *quale* prezzo manca
        "unpriced_channels": sorted(unpriced_channels),
        "storage_bytes": total_storage_bytes,
        # None means "no price configured": the storage cost is missing from the total, not zero
        "storage_priced": STORAGE_MILLICENTS_PER_GB_MONTH is not None,
        # true when at least one tenant's embedding cost came from the character estimate
        "embedding_estimated": any_estimated,
        "chars_per_token": CHARS_PER_TOKEN,
        "clients": rows,
        # La nostra spesa, fuori dal margine e dichiarata: sostenere il widget sul nostro sito e
        # l'assistenza dentro il pannello dei clienti costa, e nasconderlo renderebbe il margine
        # più bello di quanto è.
        "internal_cost_cents": round(internal_cost, 2),
        "internal_clients": sorted(internal_rows, key=lambda r: r["monthly_cost_cents"], reverse=True),
    }

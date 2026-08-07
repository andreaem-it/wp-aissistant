"""WooCommerce shop settings as knowledge base content.

Shipping methods and payment gateways are configured in WooCommerce, not written on a page, so
they were missing from the knowledge base entirely — and "quali sono i metodi di spedizione?"
is one of the most common questions a shop gets. With nothing retrieved, the model answered
from what is true of shops in general, which is how invented carriers and prices reach a
visitor.

The plugin sends the settings **structured** and the wording is built here: the phrasing can
then be improved without asking every site to update the plugin, and one shop cannot end up
with a differently-worded knowledge base than another.

What is rendered is deliberately narrow: only what a visitor may ask and the shop has decided.
No API keys, no gateway credentials, no internal identifiers — this text goes into the context
window of a model that talks to the public.
"""


def _money(value: str, currency: str) -> str:
    clean = (value or "").strip()
    if not clean:
        return ""
    return f"{clean} {currency}".strip() if currency else clean


def render_settings(settings: dict) -> str:
    """Turn the plugin's payload into the text that gets embedded.

    Written the way a shop would describe its own options, not the way WooCommerce stores them.
    This text is the model's raw material: it quotes and paraphrases it, so administrative
    wording ("metodi configurati in questo negozio") comes back out at the visitor as an
    answer that reads like a settings dump. Phrasing here is customer-facing on purpose.

    Prose rather than a table, because a grid whose header lands in a different chunk than its
    rows loses its meaning on retrieval.

    Anything the shop has not configured is simply absent. An empty section would invite the
    model to fill it, which is the failure this whole feature exists to prevent.
    """
    currency = (settings.get("currency") or "").strip()
    lines: list[str] = []

    zone_lines: list[str] = []
    for zone in settings.get("shipping_zones") or []:
        # the fallback reads inside the sentence below: "per il resto del mondo"
        name = (zone.get("name") or "").strip() or "il resto del mondo"
        methods = [m for m in (zone.get("methods") or []) if (m.get("title") or "").strip()]
        if not methods:
            continue
        rendered = []
        for method in methods:
            title = method["title"].strip()
            cost = _money(method.get("cost", ""), currency)
            # "senza costi di spedizione" rather than "gratuita": the adjective would have to
            # agree with the method's name, whose gender we cannot know ("Ritiro" vs "Consegna")
            if method.get("free"):
                rendered.append(f"{title} senza costi di spedizione")
            elif cost:
                rendered.append(f"{title} a {cost}")
            else:
                rendered.append(title)
        zone_lines.append(f"Spedizioni disponibili per {name}: " + "; ".join(rendered) + ".")

    # niente intestazioni di sezione: ogni riga è già una frase compiuta, così il modello può
    # citarla o parafrasarla senza dover ricostruire il contesto da un titolo altrove
    if zone_lines:
        lines.extend(zone_lines)

    gateways = [g for g in (settings.get("payment_gateways") or []) if (g.get("title") or "").strip()]
    if gateways:
        if lines:
            lines.append("")
        rendered_gateways = []
        for gateway in gateways:
            title = gateway["title"].strip()
            description = (gateway.get("description") or "").strip()
            rendered_gateways.append(f"{title} ({description})" if description else title)
        lines.append("Pagamenti accettati: " + "; ".join(rendered_gateways) + ".")

    free_from = _money(settings.get("free_shipping_from", ""), currency)
    if free_from:
        lines.append("")
        lines.append(f"La spedizione è gratuita per ordini a partire da {free_from}.")

    return "\n".join(lines).strip()

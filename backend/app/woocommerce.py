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

    Written as prose rather than a table because it is retrieved as free text and read by a
    model: "Spedizione Italia: Corriere espresso, 7 EUR" survives chunking and quoting better
    than a grid whose header ends up in a different chunk than its rows.

    Anything the shop has not configured is simply absent. An empty section would invite the
    model to fill it, which is the failure this whole feature exists to prevent.
    """
    currency = (settings.get("currency") or "").strip()
    lines: list[str] = []

    zone_lines: list[str] = []
    for zone in settings.get("shipping_zones") or []:
        name = (zone.get("name") or "").strip() or "Resto del mondo"
        methods = [m for m in (zone.get("methods") or []) if (m.get("title") or "").strip()]
        if not methods:
            continue
        rendered = []
        for method in methods:
            title = method["title"].strip()
            cost = _money(method.get("cost", ""), currency)
            # a free method says so in words: "0 EUR" reads like a missing value
            if method.get("free"):
                rendered.append(f"{title} (gratuita)")
            elif cost:
                rendered.append(f"{title} ({cost})")
            else:
                rendered.append(title)
        zone_lines.append(f"- Zona {name}: " + "; ".join(rendered))

    # l'intestazione esce solo se sotto c'è davvero qualcosa: una sezione vuota è un invito a
    # riempirla, ed è la cosa che questo modulo esiste per evitare
    if zone_lines:
        lines.append("Metodi di spedizione configurati in questo negozio:")
        lines.extend(zone_lines)

    gateways = [g for g in (settings.get("payment_gateways") or []) if (g.get("title") or "").strip()]
    if gateways:
        if lines:
            lines.append("")
        lines.append("Metodi di pagamento accettati in questo negozio:")
        for gateway in gateways:
            title = gateway["title"].strip()
            description = (gateway.get("description") or "").strip()
            lines.append(f"- {title}" + (f": {description}" if description else ""))

    free_from = _money(settings.get("free_shipping_from", ""), currency)
    if free_from:
        lines.append("")
        lines.append(f"La spedizione è gratuita a partire da {free_from} di spesa.")

    return "\n".join(lines).strip()

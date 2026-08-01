"""Visitor language detection.

Deterministic on purpose: no extra LLM round-trip on the hot chat path, no network, and a
result that can be unit-tested. Short chat messages are exactly where statistical detectors are
weakest, so this scores function words — the small set of articles, pronouns and prepositions
that a language repeats constantly and rarely shares with its neighbours.

When the text is too short or ambiguous to say anything honest, we fall back to the browser
locale the widget sends, and finally to the tenant default. Guessing wrong is worse than
falling back: the visitor would get an answer in a language they didn't ask for.
"""

import re

# Languages the assistant can answer in. Adding one means adding its function words below and
# its strings to app/i18n.py — the two must stay in step.
SUPPORTED = ("it", "en", "es", "fr", "de", "pt")
DEFAULT = "it"

# Function words that are frequent *and* discriminative. Words shared across languages (e.g.
# "no" in it/es, "de" in es/fr/pt) are deliberately absent: they add noise, not signal.
_MARKERS: dict[str, set[str]] = {
    "it": {
        "il", "lo", "gli", "un", "una", "sono", "come", "dove", "quando", "perché", "posso",
        "vorrei", "grazie", "ciao", "questo", "questa", "mio", "mia", "molto", "anche", "però",
        "quanto", "quale", "ordine", "spedizione", "acquisto", "sito", "salve", "buongiorno",
    },
    "en": {
        "the", "is", "are", "how", "where", "when", "why", "can", "would", "thanks", "hello",
        "this", "that", "my", "your", "with", "about", "please", "order", "shipping", "want",
        "need", "does", "do", "have", "hi",
    },
    "es": {
        "el", "los", "las", "una", "es", "cómo", "dónde", "cuándo", "por", "qué", "puedo",
        "quiero", "gracias", "hola", "esto", "esta", "mi", "muy", "también", "pero", "cuánto",
        "pedido", "envío", "compra", "sitio", "buenos",
    },
    "fr": {
        "le", "les", "une", "est", "comment", "où", "quand", "pourquoi", "je", "peux",
        "voudrais", "merci", "bonjour", "cette", "mon", "ma", "très", "aussi", "mais",
        "combien", "commande", "livraison", "achat", "site", "salut",
    },
    "de": {
        "der", "die", "das", "ein", "eine", "ist", "wie", "wo", "wann", "warum", "ich", "kann",
        "möchte", "danke", "hallo", "diese", "mein", "sehr", "auch", "aber", "wie viel",
        "bestellung", "versand", "kauf", "seite", "guten",
    },
    "pt": {
        "os", "as", "uma", "é", "como", "onde", "quando", "porquê", "porque", "eu", "posso",
        "queria", "obrigado", "olá", "isto", "esta", "meu", "minha", "muito", "também", "mas",
        "quanto", "encomenda", "envio", "compra", "site", "bom",
    },
}

_WORD_RE = re.compile(r"[a-zà-öø-ÿ]+", re.IGNORECASE)
# Below this many recognised markers the answer is a coin flip, so we don't pretend to know.
MIN_MARKERS = 1


def normalize(code: str | None) -> str | None:
    """`it-IT`, `IT_it`, `it` → `it`, or None when it isn't a language we support."""
    if not code:
        return None
    base = re.split(r"[-_]", str(code).strip().lower())[0]
    return base if base in SUPPORTED else None


def score(text: str) -> dict[str, int]:
    """How many marker words of each language the text contains."""
    words = set(_WORD_RE.findall((text or "").lower()))
    return {lang: len(words & markers) for lang, markers in _MARKERS.items()}


def detect(text: str, hint: str | None = None, default: str = DEFAULT) -> str:
    """Best-effort language of `text`. `hint` is the browser locale sent by the widget: it
    breaks ties and covers messages too short to judge."""
    scores = score(text)
    best = max(scores.values()) if scores else 0
    if best >= MIN_MARKERS:
        winners = [lang for lang, value in scores.items() if value == best]
        if len(winners) == 1:
            return winners[0]
        # a tie: prefer the browser locale when it is one of the candidates
        hinted = normalize(hint)
        if hinted in winners:
            return hinted
        return sorted(winners)[0] if default not in winners else default
    return normalize(hint) or (default if default in SUPPORTED else DEFAULT)

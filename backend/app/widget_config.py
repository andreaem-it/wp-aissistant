"""La configurazione del widget, lato server.

Finora l'aspetto del widget è esistito **solo dentro WordPress** (`get_option(WPAI_OPTION)`): il
backend non lo conosceva e il pannello nemmeno. È il motivo per cui un configuratore nel pannello
non era una schermata da disegnare sopra qualcosa che c'era, ma la schermata più la cosa sotto.
Questa è la cosa sotto — per i clienti che WordPress non ce l'hanno, e per quelli che ce l'hanno
ma vogliono configurare da un posto solo.

**Il vocabolario non è scritto qui.** Vive in `sdk/widget/src/schema.js`, che è anche ciò che il
widget usa davvero, e arriva qui attraverso `sdk/widget/schema.json`, generato dalla build e
versionato. Una copia scritta a mano in Python sarebbe una seconda dichiarazione della stessa
cosa, e le due divergerebbero al primo valore aggiunto: il sintomo sarebbe un'opzione che il
pannello offre e il widget ignora, senza un errore da nessuna parte. `test_widget_config.py`
fallisce se le due copie non coincidono.
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("wpai")

# Il file generato sta nel repo, accanto al widget. In un'immagine che spedisce solo `backend/`
# non c'è: in quel caso si parte da un vocabolario vuoto e la validazione **rifiuta tutto** invece
# di accettare tutto, che è l'unico modo sicuro di sbagliare.
_SCHEMA_PATH = Path(
    os.getenv("WIDGET_SCHEMA_PATH")
    or Path(__file__).resolve().parents[2] / "sdk" / "widget" / "schema.json"
)


def _load() -> dict:
    try:
        return json.loads(_SCHEMA_PATH.read_text())
    except (OSError, ValueError):
        logger.warning("widget schema not readable at %s: appearance options disabled", _SCHEMA_PATH)
        return {"appearance": {}, "flags": {}, "defaultColor": "#635bff"}


_SCHEMA = _load()

APPEARANCE: dict = _SCHEMA.get("appearance", {})
FLAGS: dict = _SCHEMA.get("flags", {})
DEFAULT_COLOR: str = _SCHEMA.get("defaultColor", "#635bff")

# I testi che il cliente scrive. Non sono aspetto e non hanno un vocabolario: hanno un tetto di
# lunghezza, perché finiscono in una pagina pubblica e un campo senza limite è un invito.
TEXTS = {
    "title": 80,
    "subtitle": 120,
    "welcome": 500,
    "aiDisclosure": 500,
    "launcherLabel": 40,
    "inputPlaceholder": 80,
}
URLS = ("privacyUrl", "image")

MAX_URL_CHARS = 500


class ConfigError(ValueError):
    """Un valore rifiutato, con il motivo che arriva fino al cliente."""


def _clean_url(name: str, value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) > MAX_URL_CHARS:
        raise ConfigError(f"L'indirizzo in «{name}» è troppo lungo.")
    if not text.startswith(("https://", "http://")):
        raise ConfigError(f"L'indirizzo in «{name}» deve iniziare con https://.")
    return text


def normalise(payload: dict | None) -> dict:
    """La configurazione validata, pronta da servire al widget.

    Un valore di aspetto fuori vocabolario **non passa**: solleva, invece di ricadere in silenzio
    sul default. È la differenza fra il widget e il configuratore — il widget deve funzionare
    comunque e ripiega, il configuratore deve dire al cliente che quel valore non esiste, o si
    ritroverebbe un'impostazione salvata che non ha alcun effetto.
    """
    source = payload or {}
    if not isinstance(source, dict):
        raise ConfigError("Configurazione non valida.")

    appearance_in = source.get("appearance") or {}
    if not isinstance(appearance_in, dict):
        raise ConfigError("Le opzioni di aspetto devono essere un oggetto.")

    appearance: dict = {}
    for name, spec in APPEARANCE.items():
        if name not in appearance_in or appearance_in[name] is None:
            appearance[name] = spec["default"]
            continue
        value = appearance_in[name]
        if value not in spec["values"]:
            raise ConfigError(
                f"«{value}» non è un valore ammesso per {name}: "
                + ", ".join(spec["values"]) + "."
            )
        appearance[name] = value

    for name, default in FLAGS.items():
        value = appearance_in.get(name)
        appearance[name] = default if value is None else bool(value)

    colour = str(appearance_in.get("color") or "").strip() or DEFAULT_COLOR
    if not _is_hex(colour):
        raise ConfigError("Il colore deve essere esadecimale a sei cifre, per esempio #635bff.")
    appearance["color"] = colour

    texts_in = source.get("texts") or {}
    if not isinstance(texts_in, dict):
        raise ConfigError("I testi devono essere un oggetto.")
    texts: dict = {}
    for name, limit in TEXTS.items():
        value = str(texts_in.get(name) or "").strip()
        if len(value) > limit:
            raise ConfigError(f"Il testo «{name}» supera i {limit} caratteri.")
        texts[name] = value
    for name in URLS:
        texts[name] = _clean_url(name, texts_in.get(name))

    return {"appearance": appearance, "texts": texts}


def _is_hex(value: str) -> bool:
    return (
        len(value) == 7
        and value[0] == "#"
        and all(c in "0123456789abcdefABCDEF" for c in value[1:])
    )


def defaults() -> dict:
    """La configurazione di partenza di un tenant che non ha mai salvato niente."""
    return normalise({})


def vocabulary() -> dict:
    """Il vocabolario da mostrare al pannello, così i menu a tendina non lo riscrivono."""
    return {
        "appearance": {name: spec for name, spec in APPEARANCE.items()},
        "flags": FLAGS,
        "defaultColor": DEFAULT_COLOR,
        "textLimits": TEXTS,
        # Mancavano, e il configuratore non poteva disegnare i campi che non gli venivano
        # dichiarati: avatar e link privacy erano validati dal backend, salvabili, serviti al
        # widget — e invisibili al cliente. Le etichette erano già scritte nel pannello, il che
        # dice che dovevano esserci e che nessuno se n'è accorto.
        "urls": {name: MAX_URL_CHARS for name in URLS},
    }

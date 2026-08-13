"""Il rilascio corrente del plugin WordPress, nella forma che WordPress si aspetta.

Perché esiste: il plugin è distribuito da noi, non da WordPress.org, e un plugin auto-ospitato
**non riceve aggiornamenti** a meno che non sia lui a chiederli. Finora non li chiedeva: una
correzione raggiungeva solo chi reinstallava a mano, cioè nessuno. Questo modulo è la metà
server della risposta; l'altra metà è il controllo dentro il plugin.

Due scelte che vale la pena spiegare.

**Il manifest è pubblico.** Non contiene segreti — versione, indirizzo di uno zip, requisiti — e
chiuderlo dietro la `api_key` significherebbe che un sito con la chiave scaduta, sbagliata o non
ancora configurata smette di ricevere correzioni di sicurezza. È l'opposto di ciò che serve: la
licenza si applica alle risposte della chat, dove il controllo è server-side ed è già stretto,
non al diritto di avere l'ultima versione del codice. Un plugin *nulled* non ha bisogno di
scaricare il nostro zip: ha bisogno di una chiave che funzioni, e quella non gliela diamo.

**Lo zip non passa da qui.** Il manifest indica un percorso versionato e immutabile sul CDN. Il
backend risponde con qualche centinaio di byte; il megabyte lo serve R2, che è fatto per quello
e che non cade se il backend è in manutenzione proprio mentre mille siti aggiornano insieme.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

# Il file sta accanto a questo modulo: l'immagine Docker copia solo `backend/`, quindi un
# manifest in `wp-plugin/` semplicemente non esisterebbe a runtime.
RELEASE_FILE = Path(__file__).with_name("plugin_release.json")

CDN_BASE = os.getenv("PLUGIN_CDN_BASE", "https://cdn.wpaissistant.it").rstrip("/")

# Il nome della cartella del plugin dentro lo zip, che è anche la chiave con cui WordPress lo
# identifica nel transient degli aggiornamenti. Se qui e nel pacchetto divergessero, WordPress
# mostrerebbe l'aggiornamento e poi installerebbe un plugin *diverso* accanto a quello vecchio.
PLUGIN_SLUG = "wp-aissistant"
PLUGIN_BASENAME = f"{PLUGIN_SLUG}/{PLUGIN_SLUG}.php"


@lru_cache(maxsize=1)
def release() -> dict:
    """Il contenuto del manifest versionato. Letto una volta: cambia solo con un rilascio."""
    return json.loads(RELEASE_FILE.read_text(encoding="utf-8"))


def download_url(version: str | None = None) -> str:
    """Il percorso immutabile dello zip sul CDN, come per il widget."""
    return f"{CDN_BASE}/plugin/{version or release()['version']}/{PLUGIN_SLUG}.zip"


def manifest() -> dict:
    """La risposta di `GET /plugin/update`.

    I nomi dei campi sono quelli di WordPress e non i nostri: è la struttura che finisce dentro
    `site_transient_update_plugins`, e rinominarli qui vorrebbe dire tradurli nel plugin, cioè
    avere lo schema in due posti. `sections` alimenta la scheda dei dettagli.
    """
    data = release()
    version = data["version"]
    return {
        "slug": PLUGIN_SLUG,
        "plugin": PLUGIN_BASENAME,
        "name": "WP AIssistant",
        "version": version,
        "download_url": download_url(version),
        "requires": data.get("requires", ""),
        "tested": data.get("tested", ""),
        "requires_php": data.get("requires_php", ""),
        "last_updated": data.get("released_at", ""),
        "homepage": data.get("homepage", ""),
        "sections": {
            "changelog": "\n".join(f"<p>{line}</p>" for line in data.get("changelog", [])),
        },
    }

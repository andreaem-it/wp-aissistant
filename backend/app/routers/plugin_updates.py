"""Il canale di aggiornamento del plugin WordPress.

Un endpoint solo, pubblico, senza stato: WordPress lo interroga, confronta la versione con
quella installata e mostra l'avviso. Il ragionamento sta in `app/plugin_release.py`.

`Cache-Control` non è un dettaglio: ogni sito con il plugin chiede questo manifest, e WordPress
lo fa a ogni caricamento della pagina dei plugin se il transient è scaduto. Un'ora di cache al
bordo trasforma migliaia di richieste in poche, e il costo è che un rilascio impiega fino a
un'ora a comparire — accettabile per un aggiornamento che l'amministratore applica a mano
quando gli va bene.
"""
import logging

from fastapi import APIRouter, Response

from .. import plugin_release
from ..logging_config import log

logger = logging.getLogger("wpai")

router = APIRouter()


@router.get("/plugin/update")
def plugin_update(response: Response) -> dict:
    """Versione, indirizzo dello zip e requisiti dell'ultima release del plugin."""
    response.headers["Cache-Control"] = "public, max-age=3600"
    return plugin_release.manifest()

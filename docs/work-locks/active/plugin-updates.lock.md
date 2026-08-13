---
block: plugin-updates
owner: claude
started_at: 2026-08-14T00:20:00+02:00
expires_at: 2026-08-16T00:20:00+02:00
branch: main
---

Obiettivo: il plugin WordPress deve aggiornarsi da solo. Oggi non esiste nessun canale — nessun
filtro su `site_transient_update_plugins`, distribuzione auto-ospitata fuori da WordPress.org —
quindi una correzione raggiunge solo chi reinstalla a mano, e nessuno lo fa.

Tre pezzi, e sono lo stesso schema del widget:

1. **Lo zip sul CDN, versionato e immutabile**: `plugin/<versione>/wp-aissistant.zip`, pubblicato
   da un workflow su tag `plugin-v*` che costruisce con `build.sh`. Gli scaricamenti non passano
   dal backend.
2. **Il manifest dal backend**: `GET /plugin/update`, pubblico e senza segreti — versione,
   indirizzo dello zip, requisiti, changelog. Pubblico perché un sito che non ha ancora
   configurato la chiave deve poter aggiornare comunque: la licenza si applica alle risposte
   della chat, non al diritto di avere l'ultima versione del codice.
3. **Il controllo dentro il plugin**: `pre_set_site_transient_update_plugins` per l'avviso e
   l'aggiornamento, `plugins_api` per la scheda dei dettagli, con la risposta tenuta in un
   transient — WordPress interroga a ogni caricamento della pagina dei plugin.

La versione è dichiarata **una volta**: `build.sh` già rifiuta di costruire se l'header e la
costante `WPAI_VERSION` divergono. Il manifest del backend è una terza copia, quindi serve un
test che fallisca quando si scosta — stessa regola di `schema.json` e `schema.js`.

Il manifest sta sotto `backend/` e non in `wp-plugin/` perché l'immagine Docker copia solo
`backend/`: un file fuori da lì non esiste a runtime.

Perimetro previsto:
- `backend/app/plugin_release.py` e `plugin_release.json` (nuovi), `backend/app/routers/plugin_updates.py` (nuovo), `backend/app/main.py`
- `backend/tests/test_plugin_updates.py` (nuovo)
- `wp-plugin/wp-aissistant/wp-aissistant.php` (il controllo aggiornamenti; e `WPAI_BACKEND_URL`, che punta ancora all'URL grezzo di Railway)
- `.github/workflows/publish-plugin.yml` (nuovo)
- `docs/embedded-assistant-roadmap.md`, `docs/competitor-feature-backlog.md`

Fuori perimetro: il widget, il pannello, il sito, la fatturazione.

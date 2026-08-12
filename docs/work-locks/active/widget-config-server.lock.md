---
block: widget-config-server
owner: claude
started_at: 2026-08-12T19:10:00+02:00
expires_at: 2026-08-16T19:10:00+02:00
branch: main
---

Obiettivo: la configurazione del widget esiste **lato server**, per tenant, così il pannello può
produrre le stesse opzioni che oggi sa produrre solo la pagina del plugin. È la metà backend
della fase 3 di `docs/embedded-assistant-roadmap.md`; il configuratore e lo snippet nel pannello
seguono in un blocco separato, perché il primo pezzo è verificabile da solo e il secondo senza
il primo non esiste.

Il buco che questo blocco chiude: le opzioni di aspetto esistono **solo dentro WordPress**
(`get_option(WPAI_OPTION)`). Il backend non le conosce e il pannello nemmeno, quindi un
configuratore non è una schermata da disegnare sopra qualcosa che c'è — è la schermata più la
cosa sotto.

Vincolo che regge tutto: il vocabolario è già dichiarato una volta in `sdk/widget/src/schema.js`
(blocco `widget-extraction`). Il backend **non** lo riscrive a mano: lo legge da un artefatto
generato e versionato, e un test fallisce quando le due copie divergono. Tre liste scritte a mano
della stessa cosa sono il debito 5 dell'handoff daccapo.

Perimetro previsto:
- `sdk/widget/schema.json` + generatore in `sdk/widget/build.mjs` (artefatto condiviso)
- `backend/app/widget_config.py` (vocabolario letto dall'artefatto, validazione)
- `backend/app/db.py` (`WidgetConfig`), `backend/alembic/versions/0056_*.py`
- `backend/app/routers/accounts.py` (endpoint tenant-scoped), `tests/test_routes.py`
- `backend/tests/test_widget_config.py`
- `README.md`, `docs/competitor-feature-backlog.md`, `docs/embedded-assistant-roadmap.md`

Fuori perimetro (liberi per un altro agente):
- `panel/` — il configuratore, l'anteprima e lo snippet sono il blocco successivo
- `wp-plugin/` — la sorgente di verità fra pannello e pagina del plugin è una decisione a parte,
  scritta nella roadmap e non eseguita qui
- `website/`, `cloudflare/`, `sdk/browser/`

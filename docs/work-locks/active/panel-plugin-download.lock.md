---
block: panel-plugin-download
owner: claude
started_at: 2026-08-14T01:10:00+02:00
expires_at: 2026-08-15T01:10:00+02:00
branch: main
---

Obiettivo: il pulsante «Scarica il plugin» nel pannello prende versione e indirizzo da
`GET /plugin/update`, invece di dipendere da `VITE_PLUGIN_DOWNLOAD` — che è vuota in produzione,
quindi oggi la schermata dice «scarica dal collegamento che ti abbiamo inviato».

Non è solo una comodità: una variabile di build con dentro un URL versionato sarebbe la sesta
dichiarazione della versione del plugin, e l'unica che nessun test può legare alle altre perché
vive nella configurazione di Cloudflare Pages. L'endpoint la sa già ed è pubblico.

Il fallimento deve restare morbido: se l'endpoint non risponde si torna al testo di prima, non
un errore in faccia a chi sta cercando di installare.

Perimetro previsto:
- `panel/src/api.js`, `panel/src/Install.jsx`, `panel/src/Install.test.jsx`
- `docs/embedded-assistant-roadmap.md` (una riga)

Fuori perimetro: backend, widget, plugin, sito.

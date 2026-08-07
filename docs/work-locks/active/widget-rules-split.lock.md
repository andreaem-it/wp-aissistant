---
block: widget-rules-split
owner: claude
started_at: 2026-08-07T20:00:00+02:00
expires_at: 2026-08-08T20:00:00+02:00
branch: main
---

Obiettivo: estrarre dal widget le **regole di business pure** — disponibilità del supporto,
ammissibilità e corrispondenza dei messaggi proattivi, assegnazione della variante A/B — in
`chat-rules.js`, testabili sotto Node come già `chat-i18n.js`. Nessun cambiamento di
comportamento visibile al visitatore.

Perimetro previsto:
- `wp-plugin/wp-aissistant/assets/chat-rules.js` (nuovo)
- `wp-plugin/wp-aissistant/assets/chat-widget.js`
- `wp-plugin/wp-aissistant/wp-aissistant.php` (enqueue e versione)
- `wp-plugin/tests/rules.test.js` (nuovo), `CHANGELOG.md`, `readme.txt`
- `docs/handoff.md`

Fuori perimetro:
- backend, panel, worker Cloudflare
- il resto del widget: la parte che costruisce il DOM resta dov'è

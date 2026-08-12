---
block: domain-licence-visibility
owner: claude
started_at: 2026-08-12T14:20:00+02:00
expires_at: 2026-08-15T14:20:00+02:00
branch: main
---

Obiettivo: rendere visibile la licenza legata al dominio. Oggi il vincolo è applicato
(`domain-licence-enforcement`) ma un dominio non registrato si manifesta come «il widget non
c'è»: il backend risponde `403` con il motivo per esteso e non lo legge nessuno.

Al termine: il pannello ha la schermata dei siti coperti dalla licenza (registrare il dominio
live, quello di staging, vedere gli slot e i domini osservati), e il widget scrive in console il
motivo vero per chi installa, senza mostrare al visitatore né dettagli né un invito a riprovare
che non servirebbe a niente.

Perimetro previsto:
- `panel/src/api.js` (metodi sui domini)
- `panel/src/Settings.jsx` o un componente dedicato (sezione «Siti e licenza»)
- `panel/src/*.test.*` per la logica estratta
- `wp-plugin/wp-aissistant/assets/chat-widget.js` (gestione del 403 di licenza)
- `wp-plugin/wp-aissistant/assets/chat-i18n.js` + `wp-plugin/tests/i18n.test.js`
- `README.md`, `docs/competitor-feature-backlog.md`, `docs/embedded-assistant-roadmap.md`

Fuori perimetro (liberi per un altro agente):
- `backend/` — gli endpoint `/account/origins` esistono già e non cambiano
- `sdk/`, `website/`, `cloudflare/`
- L'estrazione del widget in `sdk/widget` e il CDN (fasi 1 e 2 della roadmap)
- Il tenant interno e il piano Illimitato (fase 0)

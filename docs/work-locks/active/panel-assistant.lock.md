---
block: panel-assistant
owner: claude
started_at: 2026-08-13T16:20:00+02:00
expires_at: 2026-08-15T16:20:00+02:00
branch: main
---

Obiettivo: fase 5 della roadmap dell'assistente incorporato — l'assistente dentro il pannello del
cliente, con la nostra knowledge base come corpus e il tenant loggato come soggetto.

Il punto delicato è che nella stessa conversazione ci sono due tenant: **noi rispondiamo**, il
cliente **è l'argomento**. Il contesto del cliente non arriva mai dal browser — il widget usa la
nostra `api_key` pubblica, che chiunque può leggere — ma viene derivato dal backend da un token
HMAC di 5 minuti firmato con un segreto server-only, sullo stesso schema di `wpai_user_token` che
è già in produzione nel plugin.

Perimetro previsto:
- `backend/app/panel_assistant.py` (nuovo: firma, verifica, contesto come whitelist)
- `backend/app/routers/panel_assistant.py` (nuovo: `POST /panel/assistant/token`)
- `backend/app/routers/widget.py` (accettare il token di pannello su `/chat` e `/chat/stream`)
- `backend/app/main.py` (registrazione del router)
- `backend/app/production_config.py` (il segreto di firma fra i controlli di produzione)
- `backend/tests/test_panel_assistant.py` (nuovo)
- `panel/src/Assistant.jsx` (nuovo), `panel/src/App.jsx`, `panel/src/api.js`
- `docs/embedded-assistant-roadmap.md`

Fuori perimetro: il widget in `sdk/widget` (il pannello lo importa dal workspace, non lo cambia),
il plugin WordPress, la fatturazione, il sito.

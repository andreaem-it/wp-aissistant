---
block: cors-write-methods
owner: claude
started_at: 2026-08-05T22:40:00+02:00
expires_at: 2026-08-06T22:40:00+02:00
branch: main
---

Obiettivo: le richieste PUT/PATCH/DELETE dal panel smettono di essere bloccate dal browser.
Le intestazioni CORS annunciano solo `GET, POST, OPTIONS`, mentre il backend espone 36 rotte di
scrittura con quei metodi: dal browser sono tutte irraggiungibili cross-origin.

Perimetro previsto:
- `backend/app/main.py` — **solo** `_cors_headers()`
- `backend/tests/test_security.py` (o nuovo test CORS)
- `panel/src/Admin.jsx` — messaggio d'errore del listino modelli, che oggi nasconde la causa

Fuori perimetro:
- logica di allowlist degli origin e `CORS_ALLOW_ALL` (invariati)
- tutto il resto del backend, del panel, dei canali e del plugin

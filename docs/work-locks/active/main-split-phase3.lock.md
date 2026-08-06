---
block: main-split-phase3
owner: claude
started_at: 2026-08-06T18:10:00+02:00
expires_at: 2026-08-07T18:10:00+02:00
branch: main
---

Obiettivo: **fase 3** della divisione di `main.py`. Prima far salire nei moduli di dominio i
cinque helper condivisi che bloccano l'API pubblica, poi estrarre `/v1` in
`routers/public_api.py`. Nessun cambiamento osservabile.

Perimetro previsto:
- `backend/app/analytics.py` (catena statistiche), `backend/app/notify.py`,
  `backend/app/whatsapp.py`, `backend/app/worker.py`, `backend/app/conversations.py` (nuovo)
- `backend/app/routers/public_api.py` (nuovo)
- `backend/app/main.py`, `backend/tests/test_routes.py`, `docs/handoff.md`

Fuori perimetro:
- canali, help desk, widget, automazioni, admin residuo: fasi successive
- panel, plugin, worker Cloudflare

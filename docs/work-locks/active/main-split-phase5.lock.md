---
block: main-split-phase5
owner: claude
started_at: 2026-08-07T10:00:00+02:00
expires_at: 2026-08-08T10:00:00+02:00
branch: main
---

Obiettivo: **fase 5** della divisione di `main.py`. Estrarre analytics, statistiche, CSAT e gap
della knowledge base in `routers/insights.py`. Nessun cambiamento osservabile.

Perimetro previsto:
- `backend/app/routers/insights.py` (nuovo), `backend/app/conversations.py`
- `backend/app/main.py`, `backend/tests/test_routes.py`, `docs/handoff.md`

Fuori perimetro:
- automazioni, help desk/inbox, widget e chat, admin residuo: fasi successive
- panel, plugin, worker Cloudflare

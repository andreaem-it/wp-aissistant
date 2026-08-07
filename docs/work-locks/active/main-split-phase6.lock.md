---
block: main-split-phase6
owner: claude
started_at: 2026-08-07T11:00:00+02:00
expires_at: 2026-08-08T11:00:00+02:00
branch: main
---

Obiettivo: **fase 6** della divisione di `main.py`. Far salire i vocabolari e le viste di lead e
messaggi proattivi nei rispettivi moduli di dominio, poi estrarre le automazioni — workflow,
proattivi, lead — in `routers/automations.py`. Nessun cambiamento osservabile.

Perimetro previsto:
- `backend/app/leads.py` e `backend/app/proactive.py` (nuovi), `backend/app/util.py`
- `backend/app/routers/automations.py` (nuovo)
- `backend/app/main.py`, `backend/tests/test_routes.py`, `docs/handoff.md`

Fuori perimetro:
- help desk/inbox, widget e chat, admin residuo: fasi successive
- panel, plugin, worker Cloudflare

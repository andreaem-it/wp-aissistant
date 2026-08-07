---
block: main-split-phase4
owner: claude
started_at: 2026-08-07T09:00:00+02:00
expires_at: 2026-08-08T09:00:00+02:00
branch: main
---

Obiettivo: **fase 4** della divisione di `main.py`. Far salire SLA/instradamento e l'identità
del contatto nei rispettivi moduli di dominio, poi estrarre i canali in ingresso e gli allegati
in `routers/channels.py`. Nessun cambiamento osservabile.

Perimetro previsto:
- `backend/app/routing.py` (nuovo), `backend/app/conversations.py`
- `backend/app/routers/channels.py` (nuovo)
- `backend/app/main.py`, `backend/tests/test_routes.py`, `docs/handoff.md`

Fuori perimetro:
- help desk/inbox, widget e chat, automazioni, admin residuo: fasi successive
- panel, plugin, worker Cloudflare

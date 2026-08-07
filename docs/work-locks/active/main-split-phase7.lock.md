---
block: main-split-phase7
owner: claude
started_at: 2026-08-07T12:00:00+02:00
expires_at: 2026-08-08T12:00:00+02:00
branch: main
---

Obiettivo: **fase 7** della divisione di `main.py`. L'area help desk conta 62 endpoint: troppi
per un router solo, che sarebbe un monolite più piccolo. Questa fase prende la parte
**configurazione e connettori** — reparti, SLA, instradamento, calendario, risposte predefinite,
campi informativi, CRM, help desk esterni, push — in `routers/helpdesk_config.py`.
L'inbox vera e propria (conversazioni, ticket, note, tag) va nella fase 8.

Perimetro previsto:
- `backend/app/routing.py`, `backend/app/crm.py`, `backend/app/helpdesk.py`
- `backend/app/routers/helpdesk_config.py` (nuovo)
- `backend/app/main.py`, `backend/tests/test_routes.py`, `docs/handoff.md`

Fuori perimetro:
- inbox e conversazioni, widget e chat, admin residuo: fasi successive
- panel, plugin, worker Cloudflare

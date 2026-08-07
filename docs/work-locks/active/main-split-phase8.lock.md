---
block: main-split-phase8
owner: claude
started_at: 2026-08-07T14:00:00+02:00
expires_at: 2026-08-08T14:00:00+02:00
branch: main
---

Obiettivo: **fase 8** della divisione di `main.py`. Estrarre l'inbox operatore — conversazioni,
ticket, tag, note, menzioni, presenza, viste salvate, GDPR — in `routers/inbox.py`, dopo aver
fatto salire in `conversations.py` i due helper condivisi con il widget e con la retention.

Perimetro previsto:
- `backend/app/conversations.py`, `backend/app/routers/inbox.py` (nuovo)
- `backend/app/main.py`, `backend/tests/test_routes.py`, `docs/handoff.md`

Fuori perimetro:
- widget e chat, admin residuo: fasi successive
- panel, plugin, worker Cloudflare

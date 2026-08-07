---
block: main-split-phase9
owner: claude
started_at: 2026-08-07T16:00:00+02:00
expires_at: 2026-08-08T16:00:00+02:00
branch: main
---

Obiettivo: **fase 9** della divisione di `main.py`. Estrarre la superficie del visitatore —
chat, streaming, RAG, escalation, carrello, lookup ordini, form e messaggi proattivi del widget,
registrazione plugin — in `routers/widget.py`, dopo aver fatto salire le utility di origin e le
dipendenze di rate limit.

Perimetro previsto:
- `backend/app/util.py`, `backend/app/deps.py`, `backend/conftest.py`
- `backend/app/routers/widget.py` (nuovo)
- `backend/app/main.py`, `backend/tests/test_routes.py`, `docs/handoff.md`

Fuori perimetro:
- `/admin`, autenticazione e account, ingest: fase finale
- panel, plugin, worker Cloudflare
